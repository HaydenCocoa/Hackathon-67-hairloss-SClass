// Admin page requests. The login cookie authorizes them (no token in the browser);
// an expired login sends the admin back to /login and returns here afterwards.
import { navigate } from '../router'

export async function adminRequest(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  let result = null
  try { result = await response.json() } catch { /* handled below */ }
  if (response.status === 401) {
    navigate(`/login?next=${encodeURIComponent('/admin')}`, { replace: true })
    throw new Error('Your login has expired. Please log in again.')
  }
  if (!response.ok) {
    const detail = result?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'Request failed.')
  }
  return result
}
