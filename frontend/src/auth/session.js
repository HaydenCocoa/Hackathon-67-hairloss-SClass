// Login state. The session itself is an httpOnly cookie set by the backend;
// the browser only keeps who is logged in (name, role, home page).
import { ref } from 'vue'

export const session = ref(null)

export class AuthError extends Error {
  constructor(message, code = '') {
    super(message)
    this.code = code
  }
}

async function call(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(15000),
      ...options,
    })
  } catch {
    throw new AuthError('Cannot reach the server. Make sure the backend is running and try again.', 'NETWORK')
  }
  let body = null
  try { body = await response.json() } catch { /* empty or non-JSON body */ }
  return { response, body }
}

/** Load the current user; null when not logged in. */
export async function loadSession() {
  const { response, body } = await call('/api/auth/me')
  if (response.status === 401) {
    session.value = null
    return null
  }
  if (!response.ok) throw new AuthError(body?.detail?.message || 'Could not check your login. Try again.', body?.detail?.code)
  session.value = body
  return body
}

export async function login(email, password) {
  const { response, body } = await call('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
  if (!response.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail) ? 'Enter a valid email address and your password.'
      : detail?.message || 'Login failed. Try again.'
    throw new AuthError(message, detail?.code)
  }
  session.value = body
  return body
}

// Same limits as the backend (bcrypt in Supabase Auth uses at most 72 bytes).
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 72

/** First problem with a new password, or '' when it can be sent. */
export function passwordProblem(current, next, confirm) {
  if (!current) return 'Enter your current password.'
  if (next.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  if (new TextEncoder().encode(next).length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters.`
  if (next === current) return 'Choose a password different from your current one.'
  if (next !== confirm) return 'The new passwords do not match.'
  return ''
}

/** Replace the password; the backend renews the session and returns the updated user. */
export async function changePassword(current, next) {
  const { response, body } = await call('/api/auth/change-password', {
    method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }),
  })
  if (!response.ok) {
    const detail = body?.detail
    const message = Array.isArray(detail) ? `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`
      : detail?.message || 'Could not change the password. Try again.'
    throw new AuthError(message, response.status === 401 ? 'AUTH_REQUIRED' : detail?.code)
  }
  session.value = body
  return body
}

export async function logout() {
  try { await call('/api/auth/logout', { method: 'POST' }) } finally { session.value = null }
}
