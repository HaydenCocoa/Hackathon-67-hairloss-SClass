// Run with: node --test frontend/src/admin/schedulePreview.test.js   (Node 20+, no packages needed)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  errorAdvice, filterChoices, generateBody, groupChoices, keepsPreview, matchesFilter, matchesGroup, newRunId, outcome, placementRows,
  rowsByDay, saveBody,
  selectionKey, summaryCards, weekTitle,
} from './schedulePreview.js'

const at = (day, hhmm) => new Date(`${day}T${hhmm}:00+08:00`).toISOString()
const placement = (n, day, from, to, extra = {}) => ({
  occurrence_id: `o${n}`, section_id: `s${n}`, lecturer_id: 'L1', room_id: 'R1', room_name: 'A-01', room_building: 'Block A',
  starts_at: at(day, from), ends_at: at(day, to), student_count: 30, course_code: `CT00${n}`, course_name: 'Course',
  course_type: 'lecture', intake_id: 'I1', group_number: 1, ...extra,
})
const preview = (extra = {}) => ({
  status: 'OPTIMAL', has_solution: true, week_start: '2026-11-16', snapshot_revision: 'f'.repeat(64), required_count: 2,
  intake_ids: ['I1', 'I2'], placements: [
    placement(2, '2026-11-17', '09:00', '10:30', { intake_id: 'I2', room_id: 'R2', room_name: 'LAB-2', lecturer_id: 'L2' }),
    placement(1, '2026-11-16', '08:30', '10:30'),
  ],
  unplaced: [], diagnostics: [], quality_optimized: true, statistics: { elapsed_seconds: 41.6 },
  quality: {
    student_idle_minutes_average: 12.5, student_idle_minutes_max: 45, lecturer_idle_minutes_total: 30, lecturer_idle_minutes_max: 30,
    seat_use_percent: 75, empty_seats_total: 20, longest_student_day_minutes: 330,
  },
  ...extra,
})

test('request bodies: several intakes, sorted and without repeats; save sends the preview unchanged', () => {
  assert.deepEqual(generateBody('2026-11-16', ['b', 'a', 'b']), { week_start: '2026-11-16', intake_ids: ['a', 'b'] })
  assert.equal(selectionKey('2026-11-16', ['b', 'a']), selectionKey('2026-11-16', ['a', 'b', 'a']))
  assert.notEqual(selectionKey('2026-11-16', ['a']), selectionKey('2026-11-23', ['a']))
  const body = saveBody(preview())
  assert.deepEqual(Object.keys(body), ['week_start', 'intake_ids', 'snapshot_revision', 'placements'])
  assert.deepEqual(body.placements[0], { occurrence_id: 'o2', room_id: 'R2', starts_at: at('2026-11-17', '09:00') })
})

test('outcomes are explained in plain language', () => {
  assert.deepEqual([outcome(preview()).tone, outcome(preview()).title], ['success', '2 classes ready to schedule'])
  assert.equal(outcome(preview({ has_solution: false, status: 'NO_PENDING_REQUIREMENTS', placements: [] })).title, 'Nothing to schedule')
  const blocked = outcome(preview({ has_solution: false, status: 'INFEASIBLE', placements: [], unplaced: [{}, {}] }))
  assert.equal(blocked.tone, 'error')
  assert.match(blocked.text, /^2 classes cannot be placed/)
  assert.match(outcome(preview({ has_solution: false, status: 'INFEASIBLE', placements: [] })).text, /Try fewer intakes/)
  assert.equal(outcome(preview({ has_solution: false, status: 'UNKNOWN', placements: [] })).tone, 'warning')
})

test('error advice, and which errors keep the preview', () => {
  assert.match(errorAdvice('PREVIEW_STALE'), /Regenerate/)
  assert.match(errorAdvice('ORIGIN_NOT_ALLOWED'), /own address/)
  assert.equal(errorAdvice('LOCAL_ACCESS_ONLY'), '')  // the API is no longer local-only
  assert.equal(errorAdvice('SOMETHING_NEW'), '')
  assert.ok(keepsPreview('GENERATION_BUSY') && keepsPreview('NETWORK'))
  assert.ok(!keepsPreview('PREVIEW_STALE') && !keepsPreview('SAVE_OUTCOME_UNKNOWN'))
})

