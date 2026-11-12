// Run with: node --test frontend/src/auth/auth.test.js   (Node 20+, uses the installed vue package)
import assert from 'node:assert/strict'
import { test } from 'node:test'

// router.js reads window at import time; give it a minimal browser-like window.
const listeners = {}
globalThis.window = {
  location: { pathname: '/student', search: '', hash: '' },
  history: {
    replaceState(_s, _t, url) { Object.assign(window.location, parse(url)) },
    pushState(_s, _t, url) { Object.assign(window.location, parse(url)) },
  },
  addEventListener(name, fn) { listeners[name] = fn },
}
function parse(url) {
  const u = new URL(url, 'http://127.0.0.1')
  return { pathname: u.pathname, search: u.search, hash: u.hash }
}

const { PASSWORD_PAGE, ROLE_PAGES, landingFor, legacyHashTarget, navigate, path, safeNext } = await import('../router.js')
const { AuthError, changePassword, loadSession, login, logout, passwordProblem, session } = await import('./session.js')

const student = { role: 'student', home: '/student', name: 'Sam', code: 'TP000001' }
const admin = { role: 'admin', home: '/admin', name: 'Ada' }

test('only same-site page paths are accepted as `next`', () => {
  for (const ok of ['/student', '/admin/development/scheduling-test-hayden', '/lecturer?week=2']) assert.equal(safeNext(ok), ok)
  for (const bad of [null, '', 'student', '//evil.example', 'https://evil.example', '/api/auth/me', '/login', '/\\evil', '/a\nb']) {
    assert.equal(safeNext(bad), null, String(bad))
  }
})

test('after login, `next` is followed only inside the user\'s own area', () => {
  assert.equal(landingFor(student, null), '/student')
  assert.equal(landingFor(student, '/admin'), '/student')
  assert.equal(landingFor(student, '//evil.example'), '/student')
  assert.equal(landingFor(admin, '/admin/development/scheduling-test-hayden'), '/admin/development/scheduling-test-hayden')
  assert.equal(landingFor(admin, '/administrator'), '/admin')  // prefix must be a path segment
  assert.equal(landingFor(admin, '/admin/schedule'), '/admin/schedule')
  assert.equal(landingFor(student, '/admin/schedule'), '/student')
})

test('old hash links map to the new pages', () => {
  assert.equal(legacyHashTarget('#/student'), '/student')
  assert.equal(legacyHashTarget('#/lecturer'), '/lecturer')
  assert.equal(legacyHashTarget('#main'), '/')
  assert.equal(legacyHashTarget('#/'), '/')
  assert.equal(legacyHashTarget('#section-2'), null)
  assert.deepEqual(ROLE_PAGES, { '/student': 'student', '/lecturer': 'lecturer', '/admin': 'admin', '/admin/schedule': 'admin' })
})

test('navigate updates the reactive path and back/forward is followed', () => {
  navigate('/login?next=%2Fstudent', { replace: true })
  assert.equal(path.value, '/login')
  window.location.pathname = '/admin'
  listeners.popstate()
  assert.equal(path.value, '/admin')
})

function fakeFetch(status, body) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return { status, ok: status >= 200 && status < 300, json: async () => body }
  }
  return calls
}

test('loadSession: logged in, logged out, and server errors', async () => {
  fakeFetch(200, student)
  assert.deepEqual(await loadSession(), student)
  assert.deepEqual(session.value, student)
  fakeFetch(401, { detail: { code: 'AUTH_REQUIRED' } })
  assert.equal(await loadSession(), null)
  assert.equal(session.value, null)
  fakeFetch(503, { detail: { code: 'AUTH_NOT_CONFIGURED', message: 'Login is unavailable.' } })
  await assert.rejects(loadSession(), (e) => e instanceof AuthError && e.code === 'AUTH_NOT_CONFIGURED')
})

test('login sends credentials once and shows the server message on failure', async () => {
  const calls = fakeFetch(200, admin)
  assert.deepEqual(await login('ada@example.test', 'pw'), admin)
  assert.equal(calls[0].url, '/api/auth/login')
  assert.equal(calls[0].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].options.body), { email: 'ada@example.test', password: 'pw' })
  fakeFetch(401, { detail: { code: 'INVALID_CREDENTIALS', message: 'Incorrect email or password.' } })
  await assert.rejects(login('ada@example.test', 'bad'), { message: 'Incorrect email or password.', code: 'INVALID_CREDENTIALS' })
  fakeFetch(422, { detail: [{ msg: 'Value error' }] })
  await assert.rejects(login('x', 'y'), { message: 'Enter a valid email address and your password.' })
  globalThis.fetch = async () => { throw new TypeError('network') }
  await assert.rejects(login('a@b.c', 'pw'), { code: 'NETWORK' })
})

test('a user with a temporary password lands only on the change-password page', () => {
  const flagged = { ...student, home: PASSWORD_PAGE, must_change_password: true }
  assert.equal(landingFor(flagged, null), '/change-password')
  assert.equal(landingFor(flagged, '/student'), '/change-password')
})

test('new password checks match the backend rules', () => {
  assert.equal(passwordProblem('', 'long-enough', 'long-enough'), 'Enter your current password.')
  assert.equal(passwordProblem('TP0000010042', 'short', 'short'), 'Use at least 8 characters.')
  assert.equal(passwordProblem('TP0000010042', 'x'.repeat(73), 'x'.repeat(73)), 'Use at most 72 characters.')
  assert.equal(passwordProblem('TP0000010042', 'é'.repeat(40), 'é'.repeat(40)), 'Use at most 72 characters.') // 80 bytes
  assert.equal(passwordProblem('same-password', 'same-password', 'same-password'), 'Choose a password different from your current one.')
  assert.equal(passwordProblem('TP0000010042', 'long-enough', 'long-enougH'), 'The new passwords do not match.')
  assert.equal(passwordProblem('TP0000010042', 'long-enough', 'long-enough'), '')
})

test('changePassword sends both passwords once and updates the session', async () => {
  const calls = fakeFetch(200, student)
  session.value = { ...student, home: PASSWORD_PAGE, must_change_password: true }
  assert.deepEqual(await changePassword('TP0000010042', 'long-enough'), student)
  assert.equal(calls[0].url, '/api/auth/change-password')
  assert.deepEqual(JSON.parse(calls[0].options.body), { current_password: 'TP0000010042', new_password: 'long-enough' })
  assert.deepEqual(session.value, student)
  fakeFetch(400, { detail: { code: 'WRONG_PASSWORD', message: 'Your current password is incorrect.' } })
  await assert.rejects(changePassword('bad', 'long-enough'), { code: 'WRONG_PASSWORD', message: 'Your current password is incorrect.' })
  fakeFetch(401, { detail: { code: 'AUTH_REQUIRED', message: 'Log in to continue.' } })
  await assert.rejects(changePassword('x', 'long-enough'), { code: 'AUTH_REQUIRED' })
})

test('logout clears the local session even if the server call fails', async () => {
  session.value = admin
  globalThis.fetch = async () => { throw new TypeError('network') }
  await assert.rejects(logout())
  assert.equal(session.value, null)
})
