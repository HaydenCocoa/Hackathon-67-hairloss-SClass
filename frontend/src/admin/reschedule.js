// Pure helpers for the admin Reschedule dialog (no Vue, no fetch).
// API: GET /api/admin/timetable/{id}/availability and POST /api/admin/timetable/{id}/reschedule.
import { addDays, campusParts, formatMinutes, formatRange, mondayOf } from './roomCalendar.js'

const ACTIVE = new Set(['scheduled', 'rescheduled'])
const pad = (n) => String(n).padStart(2, '0')
export const hhmm = (minutes) => `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`
export const toMinutes = (text) => Number(text.slice(0, 2)) * 60 + Number(text.slice(3, 5))

/** Classes that can still be moved: active and not started yet, earliest first. */
export function reschedulable(sessions, now = new Date()) {
  return sessions
    .filter((s) => ACTIVE.has(s.status) && new Date(s.starts_at) > now)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.course_code.localeCompare(b.course_code))
}

const dayFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' })
const longFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
export const shortDay = (iso) => dayFormat.format(new Date(`${iso}T12:00:00Z`))
export const longDay = (iso) => longFormat.format(new Date(`${iso}T12:00:00Z`))

/** Campus date, start "HH:MM" and readable time range of a class. */
export function classTime(session) {
  const start = campusParts(session.starts_at)
  const end = campusParts(session.ends_at)
  return { date: start.date, start: hhmm(start.minutes), range: formatRange(start.minutes, end.date === start.date ? end.minutes : 1440) }
}

const typeName = (type) => (type ? type.charAt(0).toUpperCase() + type.slice(1) : '')

/** Drop-down label: "CT001 Lecture · Mon 16 Nov, 8:30 AM · A-01-01". */
export function classLabel(session) {
  const time = classTime(session)
  return `${session.course_code} ${typeName(session.course_type)} · ${shortDay(time.date)}, ${formatMinutes(toMinutes(time.start))} · ${session.room?.name || 'No room'}`
}

/** Monday to Friday of the week containing iso (classes are not taught at weekends). */
export function teachingDays(iso, today) {
  const monday = mondayOf(iso)
  return Array.from({ length: 5 }, (_, i) => {
    const day = addDays(monday, i)
    return { iso: day, label: shortDay(day), past: day < today }
  })
}

/** Why a start time cannot be chosen for the selected room, or '' when it can. */
export function slotBlock(slot, roomId, now = new Date()) {
  if (new Date(slot.starts_at) <= now) return 'This time has passed.'
  if (!slot.free_room_ids.length) return 'Not possible at this time: the lecturer or students are busy, or no suitable room is free.'
  if (roomId && !slot.free_room_ids.includes(roomId)) return 'The selected room is not free at this time. Choose another room to see its times.'
  return ''
}

const SHORT = {
  ROOM_CONFLICT: 'booked', ROOM_TOO_SMALL: 'too small', ROOM_TYPE_MISMATCH: 'wrong room type',
  ROOM_RESERVED_FOR_LARGE_CLASSES: 'kept for larger classes', ROOM_INACTIVE: 'out of use', ROOM_NOT_FOUND: 'missing',
  ROOM_POLICY_UNDEFINED: 'no room type allowed',
}
export const issueShort = (code) => SHORT[code] || 'not available'

/**
 * Whether a room can be picked, and the note shown after its name.
 * With a start time: free at that time. Without one: free at some time that day.
 */
export function roomChoice(room, { start, availability }) {
  if (!room.suitable) return { disabled: true, note: room.issues.map((i) => issueShort(i.code)).join(', ') }
  if (start && availability?.selected?.start === start) {
    const issues = availability.selected.room_issues[room.id]
    if (issues?.length) return { disabled: true, note: issues.map((i) => issueShort(i.code)).join(', ') }
    if (availability.selected.time_issues.length) return { disabled: true, note: 'time not possible' }
    return { disabled: false, note: 'free' }
  }
  const freeSomeTime = (availability?.slots || []).some((slot) => slot.free_room_ids.includes(room.id))
  return freeSomeTime ? { disabled: false, note: '' } : { disabled: true, note: 'not free this day' }
}

/** Has anything the person can change been changed? */
export const isDirty = (original, form) => Boolean(original) && (
  form.date !== original.date || form.start !== original.start || form.roomId !== original.roomId || form.reason.trim() !== ''
)

/** Has the class's time or room been changed (what Save needs)? */
export const isMoved = (original, form) => Boolean(original) && Boolean(form.start)
  && (form.date !== original.date || form.start !== original.start || form.roomId !== original.roomId)

/** Body for POST .../reschedule: times as campus-local ISO with +08:00 (Kuala Lumpur has no daylight saving). */
export function moveBody(session, form) {
  return {
    expected_starts_at: session.starts_at,
    expected_room_id: session.room_id,
    starts_at: `${form.date}T${form.start}:00+08:00`,
    room_id: form.roomId,
    // Optional: an empty reason is sent as null and recorded as "No reason given".
    reason: form.reason.trim() || null,
  }
}

/** Length of a class, such as "1h 30m" or "45 min". */
export function durationText(session) {
  const minutes = Math.round((new Date(session.ends_at) - new Date(session.starts_at)) / 60000)
  if (!(minutes > 0)) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h${m ? ` ${String(m).padStart(2, '0')}m` : ''}` : `${m} min`
}
