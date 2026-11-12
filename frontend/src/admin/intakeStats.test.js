import assert from 'node:assert/strict'
import test from 'node:test'
import { intakeFacts, intakeTotals } from './intakeStats.js'

const a = { id: 'a', intake_code: 'A', max_group: 3, course_offerings: [{ id: 1 }, { id: 2 }],
  student_intakes: [{ student_id: 's1', group_number: 1 }, { student_id: 's2', group_number: 1 }, { student_id: 's3', group_number: 3 }] }
const b = { id: 'b', intake_code: 'B', max_group: 1, student_intakes: [{ student_id: 's1', group_number: 1 }] }

test('intake facts count students per group, including empty groups', () => {
  assert.deepEqual(intakeFacts(a), { students: 3, groups: 3, groupsInUse: 2, courses: 2, perGroup: [2, 0, 1] })
  assert.deepEqual(intakeFacts({ max_group: 2 }), { students: 0, groups: 2, groupsInUse: 0, courses: 0, perGroup: [0, 0] })
})

test('totals count a student in two intakes once and average over groups with students', () => {
  assert.deepEqual(intakeTotals([a, b]), { intakes: 2, students: 3, groups: 4, perGroup: 1 })
  assert.deepEqual(intakeTotals([]), { intakes: 0, students: 0, groups: 0, perGroup: 0 })
})
