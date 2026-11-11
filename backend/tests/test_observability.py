import json
import logging
from uuid import uuid4

from backend.app import observability


def test_json_file_logging_is_idempotent_and_omits_unapproved_fields(tmp_path, monkeypatch):
    logger = logging.getLogger("sclass.trace-test." + uuid4().hex)
    monkeypatch.setattr(observability, "LOGGER", logger)
    try:
        observability.configure_scheduling_logging(tmp_path)
        observability.configure_scheduling_logging(tmp_path)
        token = observability.REQUEST_ID.set("test-trace-id")
        try:
            observability.event("test_event", http_status=502, provider_code="PGRST202", headers="SECRET-KEY", payload="STUDENT-RECORD")
            logger.error("PRIVATE-EXCEPTION-MESSAGE", exc_info=True)
        finally:
            observability.REQUEST_ID.reset(token)
        assert len(logger.handlers) == 2
        text = (tmp_path / "scheduling.log").read_text(encoding="utf-8")
        records = [json.loads(line) for line in text.splitlines()]
        assert records[0]["request_id"] == "test-trace-id"
        assert records[0]["provider_code"] == "PGRST202"
        assert records[1]["event"] == "unstructured_log_omitted"
        assert all(value not in text for value in ("SECRET-KEY", "STUDENT-RECORD", "PRIVATE-EXCEPTION-MESSAGE"))
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_file_permission_failure_keeps_console_logging_safe(tmp_path, monkeypatch, capsys):
    logger = logging.getLogger("sclass.trace-test." + uuid4().hex)
    monkeypatch.setattr(observability, "LOGGER", logger)

    def unavailable(*args, **kwargs):
        raise PermissionError("PRIVATE-PATH-DETAILS")

    monkeypatch.setattr(observability, "RotatingFileHandler", unavailable)
    try:
        observability.configure_scheduling_logging(tmp_path)
        record = json.loads(capsys.readouterr().err)
        assert record["event"] == "file_logging_unavailable"
        assert record["exception_type"] == "PermissionError"
        assert "PRIVATE-PATH-DETAILS" not in json.dumps(record)
        assert len(logger.handlers) == 1
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
