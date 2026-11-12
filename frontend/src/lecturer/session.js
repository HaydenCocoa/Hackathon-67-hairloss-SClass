// Small display and filtering helpers for class sessions returned by /api/lecturers/{id}/timetable.

/** A stable accent (0-3: blue, green, yellow, red) per course so the same course always looks the same. */
export const toneOf = (courseCode) => [...courseCode].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 4

export const typeLabel = (session) => session.course_type.charAt(0).toUpperCase() + session.course_type.slice(1)

/** "I1 · Group 2"; the group is omitted when the intake has a single group (the API sends null). */
export const groupText = (session) =>
  session.group_number ? `${session.intake_code} · Group ${session.group_number}` : session.intake_code

/**
 * Rooms that could host the session: seats the whole group and has the required type.
 * The server makes the final decision; this only keeps obviously unsuitable rooms out of the list.
 */
export const roomsFor = (session, rooms) =>
  rooms.filter(
    (room) =>
      room.capacity >= session.student_count &&
      (!session.required_room_type || room.room_type === session.required_room_type),
  )
