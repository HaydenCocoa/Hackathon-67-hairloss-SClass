// Run with: node --test frontend/src/admin/roomCalendar.test.js   (Node 20+, no packages needed)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  addDays, campusParts, eventLines, formatMinutes, formatRange, hourLabel, layoutWeek, mondayOf, roomLabel, sortRooms, todayIso, toneOf,
  weekDays, weekLabel, weekRange,
} from './roomCalendar.js'

test('weeks run Monday to Sunday and cross month/year boundaries', () => {
  assert.equal(mondayOf('2026-11-12'), '2026-11-09') // Thursday
  assert.equal(mondayOf('2026-11-09'), '2026-11-09') // Monday
  assert.equal(mondayOf('2026-11-15'), '2026-11-09') // Sunday belongs to the week before
  assert.equal(addDays('2026-12-28', 7), '2027-01-04')
  assert.equal(weekLabel('2026-11-16'), '16 – 22 Nov 2026')
  assert.equal(weekLabel('2026-11-30'), '30 Nov – 6 Dec 2026')
  assert.equal(weekLabel('2026-12-28'), '28 Dec 2026 – 3 Jan 2027')
})

test('Saturday and Sunday are the weekend; today is marked', () => {
  const days = weekDays('2026-11-09', '2026-11-12')
  assert.deepEqual(days.map((d) => d.dow), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
  assert.deepEqual(days.map((d) => d.weekend), [false, false, false, false, false, true, true])
  assert.deepEqual(days.filter((d) => d.isToday).map((d) => d.iso), ['2026-11-12'])
})

test('campus dates and times use Asia/Kuala_Lumpur whatever the browser zone is', () => {
  assert.equal(todayIso(new Date('2026-11-15T17:30:00Z')), '2026-11-16') // already Monday on campus
  assert.deepEqual(campusParts('2026-11-16T01:00:00Z'), { date: '2026-11-16', minutes: 9 * 60 })
  assert.deepEqual(campusParts('2026-11-15T16:30:00+00:00'), { date: '2026-11-16', minutes: 30 })
  assert.deepEqual(weekRange('2026-11-16'), { start: '2026-11-16T00:00:00+08:00', end: '2026-11-23T00:00:00+08:00' })
})

test('labels and colours', () => {
  assert.equal(formatMinutes(9 * 60), '9:00 AM')
  assert.equal(formatMinutes(13 * 60 + 5), '1:05 PM')
  assert.equal(formatMinutes(0), '12:00 AM')
  assert.equal(hourLabel(12), '12 PM')
  assert.equal(formatRange(510, 630), '8:30 – 10:30 AM')
  assert.equal(formatRange(690, 765), '11:30 AM – 12:45 PM')
  assert.deepEqual([45, 60, 89, 90].map(eventLines), [2, 3, 3, 4])
  assert.deepEqual(['lecture', 'tutorial', 'lab', 'others'].map(toneOf), ['blue', 'green', 'yellow', 'red'])
  assert.equal(roomLabel({ name: 'A101', building: 'A', room_type: 'classroom', capacity: 40 }), 'A101 · A · classroom · 40 seats')
  assert.deepEqual(sortRooms([{ name: 'B10' }, { name: 'B2' }, { name: 'A1' }]).map((r) => r.name), ['A1', 'B2', 'B10'])
})

const at = (day, hhmm) => new Date(`${day}T${hhmm}:00+08:00`).toISOString()
const session = (id, room, day, from, to, extra = {}) => ({ id, room_id: room, starts_at: at(day, from), ends_at: at(day, to), ...extra })

test('only the selected room and week are laid out, by campus day', () => {
  const rows = [
    session('a', 'r1', '2026-11-16', '09:00', '10:30'),
    session('b', 'r2', '2026-11-16', '09:00', '10:00'), // other room
    session('c', 'r1', '2026-11-23', '09:00', '10:00'), // next week
    session('d', 'r1', '2026-11-20', '14:00', '16:00'),
  ]
  const { days, firstHour, lastHour } = layoutWeek(rows, 'r1', '2026-11-16')
  assert.deepEqual(days['2026-11-16'].map((e) => [e.id, e.startMinutes, e.endMinutes]), [['a', 540, 630]])
  assert.deepEqual(days['2026-11-20'].map((e) => e.id), ['d'])
  assert.equal(Object.values(days).flat().length, 2)
  assert.deepEqual([firstHour, lastHour], [8, 19]) // opening hours 08:30–18:00 fit the default range
  assert.equal(Object.values(layoutWeek(rows, '', '2026-11-16').days).flat().length, 0) // no room chosen
})

test('the hour range grows to show bookings outside the usual day', () => {
  const rows = [session('early', 'r1', '2026-11-17', '07:15', '08:00'), session('late', 'r1', '2026-11-18', '18:30', '20:10')]
  const { firstHour, lastHour } = layoutWeek(rows, 'r1', '2026-11-16')
  assert.deepEqual([firstHour, lastHour], [7, 21])
})

test('overlapping classes share the column side by side; back-to-back ones do not', () => {
  const rows = [
    session('a', 'r1', '2026-11-16', '09:00', '11:00'),
    session('b', 'r1', '2026-11-16', '10:00', '11:00', { status: 'cancelled' }),
    session('c', 'r1', '2026-11-16', '11:00', '12:00'),
    session('d', 'r1', '2026-11-16', '10:30', '11:30'),
  ]
  const events = Object.fromEntries(layoutWeek(rows, 'r1', '2026-11-16').days['2026-11-16'].map((e) => [e.id, e]))
  assert.deepEqual([events.a.lane, events.b.lane, events.d.lane], [0, 1, 2])
  assert.equal(events.c.lane, 0) // a and b ended at 11:00 (d still runs): c takes the first free lane
  assert.ok(['a', 'b', 'c', 'd'].every((id) => events[id].lanes === 3))
})
