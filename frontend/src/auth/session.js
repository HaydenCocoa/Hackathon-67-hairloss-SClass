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

export async function logout() {
  try { await call('/api/auth/logout', { method: 'POST' }) } finally { session.value = null }
}
