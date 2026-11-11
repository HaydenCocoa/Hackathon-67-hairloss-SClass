"use strict";

const form = document.querySelector("#generate-form");
const weekInput = document.querySelector("#week-start");
const intakeInput = document.querySelector("#intake-id");
const groupInput = document.querySelector("#group-number");
const button = document.querySelector("#generate");
const statusBox = document.querySelector("#status");
const resultBox = document.querySelector("#result");
const body = document.querySelector("#schedule-body");
const savePanel = document.querySelector("#save-panel");
const saveButton = document.querySelector("#save");
const confirmBox = document.querySelector("#save-confirm");
const saveSummary = document.querySelector("#save-summary");
const saveAck = document.querySelector("#save-ack");
const confirmButton = document.querySelector("#save-confirm-button");
const cancelButton = document.querySelector("#save-cancel");

// The preview currently on screen. It is only kept in memory: leaving or
// reloading the page discards it (accepted: no stored drafts in this phase).
let preview = null;

function status(message, tone = "") {
  statusBox.textContent = message;
  statusBox.dataset.tone = tone;
}

function cell(row, primary, secondary) {
  const td = document.createElement("td");
  td.textContent = String(primary);
  if (secondary) {
    const detail = document.createElement("small");
    detail.textContent = secondary;
    td.append(detail);
  }
  row.append(td);
}

function render(data, requestId = "") {
  const summary = document.querySelector("#summary");
  summary.replaceChildren();
  const metrics = [["Solver outcome", data.status], ["Proposed / required", `${data.placements.length} / ${data.required_count}`],
    ["Campus timezone", data.timezone], ["Engine elapsed", `${data.statistics.elapsed_seconds.toFixed(2)}s`]];
  for (const [label, value] of metrics) {
    const metric = document.createElement("div");
    metric.className = "metric";
    const name = document.createElement("span");
    name.textContent = label;
    const text = document.createElement("strong");
    text.textContent = value;
    metric.append(name, text);
    summary.append(metric);
  }
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: data.timezone, weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: data.timezone, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  // Preserve fractional seconds in display as well as the raw response.
  const showTime = value => {
    const fraction = value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1];
    return time.format(new Date(value)) + (fraction ? `.${fraction}` : "");
  };
  body.replaceChildren();
  for (const item of [...data.placements].sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.course_code.localeCompare(b.course_code))) {
    const row = document.createElement("tr");
    cell(row, day.format(new Date(item.starts_at)));
    cell(row, `${showTime(item.starts_at)} – ${showTime(item.ends_at)}`);
    cell(row, `${item.course_code} · ${item.course_type}`, item.course_name);
    cell(row, `Group ${item.group_number}`, item.intake_id);
    cell(row, item.room_name, item.room_building);
    cell(row, item.lecturer_id);
    cell(row, item.student_count);
    body.append(row);
  }
  document.querySelector("#schedule-caption").textContent = `Week of ${data.week_start} · ${data.timezone} · Intake ${data.intake_id} · ${data.group_number === null ? "All groups" : `Group ${data.group_number}`}`;
  document.querySelector("#schedule").hidden = !data.placements.length;
  const empty = document.querySelector("#empty");
  empty.hidden = !!data.placements.length;
  empty.textContent = data.status === "NO_PENDING_REQUIREMENTS" ? "There are no pending classes for this intake/group in the selected week." : "No complete timetable was generated. See the diagnostics below.";
  const diagnostics = document.querySelector("#diagnostics");
  diagnostics.replaceChildren();
  const messages = data.diagnostics.map(item => `${item.code}: ${item.detail}`);
  for (const item of data.candidate_failures) {
    for (const diagnostic of item.diagnostics) messages.push(`${item.occurrence_id} · ${diagnostic.code}: ${diagnostic.detail}`);
  }
  if (!messages.length) messages.push("All pending classes were assigned and verified. This preview does not reserve resources.");
  for (const message of messages) {
    const li = document.createElement("li");
    li.textContent = message;
    diagnostics.append(li);
  }
  document.querySelector("#revision").textContent = `Input revision: ${data.snapshot_revision}. Booking or roster changes can make this preview stale.`;
  document.querySelector("#raw").textContent = JSON.stringify(data, null, 2);
  preview = data.has_solution ? data : null;
  closeConfirm();
  saveButton.disabled = false;
  saveButton.textContent = "Save timetable…";
  savePanel.hidden = !preview;
  resultBox.hidden = false;
  const message = data.has_solution ? "Complete preview generated. Review the proposed classes below; nothing has been saved yet."
    : data.status === "UNKNOWN" ? "Search finished without a complete result. This does not prove the week is impossible."
    : data.status === "NO_PENDING_REQUIREMENTS" ? "No pending classes for this intake/group in the selected week."
    : "No complete timetable satisfies the current constraints. See diagnostics below.";
  status(message + (requestId ? ` Request ID: ${requestId}` : ""), data.has_solution ? "success" : data.status === "NO_PENDING_REQUIREMENTS" ? "" : "error");
}

