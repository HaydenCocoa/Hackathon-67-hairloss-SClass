# Scheduling API — quick guide for teammates

Last updated: 11 November 2026. Owner: backend (Hayden).

This page explains how to call the scheduling API. For design history, internals and test evidence, see the [full preview API record](schedule-preview-api.md).

## At a glance

| | |
| --- | --- |
| Endpoint | `POST /api/schedules/generate` |
| What it does | Proposes a clash-free timetable for one intake (optionally one group) for one week |
| Saves anything? | **No.** It is a read-only preview. Nothing is booked or published. |
| Who can call it | Only from your own machine (`localhost`), with `app.environment` set to `development`. There is no login yet. |
| Live reference | `http://127.0.0.1:8000/docs` (interactive) and `/openapi.json`, while the backend is running |

**Not available yet:** saving a timetable (step 10), and rescheduling, cancelling or reserving a class (step 11). Don't build UI that depends on these endpoints yet. The preview also doesn't optimise for gaps or room usage (step 8 is postponed), so a valid result can have long gaps between classes.

## Run it locally

From the repository root, with `.env` holding the Supabase URL and server key (see the [README](../../README.md)):

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

To try it without writing code, open `http://127.0.0.1:8000/development/scheduling-test-hayden`, pick a Monday, paste an intake UUID and click **Generate preview**.

