// Sample timetable in the same shape as GET /api/student/{code}/timetable.
// Used for demos when the backend or class data is not ready yet.
import { addDays } from './time'

export const DEMO_CODE = 'DEMO'

const at = (weekStart, day, hhmm) => {
  const [h, m] = hhmm.split(':').map(Number)
  const d = addDays(weekStart, day)
  d.setHours(h, m, 0, 0)
  return d.toISOString()
}

const room = (name, building) => ({ name, building })

export function makeDemoTimetable(weekStart) {
  const t = (day, hhmm) => at(weekStart, day, hhmm)
  const base = { intake_code: 'APU1F2611CS', group_number: 1 }
  const changedAt = new Date(Date.now() - 26 * 3600 * 1000).toISOString()
  const cancelledAt = new Date(Date.now() - 3 * 3600 * 1000).toISOString()

  const rescheduled = {
    action: 'reschedule', reason: 'Lecturer attending an industry conference', created_at: changedAt,
    old_starts_at: t(1, '14:00'), new_starts_at: t(2, '08:30'),
    old_room: room('B-04-01', 'Block B'), new_room: room('B-07-05', 'Block B'),
  }
  const cancelled = {
    action: 'cancel', reason: 'Lecturer on medical leave. Replacement class will be announced.', created_at: cancelledAt,
    old_starts_at: t(3, '10:45'), new_starts_at: null, old_room: room('B-05-03', 'Block B'), new_room: null,
  }

  const classes = [
    { id: 'd1', course_code: 'CT088-3-1', course_name: 'Python Programming', course_type: 'lecture', starts_at: t(0, '08:30'), ends_at: t(0, '10:30'), room: room('B-04-05', 'Block B'), lecturer: 'Daniel Tan' },
    { id: 'd2', course_code: 'CT088-3-1', course_name: 'Python Programming', course_type: 'lab', starts_at: t(0, '13:30'), ends_at: t(0, '15:30'), room: room('LAB-04-03', 'Spine'), lecturer: 'Daniel Tan' },
    { id: 'd3', course_code: 'CT045-3-1', course_name: 'Digital Forensics Fundamentals', course_type: 'lecture', starts_at: t(1, '10:45'), ends_at: t(1, '12:45'), room: room('Auditorium 2', 'Spine'), lecturer: 'Michelle Lim' },
    { id: 'd4', course_code: 'CT102-3-1', course_name: 'Computer Systems Architecture', course_type: 'lecture', starts_at: t(2, '08:30'), ends_at: t(2, '10:30'), room: room('B-07-05', 'Block B'), lecturer: 'Jason Lee', latest_change: rescheduled },
    { id: 'd5', course_code: 'AQ077-3-1', course_name: 'Mathematical Concepts for Computing', course_type: 'tutorial', starts_at: t(2, '13:30'), ends_at: t(2, '14:30'), room: room('B-06-02', 'Block B'), lecturer: 'Siti Aisyah' },
    { id: 'd6', course_code: 'CT043-3-1', course_name: 'Introduction to Networking', course_type: 'lecture', starts_at: t(3, '10:45'), ends_at: t(3, '12:45'), status: 'cancelled', room: room('B-05-03', 'Block B'), lecturer: 'Rachel Wong', latest_change: cancelled },
    { id: 'd7', course_code: 'CT043-3-1', course_name: 'Introduction to Networking', course_type: 'lab', starts_at: t(3, '14:00'), ends_at: t(3, '16:00'), room: room('LAB-04-07', 'Spine'), lecturer: 'Rachel Wong' },
    { id: 'd8', course_code: 'MPU3112', course_name: 'Fundamentals of Entrepreneurship', course_type: 'lecture', starts_at: t(4, '09:00'), ends_at: t(4, '11:00'), room: room('B-08-05', 'Block B'), lecturer: 'Kevin Chen' },
  ].map((c) => ({ status: 'scheduled', latest_change: null, ...base, ...c }))

  const meetings = [
    { id: 'm1', starts_at: t(4, '14:00'), ends_at: t(4, '14:30'), status: 'scheduled', lecturer: 'Siti Aisyah', room: null },
  ]

  const recent_changes = [
    { ...cancelled, class_session_id: 'd6', course_code: 'CT043-3-1', course_name: 'Introduction to Networking', current_starts_at: t(3, '10:45'), status: 'cancelled' },
    { ...rescheduled, class_session_id: 'd4', course_code: 'CT102-3-1', course_name: 'Computer Systems Architecture', current_starts_at: t(2, '08:30'), status: 'scheduled' },
  ]

  return {
    student: {
      id: 'demo', student_code: 'TP000001', full_name: 'Demo Student',
      intakes: [{ intake_id: 'demo', intake_code: 'APU1F2611CS', group_number: 1 }],
    },
    start: weekStart.toISOString(),
    end: addDays(weekStart, 7).toISOString(),
    classes,
    meetings,
    recent_changes,
  }
}
