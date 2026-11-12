// Small display and filtering helpers for class sessions returned by /api/lecturers/{id}/timetable.

/** A stable accent (0-3: blue, green, yellow, red) per course so the same course always looks the same. */
export const toneOf = (courseCode) => [...courseCode].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 4

export const typeLabel = (session) => session.course_type.charAt(0).toUpperCase() + session.course_type.slice(1)

/** "I1 · Group 2"; the group is omitted when the intake has a single group (the API sends null). */
export const groupText = (session) =>
  session.group_number ? `${session.intake_code} · Group ${session.group_number}` : session.intake_code

/** Sort order for classes: earliest date first, then earliest start time. Use as rows.sort(bySlot). */
export const bySlot = (a, b) =>
  a.session_date.localeCompare(b.session_date) || a.start_time.localeCompare(b.start_time)

/** One stable key per recommended slot (the same start time can be offered in different rooms). */
export const slotKey = (slot) => `${slot.session_date}|${slot.start_time}|${slot.room_id}`

/** True when a recommended slot is exactly the date and start time the lecturer asked for. */
export const isRequestedSlot = (slot, request) =>
  !!request && slot.session_date === request.date && slot.start_time === request.time
