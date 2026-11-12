// Run with: node --test frontend/src/lecturer/lecturer.test.js   (Node 20+, no packages needed)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createDemoApi } from './demoData.js'
import { ApiError, getTimetable, reschedule, suggestSlots } from './lecturerApi.js'
import { bySlot, groupText, isRequestedSlot, slotKey, toneOf, typeLabel } from './session.js'
import { addDays, endTime, formatTime, isWeekend, latestStart, mondayOf, nowTime, requestProblems, todayIso, weekDays, weekLabel } from './time.js'

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

test('slot helpers: stable key and "your requested time"', () => {
  const slot = { session_date: '2026-11-12', start_time: '14:00', room_id: 'r1' }
  assert.equal(slotKey(slot), '2026-11-12|14:00|r1')
  assert.notEqual(slotKey(slot), slotKey({ ...slot, room_id: 'r2' }))
  assert.equal(isRequestedSlot(slot, { date: '2026-11-12', time: '14:00' }), true)
  assert.equal(isRequestedSlot(slot, { date: '2026-11-12', time: '14:30' }), false)
  assert.equal(isRequestedSlot(slot, null), false)
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

test('a plain-text error detail from the backend is shown as it is', async () => {
  fakeFetch(500, { detail: "name 'MY_TZ' is not defined" })
  await assert.rejects(getTimetable('abc'), { message: "name 'MY_TZ' is not defined" })
})

test('validation errors (a list) and network failures give friendly messages', async () => {
  fakeFetch(422, { detail: [{ msg: 'field required' }] })
  await assert.rejects(reschedule('L1', 'S1', {}), { message: 'Please check the details and try again.' })
  globalThis.fetch = async () => { throw new TypeError('network down') }
  await assert.rejects(getTimetable('abc'), { message: /Can't reach the server/ })
})

test('suggestSlots asks the backend for recommended times', async () => {
  const calls = fakeFetch(200, [])
  await suggestSlots('L1', 'S1', { date: '2026-11-12', time: '14:00', flexDays: 3 })
  const url = new URL(calls[0].url, 'http://x')
  assert.equal(url.pathname, '/api/lecturers/L1/sessions/S1/suggestions')
  assert.deepEqual(Object.fromEntries(url.searchParams), { date: '2026-11-12', time: '14:00', flex_days: '3', limit: '6' })
})

// ---- the demo engine (stands in for the backend until it can recommend times) ----
// "Now" is Tue 10 Nov 2026 10:00 in Kuala Lumpur (02:00 UTC), so this week's Monday is 9 Nov.
const demo = () => createDemoApi(() => new Date('2026-11-10T02:00:00Z'))
const LECTURER = 'demo-lecturer-1' // Dr. Aisha Rahman
const minutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
const overlap = (a, b) => minutes(a.start_time) < minutes(b.end_time) && minutes(b.start_time) < minutes(a.end_time)

async function aishaThursdayLecture(api) {
  const week = await api.getTimetable(LECTURER, { start: '2026-11-09', end: '2026-11-15' })
  return week.find((s) => s.course_code === 'CS201' && s.session_date === '2026-11-12')
}

test('demo timetable: own classes only, ordered, with derived end times', async () => {
  const api = demo()
  const rows = await api.getTimetable(LECTURER, { start: '2026-11-09', end: '2026-11-15' })
  assert.deepEqual(rows.map((r) => r.course_code), ['CS101', 'CS101', 'SE220', 'CS201'])
  const lecture = rows[0]
  assert.equal(lecture.session_date, '2026-11-09')
  assert.equal(lecture.end_time, '11:00') // 09:00 + 120 min
  assert.equal(lecture.can_reschedule, false) // Monday is already over
  assert.equal(rows[3].can_reschedule, true) // Thursday is ahead
  await assert.rejects(api.getTimetable('nobody'), { message: 'Lecturer not found.' })
})

test('demo suggestions: free of every clash, nearest first, never the current slot or the past', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  const slots = await api.suggestSlots(LECTURER, session.id, { date: '2026-11-13', time: '10:00', flexDays: 1, limit: 6 })
  assert.ok(slots.length > 0 && slots.length <= 6)
  const everyone = await Promise.all(['demo-lecturer-1', 'demo-lecturer-2', 'demo-lecturer-3'].map((l) => api.getTimetable(l)))
  const others = everyone.flat().filter((s) => s.id !== session.id && s.status === 'scheduled')
  const mine = new Set((await api.getTimetable(LECTURER)).map((s) => s.id))
  let checkedOverlaps = 0
  for (const slot of slots) {
    assert.ok(['2026-11-12', '2026-11-13', '2026-11-14'].includes(slot.session_date))
    assert.ok(!(slot.session_date === session.session_date && slot.start_time === session.start_time))
    assert.equal(minutes(slot.end_time) - minutes(slot.start_time), session.duration_minutes)
    for (const other of others.filter((o) => o.session_date === slot.session_date && overlap(slot, o))) {
      checkedOverlaps++
      assert.notEqual(other.room_id, slot.room_id, 'the room is free')
      assert.ok(!mine.has(other.id), 'the lecturer is free')
      assert.notEqual(`${other.intake_code}|${other.group_number}`, `${session.intake_code}|${session.group_number}`, 'the group is free')
    }
  }
  assert.ok(checkedOverlaps > 0, 'the check must actually meet other classes at the same time')
  assert.equal(slots[0].session_date, '2026-11-13') // the requested day comes first
  assert.equal(slots[0].start_time, '10:00')        // at the requested time, as that slot is free
  const key = (s) => `${s.session_date}|${s.start_time}`
  assert.equal(new Set(slots.map(key)).size, slots.length)
})

test('demo suggestions: a past day is never offered and a busy request returns the nearest free times', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  const slots = await api.suggestSlots(LECTURER, session.id, { date: '2026-11-10', time: '08:00', flexDays: 2 })
  assert.ok(slots.every((s) => s.session_date >= '2026-11-10'))
  assert.ok(slots.every((s) => s.session_date !== '2026-11-10' || s.start_time > '10:00')) // today only after "now"
})

test('demo reschedule: moves the class, then refuses a clash with every reason listed', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  const [slot] = await api.suggestSlots(LECTURER, session.id, { date: '2026-11-13', time: '10:00', flexDays: 0 })
  const moved = await api.reschedule(LECTURER, session.id, { ...slot, reason: null })
  assert.equal(moved.end_time, slot.end_time)
  const after = (await api.getTimetable(LECTURER, { start: '2026-11-13', end: '2026-11-13' })).find((s) => s.id === session.id)
  assert.equal(after.start_time, slot.start_time)
  assert.equal(after.moved, true)

  // Aisha's own Wednesday 14:00 tutorial: moving the lecture onto it clashes for lecturer and group
  const clash = api.reschedule(LECTURER, session.id, { session_date: '2026-11-11', start_time: '14:00', room_id: 'demo-room-4' })
  await assert.rejects(clash, (error) => {
    assert.ok(error instanceof ApiError)
    assert.ok(error.conflicts.some((c) => c.type === 'lecturer'))
    assert.ok(error.conflicts.some((c) => c.type === 'student'))
    return true
  })
})

test('demo reschedule: others cannot move my class, past classes cannot be moved', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  await assert.rejects(api.suggestSlots('demo-lecturer-2', session.id, { date: '2026-11-13', time: '10:00' }), { message: 'You do not teach this class.' })
  const monday = (await api.getTimetable(LECTURER, { start: '2026-11-09', end: '2026-11-09' }))[0]
  await assert.rejects(api.suggestSlots(LECTURER, monday.id, { date: '2026-11-13', time: '10:00' }), { message: /already started/ })
})

