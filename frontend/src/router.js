// Minimal path router (no extra dependency): /login, /student, /lecturer, /admin.
import { ref } from 'vue'

export const ROLE_PAGES = { '/student': 'student', '/lecturer': 'lecturer', '/admin': 'admin' }

export const path = ref(window.location.pathname)

export function navigate(to, { replace = false } = {}) {
  window.history[replace ? 'replaceState' : 'pushState']({}, '', to)
  path.value = window.location.pathname
}

window.addEventListener('popstate', () => { path.value = window.location.pathname })

// Old links used #/student, #/lecturer and #main; send them to the new paths.
export function legacyHashTarget(hash) {
  if (hash.startsWith('#/student')) return '/student'
  if (hash.startsWith('#/lecturer')) return '/lecturer'
  if (hash.startsWith('#/admin')) return '/admin'
  if (hash === '#/' || hash === '#main') return '/'
  return null
}

// Same rules as the backend: only same-site page paths, never /api or /login.
export function safeNext(value) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null
  if (value.startsWith('/api/') || value.startsWith('/login') || /[\u0000-\u001f]/.test(value)) return null
  return value
}

// After login, follow `next` only into the user's own area.
export function landingFor(user, next) {
  const target = safeNext(next)
  return target && (target === user.home || target.startsWith(`${user.home}/`)) ? target : user.home
}
