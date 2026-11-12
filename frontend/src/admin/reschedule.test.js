// Run with: node --test frontend/src/admin/reschedule.test.js   (Node 20+, no packages needed)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  classLabel, classTime, durationText, hhmm, isDirty, isMoved, issueShort, moveBody, reschedulable, roomChoice, slotBlock, teachingDays,
  toMinutes,
} from './reschedule.js'

const at = (day, time) => new Date(`${day}T${time}:00+08:00`).toISOString()
const cls = (id, day, from, to, extra = {}) => ({
  id, status: 'scheduled', starts_at: at(day, from), ends_at: at(day, to), course_code: 'CT001', course_type: 'lecture',
  room_id: 'R1', room: { name: 'A-01', building: 'Block A' }, ...extra,
})
const NOW = new Date('2026-11-16T03:00:00Z') // Monday 16 Nov, 11:00 on campus

test('only active classes that have not started can be moved, earliest first', () => {
  const list = reschedulable([
    cls('later', '2026-11-18', '09:00', '10:00'),
    cls('started', '2026-11-16', '10:30', '12:00'),
    cls('cancelled', '2026-11-17', '09:00', '10:00', { status: 'cancelled' }),
    cls('moved', '2026-11-17', '09:00', '10:00', { status: 'rescheduled' }),
  ], NOW)
  assert.deepEqual(list.map((c) => c.id), ['moved', 'later'])
})

test('labels and campus times', () => {
  const c = cls('a', '2026-11-17', '08:30', '10:00')
  assert.deepEqual(classTime(c), { date: '2026-11-17', start: '08:30', range: '8:30 – 10:00 AM' })
  assert.equal(classLabel(c), 'CT001 Lecture · Tue 17 Nov, 8:30 AM · A-01')
  assert.equal(hhmm(615), '10:15')
  assert.equal(toMinutes('13:45'), 825)
  assert.deepEqual(teachingDays('2026-11-18', '2026-11-17').map((d) => [d.label, d.past]), [
    ['Mon 16 Nov', true], ['Tue 17 Nov', false], ['Wed 18 Nov', false], ['Thu 19 Nov', false], ['Fri 20 Nov', false],
  ])
})

test('a start time is blocked when it passed, nothing fits, or the selected room is busy', () => {
  const slot = (start, free) => ({ start, starts_at: at('2026-11-17', start), free_room_ids: free })
  assert.equal(slotBlock(slot('09:00', ['R1', 'R2']), 'R1', NOW), '')
  assert.match(slotBlock(slot('09:00', ['R2']), 'R1', NOW), /selected room is not free/)
  assert.match(slotBlock(slot('09:00', []), 'R1', NOW), /lecturer or students are busy/)
  assert.match(slotBlock({ ...slot('09:00', ['R1']), starts_at: at('2026-11-16', '09:00') }, 'R1', NOW), /passed/)
})

test('rooms are greyed out by suitability, the chosen time, or the whole day', () => {
  const availability = {
    slots: [{ start: '09:00', free_room_ids: ['R2'] }],
    selected: { start: '09:00', time_issues: [], available_room_ids: ['R2'], room_issues: { R1: [{ code: 'ROOM_CONFLICT' }] } },
  }
  const room = (id, extra = {}) => ({ id, suitable: true, issues: [], ...extra })
  assert.deepEqual(roomChoice(room('R1'), { start: '09:00', availability }), { disabled: true, note: 'booked' })
  assert.deepEqual(roomChoice(room('R2'), { start: '09:00', availability }), { disabled: false, note: 'free' })
  assert.deepEqual(roomChoice(room('LAB', { suitable: false, issues: [{ code: 'ROOM_TYPE_MISMATCH' }, { code: 'ROOM_TOO_SMALL' }] }),
    { start: '09:00', availability }), { disabled: true, note: 'wrong room type, too small' })
  // No time chosen: a room is offered if it is free at some time that day.
  assert.deepEqual(roomChoice(room('R1'), { start: '', availability }), { disabled: true, note: 'not free this day' })
  assert.deepEqual(roomChoice(room('R2'), { start: '', availability }), { disabled: false, note: '' })
  // A time with problems for every room (lecturer busy, ...).
  const busy = { ...availability, selected: { ...availability.selected, time_issues: [{ code: 'LECTURER_CONFLICT' }], available_room_ids: [] } }
  assert.deepEqual(roomChoice(room('R2'), { start: '09:00', availability: busy }), { disabled: true, note: 'time not possible' })
  assert.equal(issueShort('ROOM_RESERVED_FOR_LARGE_CLASSES'), 'kept for larger classes')
})

test('changes, saving and the request body', () => {
  const original = { date: '2026-11-17', start: '08:30', roomId: 'R1' }
  const form = { ...original, reason: '' }
  assert.ok(!isDirty(original, form) && !isMoved(original, form))
  assert.ok(isDirty(original, { ...form, reason: 'x' }) && !isMoved(original, { ...form, reason: 'x' }))
  assert.ok(isMoved(original, { ...form, roomId: 'R2' }))
  assert.ok(isDirty(original, { ...form, start: '' }) && !isMoved(original, { ...form, start: '' }))
  const c = cls('a', '2026-11-17', '08:30', '10:00')
  assert.deepEqual(moveBody(c, { date: '2026-11-18', start: '13:15', roomId: 'R2', reason: '  Clash  ' }), {
    expected_starts_at: c.starts_at, expected_room_id: 'R1', starts_at: '2026-11-18T13:15:00+08:00', room_id: 'R2', reason: 'Clash',
  })  // The reason is optional: blank becomes null (the API records "No reason given").
  assert.equal(moveBody(c, { date: '2026-11-18', start: '13:15', roomId: 'R2', reason: '   ' }).reason, null)
})

test('durationText reads the class length', () => {
  assert.equal(durationText(cls('a', '2026-11-17', '08:30', '10:00')), '1h 30m')
  assert.equal(durationText(cls('a', '2026-11-17', '08:30', '10:30')), '2h')
  assert.equal(durationText(cls('a', '2026-11-17', '08:30', '09:15')), '45 min')
})