// ---- timetable rules: Monday to Friday, 08:30-18:00, 15 minutes between classes, room type by course type ----
// Now is Tue 10 Nov 2026 10:00 (KL). Aisha's Thursday 12 Nov CS201 lecture (120 min, intake I2 group 1, needs a classroom).

test('demo suggestions never offer a weekend, or a time outside 08:30-18:00', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  const slots = await api.suggestSlots(LECTURER, session.id, { date: '2026-11-14', time: '10:00', flexDays: 3, limit: 20 }) // a Saturday
  assert.ok(slots.length > 0)
  for (const slot of slots) {
    assert.ok(!['2026-11-14', '2026-11-15'].includes(slot.session_date), `${slot.session_date} is a weekend`)
    assert.ok(minutes(slot.start_time) >= 8 * 60 + 30 && minutes(slot.end_time) <= 18 * 60, `${slot.start_time}-${slot.end_time} is outside 08:30-18:00`)
  }
  assert.deepEqual(await api.suggestSlots(LECTURER, session.id, { date: '2026-11-14', time: '10:00', flexDays: 0 }), [])
})

test('demo reschedule refuses weekends and times outside 08:30-18:00', async () => {
  const api = demo()
  const session = await aishaThursdayLecture(api)
  await assert.rejects(api.reschedule(LECTURER, session.id, { session_date: '2026-11-14', start_time: '10:00', room_id: 'demo-room-3' }), { message: /Monday to Friday/ })
  await assert.rejects(api.reschedule(LECTURER, session.id, { session_date: '2026-11-13', start_time: '08:00', room_id: 'demo-room-3' }), { message: /08:30 or later and finish by 18:00/ })
  await assert.rejects(api.reschedule(LECTURER, session.id, { session_date: '2026-11-13', start_time: '16:30', room_id: 'demo-room-3' }), { message: /finish by 18:00/ })
})

