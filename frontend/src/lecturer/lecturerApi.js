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
    throw new ApiError('Please check the details and try again.')
  }
  return body
}

export const listLecturers = () => request('/api/lecturers')

export const listRooms = () => request('/api/rooms')

/** Classes of the courses this lecturer teaches. start/end are inclusive "YYYY-MM-DD" dates. */
export function getTimetable(lecturerId, { start, end } = {}) {
  const query = new URLSearchParams()
  if (start) query.set('start', start)
  if (end) query.set('end', end)
  const suffix = query.size ? `?${query}` : ''
  return request(`/api/lecturers/${encodeURIComponent(lecturerId)}/timetable${suffix}`)
}

/** body: { session_date, start_time, room_id, reason }. The end time is derived by the server. */
export const reschedule = (lecturerId, sessionId, body) =>
  request(`/api/lecturers/${encodeURIComponent(lecturerId)}/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
