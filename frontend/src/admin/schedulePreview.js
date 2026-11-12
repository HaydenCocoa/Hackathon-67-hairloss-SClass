// Pure helpers for /admin/schedule (no Vue, no fetch): request bodies, plain-language outcomes and
// errors, and the preview's rows and filters. API: POST /api/schedules/generate and /api/schedules/save.
import { addDays, campusParts, formatRange, weekLabel } from './roomCalendar.js'

const uniqueSorted = (ids) => [...new Set(ids.map(String))].sort()

/** Identifies a selection, so the page can tell when the preview no longer matches it. */
export const selectionKey = (week, intakeIds) => `${week}|${uniqueSorted(intakeIds).join(',')}`

export const generateBody = (week, intakeIds) => ({ week_start: week, intake_ids: uniqueSorted(intakeIds) })

/** The save request for a preview: its own week, intakes and revision, and every placement unchanged. */
export const saveBody = (preview) => ({
  week_start: preview.week_start,
  intake_ids: preview.intake_ids,
  snapshot_revision: preview.snapshot_revision,
  placements: preview.placements.map(({ occurrence_id, room_id, starts_at }) => ({ occurrence_id, room_id, starts_at })),
})

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Headline for a generate response: { tone: success | warning | error | neutral, title, text }. */
export function outcome(preview) {
  const count = preview.placements.length
  if (preview.has_solution) {
    return {
      tone: 'success',
      title: `${plural(count, 'class', 'classes')} ready to schedule`,
      text: 'Every pending class has a room and time that pass all compulsory rules. Review the timetable below; nothing is saved until you choose Schedule with preview.',
    }
  }
  if (preview.status === 'NO_PENDING_REQUIREMENTS') {
    return {
      tone: 'neutral',
      title: 'Nothing to schedule',
      text: 'The selected intakes have no unscheduled classes in this week. They may already be scheduled, or have no teaching plan for this week.',
    }
  }
  if (preview.status === 'INFEASIBLE') {
    const blocked = preview.unplaced?.length || 0
    return {
      tone: 'error',
      title: 'No complete timetable is possible',
      text: blocked
        ? `${plural(blocked, 'class', 'classes')} cannot be placed in any room at any time this week (see below). Nothing can be scheduled until that is fixed.`
        : 'The classes cannot all fit together without breaking a compulsory rule. Try fewer intakes, or another week.',
    }
  }
  if (preview.status === 'UNKNOWN') {
    return {
      tone: 'warning',
      title: 'The search stopped before finding a timetable',
      text: 'This does not prove the week is impossible. Regenerate, or select fewer intakes.',
    }
  }
  return { tone: 'error', title: 'The preview could not be completed', text: 'Regenerate the preview. If this repeats, report the request ID.' }
}

/** What the person should do after an API error, by its code. */
export function errorAdvice(code) {
  return ({
    GENERATION_BUSY: 'Another preview or save is running. Wait a moment and try again.',
    PREVIEW_STALE: 'Bookings or teaching data changed since this preview. Regenerate it and review again.',
    ALREADY_SAVED: 'Some of these classes were booked meanwhile. Regenerate the preview.',
    PLACEMENTS_INCOMPLETE: 'Regenerate the preview and schedule it as a whole.',
    PLACEMENT_CONFLICT: 'A class no longer fits. Regenerate the preview.',
    SAVE_OUTCOME_UNKNOWN: 'Regenerate the preview to see whether the classes were saved before trying again.',
    AUDIT_NOT_INSTALLED: 'Ask the project owner to apply the save-audit database migration.',
    DEVELOPMENT_DISABLED: 'Scheduling runs only on the local development server; it is not available on this deployment.',
    LOCAL_ACCESS_ONLY: 'Scheduling runs only on the local development server; open this page there.',
    ORIGIN_NOT_ALLOWED: 'Open this page from the same server that runs the backend.',
  })[code] || ''
}

/** Errors after which the same preview can be scheduled again (nothing was attempted). */
export const keepsPreview = (code) => code === 'GENERATION_BUSY' || code === 'NETWORK'

const minutesText = (minutes) => (minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m` : `${minutes} min`)

/** Short figures for the summary cards. names = { intakes: Map, lecturers: Map }. */
export function summaryCards(preview) {
  const cards = [
    { label: 'Classes', value: `${preview.placements.length} / ${preview.required_count}`, hint: 'placed / needed' },
    { label: 'Intakes', value: String(preview.intake_ids.length), hint: 'scheduled together' },
    { label: 'Rooms used', value: String(new Set(preview.placements.map((p) => p.room_id)).size), hint: 'different rooms' },
  ]
  const q = preview.quality
  if (q) {
    cards.push(
      { label: 'Student waiting', value: `${q.student_idle_minutes_average} min`, hint: `average per student-day · worst ${q.student_idle_minutes_max} min` },
      { label: 'Lecturer gaps', value: `${q.lecturer_idle_minutes_total} min`, hint: `in total · worst day ${q.lecturer_idle_minutes_max} min` },
      { label: 'Seat use', value: `${q.seat_use_percent}%`, hint: `${q.empty_seats_total} empty seats` },
      { label: 'Longest student day', value: minutesText(q.longest_student_day_minutes), hint: 'first to last class' },
    )
  }
  cards.push({ label: 'Search time', value: `${Math.round(preview.statistics.elapsed_seconds)} s`, hint: preview.quality_optimized ? 'ranked by preferences' : 'first valid timetable' })
  return cards
}

/** Placements with display fields, sorted by time then course. */
export function placementRows(preview, names = {}) {
  const intakes = names.intakes || new Map()
  const lecturers = names.lecturers || new Map()
  return [...preview.placements]
    .map((p) => {
      const start = campusParts(p.starts_at)
      const end = campusParts(p.ends_at)
      return {
        ...p,
        day: start.date,
        time: formatRange(start.minutes, end.date === start.date ? end.minutes : 24 * 60),
        intake_code: intakes.get(String(p.intake_id)) || 'Unknown intake',
        lecturer_name: lecturers.get(String(p.lecturer_id)) || 'Unknown lecturer',
      }
    })
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.course_code.localeCompare(b.course_code))
}

export const FILTER_KINDS = [
  { value: 'intake', label: 'Intake' },
  { value: 'room', label: 'Room' },
  { value: 'lecturer', label: 'Lecturer' },
]

const filterKey = { intake: 'intake_id', room: 'room_id', lecturer: 'lecturer_id' }

/** Choices for "Show" (one intake, room or lecturer), each with how many classes it has. */
export function filterChoices(rows, kind) {
  const label = { intake: (r) => r.intake_code, room: (r) => `${r.room_name} · ${r.room_building}`, lecturer: (r) => r.lecturer_name }[kind]
  const choices = new Map()
  for (const row of rows) {
    const id = String(row[filterKey[kind]])
    const entry = choices.get(id) || { value: id, label: label(row), count: 0 }
    entry.count += 1
    choices.set(id, entry)
  }
  return [...choices.values()].sort((a, b) => a.label.localeCompare(b.label, 'en', { numeric: true }))
}

export const matchesFilter = (row, kind, value) => value === 'all' || String(row[filterKey[kind]]) === String(value)

/** "Week of 16 – 22 Nov 2026" */
export const weekTitle = (monday) => `Week of ${weekLabel(monday)}`

/** Days of the preview week that have classes, for the list view. */
export function rowsByDay(rows, monday) {
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i))
    .map((iso) => ({ iso, rows: rows.filter((row) => row.day === iso) }))
    .filter((day) => day.rows.length)
}