test('summary cards', () => {
  const cards = Object.fromEntries(summaryCards(preview()).map((card) => [card.label, card.value]))
  assert.deepEqual(cards, {
    Classes: '2 / 2', Intakes: '2', 'Rooms used': '2', 'Student waiting': '12.5 min', 'Lecturer gaps': '30 min',
    'Seat use': '75%', 'Longest student day': '5h 30m', 'Search time': '42 s',
  })
  assert.equal(summaryCards(preview({ quality: null })).length, 4)
})

test('rows are sorted, labelled in campus time, filtered and grouped by day', () => {
  const names = { intakes: new Map([['I1', 'APU1F2611CS'], ['I2', 'APD1F2611CS']]), lecturers: new Map([['L1', 'Dr. Aisha']]) }
  const rows = placementRows(preview(), names)
  assert.deepEqual(rows.map((r) => [r.course_code, r.day, r.time, r.intake_code, r.lecturer_name]), [
    ['CT001', '2026-11-16', '8:30 – 10:30 AM', 'APU1F2611CS', 'Dr. Aisha'],
    ['CT002', '2026-11-17', '9:00 – 10:30 AM', 'APD1F2611CS', 'Unknown lecturer'],
  ])
  assert.deepEqual(filterChoices(rows, 'intake'), [
    { value: 'I2', label: 'APD1F2611CS', count: 1 }, { value: 'I1', label: 'APU1F2611CS', count: 1 },
  ])
  assert.deepEqual(filterChoices(rows, 'room').map((c) => c.label), ['A-01 · Block A', 'LAB-2 · Block A'])
  assert.deepEqual(rows.filter((r) => matchesFilter(r, 'room', 'R2')).map((r) => r.course_code), ['CT002'])
  assert.equal(rows.filter((r) => matchesFilter(r, 'lecturer', 'all')).length, 2)
  assert.deepEqual(rowsByDay(rows, '2026-11-16').map((d) => [d.iso, d.rows.length]), [['2026-11-16', 1], ['2026-11-17', 1]])
  assert.equal(weekTitle('2026-11-16'), 'Week of 16 – 22 Nov 2026')
})

test('an intake can be narrowed to one of its groups', () => {
  const rows = placementRows(preview({ placements: [
    placement(1, '2026-11-16', '08:30', '10:30', { group_number: 2 }),
    placement(2, '2026-11-16', '11:00', '12:00', { group_number: 1 }),
    placement(3, '2026-11-17', '09:00', '10:00', { group_number: 2 }),
    placement(4, '2026-11-17', '13:00', '14:00', { group_number: 10 }),
    placement(5, '2026-11-18', '09:00', '10:00', { intake_id: 'I2', group_number: 3 }),
  ] }))
  // Only the chosen intake's groups, in number order (10 after 2), with their class counts.
  assert.deepEqual(groupChoices(rows, 'I1'), [
    { value: '1', label: 'Group 1', count: 1 }, { value: '2', label: 'Group 2', count: 2 }, { value: '10', label: 'Group 10', count: 1 },
  ])
  assert.deepEqual(groupChoices(rows, 'I2').map((g) => g.label), ['Group 3'])
  assert.deepEqual(groupChoices(rows, 'all'), []) // no group choice until an intake is chosen
  const shown = (intake, group) => rows.filter((r) => matchesFilter(r, 'intake', intake) && matchesGroup(r, group)).map((r) => r.course_code)
  assert.deepEqual(shown('I1', '2'), ['CT001', 'CT003'])
  assert.deepEqual(shown('I1', 'all'), ['CT001', 'CT002', 'CT003', 'CT004'])
  assert.deepEqual(shown('I2', 'all'), ['CT005'])
})

// ---------- scheduleApi.js against a fake fetch ----------
globalThis.window = { location: { pathname: '/admin/schedule', assign(url) { window.location.assigned = url } } }
const { PAUSED, ScheduleApiError, generatePreview, listIntakes, savePreview, stopPreview } = await import('./scheduleApi.js')

function fakeFetch(status, body, headers = {}) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return {
      status, ok: status >= 200 && status < 300,
      headers: { get: (name) => headers[name] || null },
      json: async () => { if (body === undefined) throw new Error('no json'); return body },
    }
  }
  return calls
}

