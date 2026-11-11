# Step 10: saving a generated timetable

Implemented and verified locally: 11 November 2026. **Local development, admin use only. Not run against hosted Supabase.**

Related: [preview API record](schedule-preview-api.md), [backend record](agents.md), [checklist](../../task_hayden.md), [logging](scheduling-logging.md).

## Accepted decisions (11 November 2026)

| # | Topic | Decision |
| --- | --- | --- |
| — | Drafts | **No stored draft.** The preview exists only on the page. Leaving or reloading loses it, and the admin generates again. Saving writes real bookings immediately; there is no draft, approval or publish state. Reason: hackathon scope, ship quickly. |
| D1 | Who saves | Admin only. With no login yet, "admin only" is enforced the same way as the preview: `app.environment=development`, a direct localhost connection, an allowed Origin and no proxy headers. Login-based admin checks come with the login page. |
| D2 | Stale preview | Reject the save if anything in the week changed since the preview, and regenerate. |
| D3 | Concurrency | The backend rechecks, then writes with one insert. Safe against other saves through this backend process; **not** against writes from elsewhere (Supabase dashboard, another server process, the lecturer reschedule endpoint) during the short gap between the re-read and the insert. A database function would be fully safe; deferred. |
| D4 | Audit of who saved | Not implemented. To do once the login page exists, because `schedule_changes.changed_by` must reference a signed-in user and `action` currently only allows `cancel`/`reschedule`. Saves are traced in `logs/scheduling.log` with a request ID meanwhile. |
| D5 | Whole or partial | Whole preview only. |
| D6 | Viewing saved timetables | Out of scope for step 10. |
| D7 | Undo | No undo. Saving needs a two-step confirmation on the page. **Design remark for the future admin frontend:** keep a double confirmation (a summary step, then an explicit acknowledgement) before any save, because a save is immediately visible and cannot be undone from the UI. |

## Where the result is saved

Each placement becomes one row in the existing `public.class_sessions` table. No new table or migration.