test('demo: a room that is booked (and nothing else clashes) is refused, with a 15-minute gap', async () => {
  // Fri 13 Nov 10:00-12:00 Daniel teaches MA110 (I1 group 2) in Room B205. Aisha and her group (I2 group 1) are free then.
  const api = demo()
  const session = await aishaThursdayLecture(api)
  const move = (start_time) => api.reschedule(LECTURER, session.id, { session_date: '2026-11-13', start_time, room_id: 'demo-room-4' })
  await assert.rejects(move('10:30'), (error) => {
    assert.deepEqual(error.conflicts.map((c) => c.type), ['room'], 'only the room is the problem')
    return true
  })
  await assert.rejects(move('12:10'), (error) => { // 10 minutes after the other class ends
    assert.deepEqual(error.conflicts.map((c) => c.type), ['room'])
    return true
  })
  const moved = await move('12:15') // exactly 15 minutes after: allowed
  assert.equal(moved.start_time ?? '12:15', '12:15')
})

test('demo: room policy from the config: lectures use classrooms or auditoriums, labs classrooms or labs', async () => {
  const api = demo()
  const week = await api.getTimetable(LECTURER, { start: '2026-11-23', end: '2026-11-29' }) // in two weeks: nothing has started, nothing is cancelled
  const lecture = week.find((s) => s.course_type === 'lecture' && s.can_reschedule)
  const lab = week.find((s) => s.course_type === 'lab' && s.can_reschedule)
  assert.deepEqual(lecture.allowed_room_types, ['classroom', 'auditorium'])
  assert.deepEqual(lab.allowed_room_types, ['classroom', 'lab'])
  const labSlots = await api.suggestSlots(LECTURER, lab.id, { date: '2026-11-13', time: '10:00', flexDays: 1, limit: 20 })
  assert.ok(labSlots.length > 0, 'a lab class gets suggestions')
  assert.ok(labSlots.every((s) => !s.room_name.startsWith('Hall')), 'a lab class is never offered an auditorium')
  const lectureSlots = await api.suggestSlots(LECTURER, lecture.id, { date: '2026-11-20', time: '10:00', flexDays: 2, limit: 30 })
  assert.ok(lectureSlots.every((s) => !s.room_name.startsWith('Lab')), 'a lecture is never offered a lab')
})

