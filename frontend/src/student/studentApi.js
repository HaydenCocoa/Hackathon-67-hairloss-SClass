// HTTP client for the Student Page. Relative URLs go through Vite's proxy in dev.

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
  // 0 = network error; 5xx from the Vite proxy/FastAPI means the backend or Supabase is unavailable.
  get backendUnavailable() {
    return this.status === 0 || this.status >= 500
  }
}

export async function fetchTimetable(studentCode, start, end) {
  const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })
  let response
  try {
    response = await fetch(`/api/student/${encodeURIComponent(studentCode)}/timetable?${params}`, {
      credentials: 'same-origin', // send the login cookie
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(15000),
    })
  } catch {
    throw new ApiError('Cannot reach the backend. Make sure FastAPI is running on port 8000.', 0)
  }
  let body = null
  try {
    body = await response.json()
  } catch {
    // Vite returns an empty 500 when FastAPI is not running.
  }
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message || null
    const fallback = response.status >= 500
      ? 'The backend is not available right now.'
      : 'The timetable could not be loaded.'
    throw new ApiError(detail || fallback, response.status)
  }
  return body
}
