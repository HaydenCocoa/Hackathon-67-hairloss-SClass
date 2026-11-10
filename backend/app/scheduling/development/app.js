"use strict";

const form = document.querySelector("#generate-form");
const weekInput = document.querySelector("#week-start");
const button = document.querySelector("#generate");
const statusBox = document.querySelector("#status");
const resultBox = document.querySelector("#result");
const body = document.querySelector("#schedule-body");

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

function render(data) {
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
  document.querySelector("#schedule-caption").textContent = `Week of ${data.week_start} · ${data.timezone}`;
  document.querySelector("#schedule").hidden = !data.placements.length;
  const empty = document.querySelector("#empty");
  empty.hidden = !!data.placements.length;
  empty.textContent = data.status === "NO_PENDING_REQUIREMENTS" ? "There are no pending classes to schedule for this week." : "No complete timetable was generated. See the diagnostics below.";
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
  resultBox.hidden = false;
  const message = data.has_solution ? "Complete preview generated. Review the proposed classes below; nothing has been saved."
    : data.status === "UNKNOWN" ? "Search finished without a complete result. This does not prove the week is impossible."
    : data.status === "NO_PENDING_REQUIREMENTS" ? "No pending classes for this week."
    : "No complete timetable satisfies the current constraints. See diagnostics below.";
  status(message, data.has_solution ? "success" : data.status === "NO_PENDING_REQUIREMENTS" ? "" : "error");
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const value = weekInput.value;
  weekInput.setCustomValidity("");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || new Date(`${value}T00:00:00Z`).getUTCDay() !== 1) {
    weekInput.setCustomValidity("Choose a Monday for the start of the teaching week.");
    weekInput.reportValidity();
    return;
  }
  resultBox.hidden = true;
  button.disabled = true;
  weekInput.disabled = true;
  button.textContent = "Generating…";
  status("Loading database inputs and generating a complete preview. This may take a little longer than the configured solver search limit.");
  try {
    const response = await fetch("/api/schedules/generate", {
      method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ week_start: value }), cache: "no-store",
    });
    let data;
    try { data = await response.json(); } catch { throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`); }
    if (!response.ok) {
      const detail = data.detail;
      const message = Array.isArray(detail) ? detail.map(item => item.msg).join("; ")
        : typeof detail === "string" ? detail : detail?.message || "The request could not be completed.";
      throw new Error(`HTTP ${response.status}: ${message}`);
    }
    render(data);
  } catch (error) {
    resultBox.hidden = true;
    status(error instanceof Error ? error.message : "Could not reach the API server. Try again.", "error");
  } finally {
    button.disabled = false;
    weekInput.disabled = false;
    button.textContent = "Generate preview";
  }
});
weekInput.addEventListener("input", () => weekInput.setCustomValidity(""));

// Pick the current campus week for convenience; the user can choose any Monday.
const local = new Intl.DateTimeFormat("en-CA", { timeZone: document.documentElement.dataset.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
const part = name => local.find(item => item.type === name).value;
const today = new Date(`${part("year")}-${part("month")}-${part("day")}T00:00:00Z`);
today.setUTCDate(today.getUTCDate() - (today.getUTCDay() + 6) % 7);
weekInput.value = today.toISOString().slice(0, 10);
