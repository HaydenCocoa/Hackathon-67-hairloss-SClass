// HTTP calls for /admin/schedule. Uses the login session cookie (same origin).
// Scheduling errors arrive as { detail: { code, message, request_id } }; admin API errors as { detail: "text" }.
import { generateBody, saveBody } from './schedulePreview.js'

export class ScheduleApiError extends Error {
  constructor(message, { code = '', status = 0, requestId = '' } = {}) {
    super(message)
    this.code = code
    this.status = status
    this.requestId = requestId
  }
}

const LOGIN = `/login?next=${encodeURIComponent('/admin/schedule')}`

async function call(url, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(url, {
      method,
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    })
  } catch {
    throw new ScheduleApiError("Can't reach the server. Check that the backend is running, then try again.", { code: 'NETWORK' })
  }
  const requestId = response.headers?.get('X-Request-ID') || ''
  if (response.status === 401) {
    window.location.assign(LOGIN) // the session ended: log in again, then come back here
    throw new ScheduleApiError('Your session has ended. Log in again.', { code: 'AUTH_REQUIRED', status: 401, requestId })
  }
  let data = null
  try { data = await response.json() } catch { /* handled below */ }
  if (!response.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail) ? detail.map((item) => item.msg).join('; ')
      : typeof detail === 'string' ? detail
        : detail?.message || `The request failed (HTTP ${response.status}).`
    throw new ScheduleApiError(message, { code: detail?.code || '', status: response.status, requestId: requestId || detail?.request_id || '' })
  }
  if (data === null) throw new ScheduleApiError(`The server sent an unreadable reply (HTTP ${response.status}).`, { status: response.status, requestId })
  return { data, requestId }
}

export const listIntakes = async () => (await call('/api/admin/intakes')).data
export const listLecturers = async () => (await call('/api/admin/lecturers')).data

/** Can take up to about two minutes: the solver's time limit plus loading. */
export const generatePreview = (week, intakeIds) => call('/api/schedules/generate', { method: 'POST', body: generateBody(week, intakeIds) })

export const savePreview = (preview) => call('/api/schedules/save', { method: 'POST', body: saveBody(preview) })