test('generate posts the selection and returns the request ID', async () => {
  const calls = fakeFetch(200, preview(), { 'X-Request-ID': 'req-1' })
  const { data, requestId } = await generatePreview('2026-11-16', ['I2', 'I1'])
  assert.equal(calls[0].url, '/api/schedules/generate')
  assert.equal(calls[0].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].options.body), { week_start: '2026-11-16', intake_ids: ['I1', 'I2'] })
  assert.equal(data.status, 'OPTIMAL')
  assert.equal(requestId, 'req-1')
})

test('scheduling errors keep their code and request ID; admin API string errors are shown as they are', async () => {
  fakeFetch(409, { detail: { code: 'PREVIEW_STALE', message: 'Changed.', request_id: 'req-2' } })
  await assert.rejects(savePreview(preview()), (e) => e instanceof ScheduleApiError && e.code === 'PREVIEW_STALE'
    && e.message === 'Changed.' && e.requestId === 'req-2' && e.status === 409)
  fakeFetch(403, { detail: 'Administrator access required.' })
  await assert.rejects(listIntakes(), (e) => e.message === 'Administrator access required.' && e.code === '')
  fakeFetch(422, { detail: [{ msg: 'Value error, Give either intake_id or intake_ids' }] })
  await assert.rejects(generatePreview('2026-11-16', []), /Give either intake_id or intake_ids/)
  fakeFetch(502, undefined)
  await assert.rejects(listIntakes(), /The request failed \(HTTP 502\)/)
  fakeFetch(504, undefined)  // Vercel's own timeout page
  await assert.rejects(generatePreview('2026-11-16', ['I1']), (e) => e.code === 'SERVER_TIMEOUT' && e.status === 504)
  fakeFetch(200, undefined)
  await assert.rejects(listIntakes(), /unreadable reply \(HTTP 200\)/)
  globalThis.fetch = async () => { throw new TypeError('offline') }
  await assert.rejects(listIntakes(), (e) => e.code === 'NETWORK')
})

test('an ended session sends the person to log in and back to this page', async () => {
  fakeFetch(401, { detail: 'Admin sign-in required.' })
  await assert.rejects(listIntakes(), (e) => e.code === 'AUTH_REQUIRED')
  assert.equal(window.location.assigned, '/login?next=%2Fadmin%2Fschedule')
})

// ---------- Pause ----------
test('a paused preview is explained, with or without a timetable', () => {
  const kept = outcome(preview({ stopped: true, status: 'FEASIBLE' }))
  assert.equal(kept.tone, 'warning')
  assert.match(kept.title, /^Paused: 2 classes placed/)
  assert.match(kept.text, /You can schedule this timetable/)
  const none = outcome(preview({ stopped: true, has_solution: false, status: 'UNKNOWN', placements: [] }))
  assert.deepEqual([none.tone, none.title], ['neutral', 'Scheduling paused'])
  assert.match(none.text, /Nothing was saved/)
})

test('each Generate press gets its own run id, sent with the request', () => {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
  assert.match(newRunId(), uuid)
  // Without crypto.randomUUID (an older browser or plain-HTTP page) it is built from random bytes.
  const fallback = newRunId({ getRandomValues: (bytes) => bytes.fill(255) })
  assert.match(fallback, uuid)
  assert.notEqual(newRunId(), newRunId())
  assert.deepEqual(generateBody('2026-11-16', ['b', 'a'], 'run-1'), { week_start: '2026-11-16', intake_ids: ['a', 'b'], run_id: 'run-1' })
})

test('Pause asks the server to stop that run; aborting the wait is reported as paused', async () => {
  const calls = fakeFetch(200, { stopped: true })
  const { data } = await stopPreview('run-1')
  assert.equal(calls[0].url, '/api/schedules/generate/stop')
  assert.equal(calls[0].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].options.body), { run_id: 'run-1' })
  assert.equal(data.stopped, true)

  const seen = fakeFetch(200, preview())
  const controller = new AbortController()
  await generatePreview('2026-11-16', ['I1'], { runId: 'run-2', signal: controller.signal })
  assert.equal(JSON.parse(seen[0].options.body).run_id, 'run-2')
  assert.equal(seen[0].options.signal, controller.signal)

  globalThis.fetch = async (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
  })
  const waiting = generatePreview('2026-11-16', ['I1'], { runId: 'run-3', signal: controller.signal })
  controller.abort()
  await assert.rejects(waiting, (e) => e instanceof ScheduleApiError && e.code === PAUSED && /paused/.test(e.message))
})