| Written column | Value |
| --- | --- |
| `occurrence_id` | From the preview, checked against the database |
| `section_id` | From the database (the occurrence's section), never from the client |
| `room_id` | From the preview, revalidated |
| `starts_at` | From the preview, revalidated (UTC) |
| `status` | `scheduled` |

Existing database rules then apply: one booking per occurrence (`class_session_occurrence_unique`), occurrence/section must match, cancelled occurrences cannot be booked, the occurrence's target week is synced, and every write takes the shared advisory lock. Other users see saved classes through `class_session_details` under existing row-level security.

## API: `POST /api/schedules/save`

Request: the preview's scope, its `snapshot_revision`, and **every** placement with only three fields.

```json
{
  "week_start": "2026-11-16",
  "intake_id": "<intake-uuid>",
  "group_number": 1,
  "snapshot_revision": "<64-character hex from the preview>",
  "placements": [
    { "occurrence_id": "<uuid>", "room_id": "<uuid>", "starts_at": "2026-11-16T01:17:00Z" }
  ]
}
```

`week_start`, `intake_id` and `group_number` follow the preview's rules. `snapshot_revision` must be 64 lowercase hex characters. `placements` must have 1–1000 items; `starts_at` must include a timezone; any extra field is rejected (422, before any database call).

Server steps, holding the **same one-at-a-time slot as generation** (a save never runs alongside a preview or another save in this process):

1. Re-read the week with the existing loader and narrow it to the same intake/group (`select_scope`).
2. If the recalculated revision differs from `snapshot_revision` → `409 PREVIEW_STALE`.
3. If the placements are not exactly the pending occurrences in scope, each once → `422 PLACEMENTS_INCOMPLETE`.
4. Revalidate each placement with `BookingValidator`, then run the solver's own placement verification (`verify_placements`) for clashes between the new classes → `409 PLACEMENT_CONFLICT` with the validator's reason codes.
5. Insert all rows in **one** PostgREST request (`Prefer: return=representation`). One statement, so all rows are written or none.
6. Check Supabase returned one row per occurrence.

Success: `201` with `status: "SAVED"`, `saved_count`, the scope, the revision, and `saved: [{occurrence_id, class_session_id}]`.

### Errors

All use the existing shape `{"detail": {"code", "message", "request_id"}}` except FastAPI's 422 validation list.

| HTTP | Code | Meaning | Written? |
| --- | --- | --- | --- |
| 422 | (validation list) | Malformed request | No |
| 422 | `PLACEMENTS_INCOMPLETE` | Missing, duplicate or unknown placements | No |
| 409 | `PREVIEW_STALE` | Week changed since the preview, or it was already saved | No |
| 409 | `PLACEMENT_CONFLICT` | A placement fails validation or two placements clash | No |
| 409 | `ALREADY_SAVED` | The database reported a duplicate booking (written by someone else after the recheck) | No |
| 409 | `SAVE_REJECTED_BY_DATABASE` | A database check/trigger rejected the insert | No |
| 429 | `GENERATION_BUSY` | A preview or save is running; `Retry-After: 2` | No |
| 502 | `DATABASE_PERMISSION_DENIED` | Server key cannot write `class_sessions` | No |
| 502 | `DATABASE_UNAVAILABLE` / loader data codes | Read or write failed | No |
| 502 | `SAVE_UNCONFIRMED` | Supabase's reply did not list every saved class | Unknown — regenerate to check |
| 504 | `DATABASE_TIMEOUT` | Timed out while reading | No |
| 504 | `SAVE_OUTCOME_UNKNOWN` | Timed out during the insert | Unknown — regenerate to check |
| 500 | `SAVE_FAILED` | Internal error | Unknown — regenerate to check |
| 403 / 404 / 503 | existing codes | Access, environment, configuration | No |

Provider messages, details and hints are never returned or logged; only the HTTP status and an allowlisted Postgres error code are kept for classification.

**Retries:** a retried save after success is rejected as `PREVIEW_STALE` (the new bookings change the revision), and the unique occurrence constraint blocks duplicates in any case. After an "unknown" outcome, regenerating shows `NO_PENDING_REQUIREMENTS` if the save went through.

## Development page

At `/development/scheduling-test-hayden`, a **Save timetable** panel appears only for a complete preview (`has_solution`).

1. **Save timetable…** opens a confirmation showing the class count, intake, group and week, and that the save is immediate and cannot be undone.
2. **Confirm save** stays disabled until the acknowledgement box is ticked. **Cancel** closes it without saving.

While saving, generation and confirmation controls are disabled. On success the button shows **Saved** and stays disabled. On `GENERATION_BUSY` the same preview can be saved again; on any other error the preview is discarded and the page asks for a new one. The page's notice now says previews are not stored and saves cannot be undone.

## Code changes

| File | Change |
| --- | --- |
| `backend/app/scheduling/save.py` (new) | Request/response models, `prepare_rows` (revision, completeness and validation checks) and `SaveRejected` |
| `backend/app/scheduling/preview.py` | `SaveRequest`, `POST /api/schedules/save` sharing the generation slot and access checks; `failure()` takes an optional log event name |
| `backend/app/scheduling/solver.py` | `_verify_placements` renamed to public `verify_placements`; the old name stays as an alias |
| `backend/app/student.py` | Shared `Supabase` client gains `insert()` (one bulk POST) and `SupabaseWriteError` |
| `backend/app/observability.py` | Request tracing covers the save path; `saved_count` is an allowed trace field |
| `backend/app/scheduling/development/*` | Save panel, two-step confirmation, updated notice text, shared `postJson` helper |

Trace events: `save_started` (placement count), `save_validated` (row count), `save_completed` (saved count), `save_rejected` (HTTP status and code), `save_write_failed` (provider status and allowlisted code), `save_failed` (exception type and stack locations). No IDs, rosters or provider text.

## Verification (11 November 2026)

Using the project `.venv` (Python 3.12.3) and local synthetic data only; no hosted Supabase project was contacted.

- **30 new API tests passed** (`backend/tests/test_schedule_save.py`): full save in one insert with only booking columns, section from the database, retry rejected and next preview empty, group scope, stale revision and scope mismatch, partial/duplicate/unknown placements, edited start/room failing revalidation, eight malformed requests rejected before any database call, six provider write-failure classifications without leaking provider text, write timeout, shared slot with generation, access rules, traces and OpenAPI.
- **19 page tests passed** (Node/jsdom), including 6 new save-flow tests and a served-page test that saves through the real backend over HTTP against the synthetic QA service on port 8001 (stopped afterwards).
- **Full backend suite: 170 passed, 10 failed, 95 errors, 1 skipped.** Before this work, on `main`, it was 140 passed with the **same** 10 failures and 95 errors. Those are pre-existing and unrelated to saving: validator/candidate/solver fixtures still pass the removed `required_room_type` field (95 errors), and loader/preview tests still expect pre-11-November RPC behaviour (10 failures). They were not changed in this task.
- Not verified: a real save against hosted Supabase (permissions, triggers and the unique constraint under real PostgREST), visual browser rendering, and behaviour with multiple server processes.

## Known limits

- The week is read with several separate requests, not one database snapshot; the revision check and the insert's advisory lock narrow but do not remove the race with writers outside this backend (D3).
- `backend/app/lecturer.py`'s reschedule endpoint (`PATCH /api/lecturers/{id}/sessions/{id}`) writes `class_sessions` directly without validation or the scheduling slot. It was not changed (out of scope), but it is one of those outside writers.
- The slot is per server process.
- No audit record of who saved (D4); no undo (D7).