From the Vue dev server (`npm run dev`, port 5173), call `/api/schedules/generate`; Vite proxies it to port 8000. That origin is on the allowed list in `Config/config.json`. This path has not been tested end to end yet. If you get `403`, see [Errors](#errors).

## Request

```http
POST /api/schedules/generate
Content-Type: application/json
```

```json
{
  "week_start": "2026-11-16",
  "intake_id": "00000000-0000-0000-0000-000000000001",
  "group_number": 1
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `week_start` | Yes | `YYYY-MM-DD` string, and it must be a **Monday**. The week is read in the campus timezone (`Asia/Kuala_Lumpur`). |
| `intake_id` | Yes | The intake's database UUID. |
| `group_number` | No | A positive integer. Omit it, or send `null`, to schedule **all groups** in the intake. |

Any other field is rejected. You don't send lecturers, rooms, durations or student lists; the backend reads all of these from the database.

The values above are placeholders. Use a real intake UUID from Supabase. An unknown intake or group isn't an error: it returns `status: "NO_PENDING_REQUIREMENTS"`.

### Example calls

PowerShell:

```powershell
$body = @{ week_start = '2026-11-16'; intake_id = '<intake-uuid>'; group_number = 1 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/schedules/generate -ContentType 'application/json' -Body $body
```

JavaScript (from the Vue app):

```js
const res = await fetch('/api/schedules/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ week_start: '2026-11-16', intake_id: intakeId, group_number: 1 }),
})
const data = await res.json()
if (!res.ok) throw new Error(`${data.detail?.code ?? res.status}: ${data.detail?.message ?? 'Request failed'}`)
```

## Response (HTTP 200)

A trimmed, illustrative example:

```json
{
  "week_start": "2026-11-16",
  "timezone": "Asia/Kuala_Lumpur",
  "status": "OPTIMAL",
  "has_solution": true,
  "required_count": 1,
  "scope": "intake_group",
  "intake_id": "00000000-0000-0000-0000-000000000001",
  "group_number": 1,
  "snapshot_revision": "<64-character hex fingerprint>",
  "placements": [
    {
      "occurrence_id": "<uuid>",
      "section_id": "<uuid>",
      "lecturer_id": "<uuid>",
      "room_id": "<uuid>",
      "intake_id": "00000000-0000-0000-0000-000000000001",
      "group_number": 1,
      "starts_at": "2026-11-16T01:17:00Z",
      "ends_at": "2026-11-16T03:17:00Z",
      "student_count": 40,
      "course_code": "DEMO101",
      "course_name": "Demo Course",
      "course_type": "lecture",
      "room_name": "Room A",
      "room_building": "Block A"
    }
  ],
  "diagnostics": [],
  "candidate_failures": [],
  "statistics": {
    "solver_ran": true,
    "max_time_seconds": 10.0,
    "num_search_workers": 1,
    "random_seed": 0,
    "elapsed_seconds": 0.42,
    "search_wall_time_seconds": 0.03,
    "branches": 0,
    "conflicts": 0
  },
  "quality_optimized": false,
  "quality": null
}
```

What to rely on:

- **Check `has_solution` first.** It is `true` only for `OPTIMAL` or `FEASIBLE`, and then `placements` holds every pending class exactly once. Otherwise `placements` is empty. A partial timetable is never returned.
- **Times are UTC.** Convert `starts_at` and `ends_at` to the `timezone` field for display (for example, `01:17Z` is 09:17 in Kuala Lumpur). Start times aren't on a fixed grid: 09:17 is valid, and seconds can be non-zero.
- **Only new classes appear in `placements`.** Classes that are already booked, and meetings, stay fixed and aren't listed.
- Lecturer and intake **names** aren't returned, only IDs. Course and room labels are included.
- `snapshot_revision` identifies the data the preview was built from. Treat it as an opaque string.

### `status` values

| `status` | `has_solution` | Meaning | Suggested UI |
| --- | --- | --- | --- |
| `OPTIMAL` | `true` | Complete clash-free timetable found | Show the placements |
| `FEASIBLE` | `true` | Complete clash-free timetable found | Show the placements |
| `NO_PENDING_REQUIREMENTS` | `false` | Nothing to schedule for that intake/group and week (also for an unknown ID) | "Nothing to schedule this week" |
| `INFEASIBLE` | `false` | No complete timetable is possible with current bookings and rooms | Show `diagnostics` / `candidate_failures` |
| `UNKNOWN` | `false` | The search ran out of time without an answer. This does **not** mean impossible. | Offer "Try again" |

`OPTIMAL` doesn't mean the timetable is optimised for quality. It means a valid timetable was found.

`diagnostics` items have a `code` (`NO_CANDIDATES`, `JOINT_CONSTRAINTS_INFEASIBLE`, `SEARCH_INCOMPLETE`, …), a readable `detail` and, where relevant, an `occurrence_id`. `candidate_failures` explains, per class, why no room or time was available. Show `detail` text as-is; don't parse it.

## Errors

Every non-200 response except `422` has this shape:

```json
{ "detail": { "code": "GENERATION_BUSY", "message": "Another preview is being generated. Try again shortly.", "request_id": "<uuid>" } }
```

| HTTP | `detail.code` | What to do |
| --- | --- | --- |
| 422 | (FastAPI validation list) | Fix the request: date isn't a Monday, bad UUID, `group_number` ≤ 0 or not an integer, or an extra field |
| 429 | `GENERATION_BUSY` | Another preview is running. Wait for `Retry-After` (2 s) and retry. |
| 403 | `LOCAL_ACCESS_ONLY` / `ORIGIN_NOT_ALLOWED` | Call from localhost, without a proxy that adds `X-Forwarded-*` headers, from an allowed origin |
| 404 | `DEVELOPMENT_DISABLED` | `app.environment` isn't `development` |
| 503 | `DATABASE_NOT_CONFIGURED` | Supabase URL/key missing in `.env` |
| 504 | `DATABASE_TIMEOUT` | Supabase was slow; retry |
| 502 | `DATABASE_UNAVAILABLE` or a data code such as `MISSING_ROSTER`, `EMPTY_ROSTER`, `BOOKING_MISMATCH`, `MISSING_ROOMS` | The database couldn't be read or its data is inconsistent. Tell the backend owner and include the `request_id`. |
| 500 | `MODEL_INVALID` / `GENERATION_FAILED` | Backend bug. Report it with the `request_id`. |

When reporting a problem, include the **`request_id`**. It is also sent in the `X-Request-ID` response header and lets the backend find the trace in `logs/scheduling.log`.

## Practical notes

- One request at a time per server. A request usually takes a few seconds; the search alone is capped at 10 s, and loading the data adds to that. Disable the button while waiting.
- Responses aren't cached (`Cache-Control: no-store`). Each call reads fresh data, so two calls can differ if someone changed bookings in between.
- The preview isn't stored anywhere and has no ID to fetch later. Keep the response in memory if you need to show it again.
- Two previews for different intakes don't know about each other, because nothing is saved. They can propose the same room at the same time until saving (step 10) exists.

## Related

- [Full preview API record](schedule-preview-api.md): design decisions, access rules and test evidence
- [Scheduling logging](scheduling-logging.md): reading traces by `request_id`
- [Backend record](agents.md) and [development checklist](../../task_hayden.md): what is done and what is planned
