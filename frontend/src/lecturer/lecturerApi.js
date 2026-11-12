// Calls to the Lecturer endpoints of the FastAPI backend (backend/app/lecturer/api.py).

export class ApiError extends Error {
  constructor(message, conflicts = []) {
    super(message)
    this.conflicts = conflicts // [{ type: 'room' | 'lecturer' | 'student', message }]
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.")
  }
  let body = null
  try {
    body = await response.json()
  } catch {
    // Non-JSON error body: fall through to the generic message below.
  }
  if (!response.ok) {
    const detail = body?.detail
    // The backend sends { detail: { message, conflicts } }; FastAPI validation errors send a list.
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      throw new ApiError(detail.message, detail.conflicts || [])
    }
    // A plain-text detail (for example from HTTPException(500, "...")) is shown as it is, so the cause is visible.
    if (typeof detail === 'string' && detail) throw new ApiError(detail)
    throw new ApiError('Please check the details and try again.')
  }
  return body
}

export const listLecturers = () => request('/api/lecturers')

/** Classes of the courses this lecturer teaches. start/end are inclusive "YYYY-MM-DD" dates. */
export function getTimetable(lecturerId, { start, end } = {}) {
  const query = new URLSearchParams()
  if (start) query.set('start', start)
  if (end) query.set('end', end)
  const suffix = query.size ? `?${query}` : ''
  return request(`/api/lecturers/${encodeURIComponent(lecturerId)}/timetable${suffix}`)
}

/**
 * Free time slots near what the lecturer asked for, best first (the backend works them out from the
 * timetable: no room, lecturer or student clash; room of the right type and size). Not built yet.
 *   request:  { date: 'YYYY-MM-DD', time: 'HH:MM', flexDays: 0-7, limit }
 *   response: [{ session_date, start_time, end_time, room_id, room_name, building, capacity }]
 */
export function suggestSlots(lecturerId, sessionId, { date, time, flexDays = 1, limit = 6 }) {
  const query = new URLSearchParams({ date, time, flex_days: String(flexDays), limit: String(limit) })
  return request(
    `/api/lecturers/${encodeURIComponent(lecturerId)}/sessions/${encodeURIComponent(sessionId)}/suggestions?${query}`,
  )
}

/** body: { session_date, start_time, room_id, reason }. The end time is derived by the server. */
export const reschedule = (lecturerId, sessionId, body) =>
  request(`/api/lecturers/${encodeURIComponent(lecturerId)}/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
