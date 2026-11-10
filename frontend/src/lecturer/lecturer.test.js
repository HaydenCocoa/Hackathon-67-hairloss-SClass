// Run with: node --test frontend/src/lecturer/lecturer.test.js   (Node 20+, no packages needed)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { ApiError, getTimetable, reschedule } from './lecturerApi.js'
import { groupText, roomsFor, toneOf, typeLabel } from './session.js'
import { addDays, endTime, formatTime, mondayOf, todayIso, weekDays, weekLabel } from './time.js'

test('todayIso uses Kuala Lumpur, not the browser time zone', () => {
  assert.equal(todayIso(new Date('2026-11-09T17:00:00Z')), '2026-11-10') // 01:00 on the 10th in KL
  assert.equal(todayIso(new Date('2026-11-09T15:59:00Z')), '2026-11-09')
})

test('addDays crosses month and year ends', () => {
  assert.equal(addDays('2026-11-30', 1), '2026-12-01')
  assert.equal(addDays('2026-12-31', 1), '2027-01-01')
  assert.equal(addDays('2026-03-01', -1), '2026-02-28')
})

test('mondayOf: weeks run Monday to Sunday', () => {
  assert.equal(mondayOf('2026-11-09'), '2026-11-09') // Monday
  assert.equal(mondayOf('2026-11-10'), '2026-11-09') // Tuesday
  assert.equal(mondayOf('2026-11-08'), '2026-11-02') // Sunday belongs to the week before
})

test('weekDays and weekLabel', () => {
  const days = weekDays('2026-11-09', '2026-11-10')
  assert.equal(days.length, 7)
  assert.deepEqual(days.map((d) => d.dow), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
  assert.deepEqual(days.filter((d) => d.isToday).map((d) => d.iso), ['2026-11-10'])
  assert.equal(weekLabel('2026-11-09'), '9 – 15 Nov 2026')
  assert.equal(weekLabel('2026-12-28'), '28 Dec – 3 Jan 2027')
})

test('formatTime', () => {
  assert.equal(formatTime('00:05'), '12:05 AM')
  assert.equal(formatTime('09:00'), '9:00 AM')
  assert.equal(formatTime('12:00'), '12:00 PM')
  assert.equal(formatTime('13:30'), '1:30 PM')
})

test('endTime is start plus the course duration', () => {
  assert.deepEqual(endTime('10:00', 90), { hhmm: '11:30', nextDay: false })
  assert.deepEqual(endTime('23:30', 60), { hhmm: '00:30', nextDay: true })
  assert.equal(endTime('', 60), null)
  assert.equal(endTime('9:00', 60), null)
})

test('session helpers', () => {
  assert.equal(typeLabel({ course_type: 'lab' }), 'Lab')
  assert.equal(groupText({ intake_code: 'I1', group_number: 2 }), 'I1 · Group 2')
  assert.equal(groupText({ intake_code: 'I2', group_number: null }), 'I2')
  assert.ok([0, 1, 2, 3].includes(toneOf('CS101')))
  assert.equal(toneOf('CS101'), toneOf('CS101'))
})

test('roomsFor keeps only rooms that fit the group and the required type', () => {
  const rooms = [
    { id: 'a', capacity: 100, room_type: 'auditorium' },
    { id: 'b', capacity: 20, room_type: 'auditorium' },
    { id: 'c', capacity: 40, room_type: 'lab' },
  ]
  assert.deepEqual(roomsFor({ student_count: 30, required_room_type: 'auditorium' }, rooms).map((r) => r.id), ['a'])
  assert.deepEqual(roomsFor({ student_count: 30, required_room_type: 'lab' }, rooms).map((r) => r.id), ['c'])
  assert.deepEqual(roomsFor({ student_count: 10, required_room_type: null }, rooms).map((r) => r.id), ['a', 'b', 'c'])
})

function fakeFetch(status, body, calls = []) {
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return { ok: status < 400, status, json: async () => body }
  }
  return calls
}

test('getTimetable builds the query string', async () => {
  const calls = fakeFetch(200, [])
  await getTimetable('abc', { start: '2026-11-09', end: '2026-11-15' })
  assert.equal(calls[0].url, '/api/lecturers/abc/timetable?start=2026-11-09&end=2026-11-15')
  await getTimetable('abc')
  assert.equal(calls[1].url, '/api/lecturers/abc/timetable')
})

test('reschedule sends a PATCH with a JSON body', async () => {
  const calls = fakeFetch(200, { id: 's1' })
  await reschedule('L1', 'S1', { session_date: '2026-11-12', start_time: '09:00', room_id: 'R1', reason: null })
  assert.equal(calls[0].url, '/api/lecturers/L1/sessions/S1')
  assert.equal(calls[0].options.method, 'PATCH')
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    session_date: '2026-11-12', start_time: '09:00', room_id: 'R1', reason: null,
  })
})

test('clash errors carry their conflict list', async () => {
  const conflicts = [{ type: 'room', message: 'Hall A is already booked.' }]
  fakeFetch(409, { detail: { message: 'That slot clashes with another booking.', conflicts } })
  await assert.rejects(reschedule('L1', 'S1', {}), (error) => {
    assert.ok(error instanceof ApiError)
    assert.equal(error.message, 'That slot clashes with another booking.')
    assert.deepEqual(error.conflicts, conflicts)
    return true
  })
})

test('validation errors (a list) and network failures give friendly messages', async () => {
  fakeFetch(422, { detail: [{ msg: 'field required' }] })
  await assert.rejects(reschedule('L1', 'S1', {}), { message: 'Please check the details and try again.' })
  globalThis.fetch = async () => { throw new TypeError('network down') }
  await assert.rejects(getTimetable('abc'), { message: /Can't reach the server/ })
})