// POST JSON and return { data, requestId }, or throw an Error carrying the
// API's error code and request ID. Shared by generate and save.
async function postJson(url, payload) {
  let requestId = "";
  try {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload), cache: "no-store",
    });
    requestId = response.headers?.get("X-Request-ID") || "";
    if (response.status === 401) {
      // Session expired or logged out: back to the login page, then here again.
      window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    }
    let data;
    try { data = await response.json(); } catch { throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`); }
    if (!response.ok) {
      const detail = data.detail;
      requestId = requestId || detail?.request_id || "";
      const message = Array.isArray(detail) ? detail.map(item => item.msg).join("; ")
        : typeof detail === "string" ? detail : detail?.message || "The request could not be completed.";
      const error = new Error(`HTTP ${response.status}${detail?.code ? ` [${detail.code}]` : ""}: ${message}`);
      error.code = detail?.code || "";
      throw error;
    }
    return { data, requestId };
  } catch (error) {
    const failure = error instanceof Error ? error : new Error("Could not reach the API server. Try again.");
    failure.requestId = requestId;
    throw failure;
  }
}

function setGenerateDisabled(disabled) {
  button.disabled = disabled;
  weekInput.disabled = disabled;
  intakeInput.disabled = disabled;
  groupInput.disabled = disabled;
}

function closeConfirm() {
  confirmBox.hidden = true;
  saveAck.checked = false;
  saveAck.disabled = false;
  confirmButton.disabled = true;
  cancelButton.disabled = false;
}

// Step 1 of 2: open the confirmation with a summary of what will be written.
saveButton.addEventListener("click", () => {
  if (!preview) return;
  const count = preview.placements.length;
  const scope = preview.group_number === null ? "all groups" : `group ${preview.group_number}`;
  saveSummary.textContent = `Save ${count} ${count === 1 ? "class" : "classes"} for intake ${preview.intake_id} (${scope}), week of ${preview.week_start}. `
    + "They become real bookings immediately and are visible to students and lecturers. This page cannot undo a save.";
  confirmBox.hidden = false;
  saveButton.disabled = true;
  saveAck.focus();
});
saveAck.addEventListener("change", () => { confirmButton.disabled = !saveAck.checked; });
cancelButton.addEventListener("click", () => {
  closeConfirm();
  saveButton.disabled = !preview;
  saveButton.focus();
});

// Step 2 of 2: only after the acknowledgement is ticked.
confirmButton.addEventListener("click", async () => {
  if (!preview || !saveAck.checked) return;
  const current = preview;
  setGenerateDisabled(true);
  confirmButton.disabled = true;
  cancelButton.disabled = true;
  saveAck.disabled = true;
  confirmButton.textContent = "Saving…";
  status("Rechecking the week against the database and saving all classes. Nothing is written unless every class still fits.");
  try {
    const { data, requestId } = await postJson("/api/schedules/save", {
      week_start: current.week_start, intake_id: current.intake_id, group_number: current.group_number,
      snapshot_revision: current.snapshot_revision,
      placements: current.placements.map(item => ({ occurrence_id: item.occurrence_id, room_id: item.room_id, starts_at: item.starts_at })),
    });
    preview = null;
    closeConfirm();
    saveButton.disabled = true;
    saveButton.textContent = "Saved";
    status(`Saved ${data.saved_count} ${data.saved_count === 1 ? "class" : "classes"} to the timetable.` + (requestId ? ` Request ID: ${requestId}` : ""), "success");
  } catch (error) {
    closeConfirm();
    if (error.code === "GENERATION_BUSY") {
      saveButton.disabled = false; // Nothing was attempted; the same preview can be saved again.
    } else {
      // The preview can no longer be trusted (stale, rejected, or an unknown outcome).
      preview = null;
      saveButton.disabled = true;
    }
    const advice = error.code === "GENERATION_BUSY" ? " Try saving again shortly." : " Generate a new preview before saving.";
    status(error.message + advice + (error.requestId ? ` Request ID: ${error.requestId}` : ""), "error");
  } finally {
    confirmButton.textContent = "Confirm save";
    setGenerateDisabled(false);
  }
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  const value = weekInput.value;
  const intakeId = intakeInput.value.trim();
  const group = groupInput.value.trim() === "" ? null : Number(groupInput.value);
  weekInput.setCustomValidity("");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || new Date(`${value}T00:00:00Z`).getUTCDay() !== 1) {
    weekInput.setCustomValidity("Choose a Monday for the start of the teaching week.");
    weekInput.reportValidity();
    return;
  }
  intakeInput.setCustomValidity("");
  groupInput.setCustomValidity("");
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(intakeId)) {
    intakeInput.setCustomValidity("Enter the intake's UUID from the database.");
    intakeInput.reportValidity();
    return;
  }
  if (group !== null && (!Number.isSafeInteger(group) || group < 1)) {
    groupInput.setCustomValidity("Group must be a positive whole number.");
    groupInput.reportValidity();
    return;
  }
  resultBox.hidden = true;
  preview = null;
  closeConfirm();
  setGenerateDisabled(true);
  button.textContent = "Generating…";
  status("Loading database inputs and generating a complete preview. This may take a little longer than the configured solver search limit.");
  try {
    const { data, requestId } = await postJson("/api/schedules/generate", { week_start: value, intake_id: intakeId, group_number: group });
    render(data, requestId);
  } catch (error) {
    resultBox.hidden = true;
    status(error.message + (error.requestId ? ` Request ID: ${error.requestId}` : ""), "error");
  } finally {
    setGenerateDisabled(false);
    button.textContent = "Generate preview";
  }
});
weekInput.addEventListener("input", () => weekInput.setCustomValidity(""));
intakeInput.addEventListener("input", () => intakeInput.setCustomValidity(""));
groupInput.addEventListener("input", () => groupInput.setCustomValidity(""));

// Pick the current campus week for convenience; the user can choose any Monday.
const local = new Intl.DateTimeFormat("en-CA", { timeZone: document.documentElement.dataset.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
const part = name => local.find(item => item.type === name).value;
const today = new Date(`${part("year")}-${part("month")}-${part("day")}T00:00:00Z`);
today.setUTCDate(today.getUTCDate() - (today.getUTCDay() + 6) % 7);
weekInput.value = today.toISOString().slice(0, 10);