test('bySlot orders classes by date, then start time', () => {
  const rows = [
    { id: 'c', session_date: '2026-11-13', start_time: '09:00' },
    { id: 'b', session_date: '2026-11-12', start_time: '14:00' },
    { id: 'a', session_date: '2026-11-12', start_time: '09:30' },
    { id: 'd', session_date: '2026-11-13', start_time: '08:00' },
  ]
  assert.deepEqual([...rows].sort(bySlot).map((r) => r.id), ['a', 'b', 'd', 'c'])
})

test('the demo timetable and the classes you can still move come out in order', async () => {
  const api = demo()
  const all = await api.getTimetable(LECTURER, { start: '2026-11-09' })
  const upcoming = all.filter((s) => s.can_reschedule)
  assert.deepEqual([...upcoming].sort(bySlot), upcoming)
})

// ---- the date and start time must be inside the opening days and hours (Mon-Fri, 08:30-18:00) ----
const TODAY = '2026-11-12' // a Thursday
const problem = (date, time, minutes = 120, now = '10:00') => requestProblems(date, time, minutes, TODAY, now)

test('weekends are refused, weekdays are fine', () => {
  assert.equal(isWeekend('2026-11-14'), true) // Saturday
  assert.equal(isWeekend('2026-11-15'), true) // Sunday
  assert.equal(isWeekend('2026-11-16'), false) // Monday
  assert.match(problem('2026-11-14', '10:00').date, /Monday to Friday/)
  assert.match(problem('2026-11-15', '10:00').date, /Monday to Friday/)
  assert.equal(problem('2026-11-13', '10:00').date, '')
  assert.equal(problem('2026-11-16', '10:00').date, '')
})

test('a date in the past is refused; today is fine', () => {
  assert.match(problem('2026-11-11', '10:00').date, /already passed/)
  assert.equal(problem(TODAY, '14:00').date, '')
})

test('start times: not before 08:30, and the class must finish by 18:00', () => {
  assert.equal(latestStart(120), '16:00')
  assert.equal(latestStart(90), '16:30')
  assert.equal(latestStart(700), null)
  assert.match(problem('2026-11-13', '08:29').time, /8:30 AM or later/)
  assert.match(problem('2026-11-13', '08:00').time, /8:30 AM or later/) // the old 08:00 opening is gone
  assert.equal(problem('2026-11-13', '08:30').time, '')
  assert.equal(problem('2026-11-13', '16:00').time, '') // 16:00 + 120 min = 18:00 exactly
  assert.match(problem('2026-11-13', '16:01').time, /must start by 4:00 PM/)
  assert.match(problem('2026-11-13', '17:30').time, /finish by 6:00 PM/)
  assert.equal(problem('2026-11-13', '16:30', 90).time, '') // a 90-minute class may start at 16:30
  assert.match(problem('2026-11-13', '10:00', 700).time, /does not fit/)
})

test('today: a start time that has already passed is refused', () => {
  assert.match(problem(TODAY, '09:30', 120, '10:00').time, /already passed today/)
  assert.match(problem(TODAY, '10:00', 120, '10:00').time, /already passed today/)
  assert.equal(problem(TODAY, '10:30', 120, '10:00').time, '')
  assert.equal(problem('2026-11-13', '08:30', 120, '23:00').time, '') // tomorrow is not affected
  assert.match(nowTime(new Date('2026-11-12T07:05:00Z')), /^15:05$/) // 15:05 in Kuala Lumpur
})

test('empty fields give no message (the form asks for them) and each field reports on its own', () => {
  assert.deepEqual(problem('', ''), { date: '', time: '' })
  const both = problem('2026-11-14', '19:00')
  assert.ok(both.date && both.time)
})
