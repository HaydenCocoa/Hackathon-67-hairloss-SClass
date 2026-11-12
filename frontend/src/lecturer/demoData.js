// Demo data for the Lecturer page, used until the backend suggestions endpoint exists
// (see dataSource.js). It has the same functions and response shapes as lecturerApi.js, keeps its
// state in memory (a page reload resets it), and its suggestion engine follows the same rules the
// real backend will: no room, lecturer or student-group clash, and a room of the right type and size.

import { ApiError } from './lecturerApi.js'
import { addDays, mondayOf } from './time.js'

const ROOMS = [
  { id: 'demo-room-1', name: 'Hall A', building: 'Main', capacity: 120, room_type: 'auditorium' },
  { id: 'demo-room-2', name: 'Hall B', building: 'Main', capacity: 120, room_type: 'auditorium' },
  { id: 'demo-room-3', name: 'Room B204', building: 'Block B', capacity: 40, room_type: 'classroom' },
  { id: 'demo-room-4', name: 'Room B205', building: 'Block B', capacity: 40, room_type: 'classroom' },
  { id: 'demo-room-5', name: 'Lab 1', building: 'Tech', capacity: 40, room_type: 'lab' },
  { id: 'demo-room-6', name: 'Lab 2', building: 'Tech', capacity: 40, room_type: 'lab' },
]

const LECTURERS = [
  { id: 'demo-lecturer-1', name: 'Dr. Aisha Rahman' },
  { id: 'demo-lecturer-2', name: 'Prof. Daniel Lim' },
  { id: 'demo-lecturer-3', name: 'Dr. Priya Nair' },
]

// One entry per teaching type, as in the courses table.
const COURSES = {
  'CS101-lecture': { code: 'CS101', name: 'Introduction to Programming', type: 'lecture', minutes: 120 },
  'CS101-lab': { code: 'CS101', name: 'Introduction to Programming', type: 'lab', minutes: 90 },
  'CS201-lecture': { code: 'CS201', name: 'Data Structures', type: 'lecture', minutes: 120 },
  'CS201-tutorial': { code: 'CS201', name: 'Data Structures', type: 'tutorial', minutes: 60 },
  'MA110-lecture': { code: 'MA110', name: 'Discrete Mathematics', type: 'lecture', minutes: 120 },
  'DB301-lecture': { code: 'DB301', name: 'Database Systems', type: 'lecture', minutes: 120 },
  'DB301-lab': { code: 'DB301', name: 'Database Systems', type: 'lab', minutes: 120 },
  'SE220-tutorial': { code: 'SE220', name: 'Software Engineering', type: 'tutorial', minutes: 60 },
}

// Which room types a course type may use (the backend decides the same way).
// scheduling.room_compatibility in Config/config.json ('others' and unknown types: no rooms).
const ROOM_TYPES = { lecture: ['classroom', 'auditorium'], tutorial: ['classroom', 'lab'], lab: ['classroom', 'lab'] }
const roomTypesOf = (s) => ROOM_TYPES[s.course.type] ?? []

// Intake I1 has two groups (so the group is shown); I2 has one (so it is hidden).
const INTAKES = { I1: { maxGroup: 2 }, I2: { maxGroup: 1 } }
const STUDENTS = { 'I1|1': 36, 'I1|2': 28, 'I2|1': 38 }

// The weekly pattern: [day offset from Monday, start, course, lecturer index, intake, group, room]
const WEEKLY = [
  [0, '09:00', 'CS101-lecture', 0, 'I1', 1, 'demo-room-1'],
  [1, '10:00', 'CS101-lab', 0, 'I1', 1, 'demo-room-5'],
  [2, '14:00', 'SE220-tutorial', 0, 'I2', 1, 'demo-room-3'],
  [3, '09:00', 'CS201-lecture', 0, 'I2', 1, 'demo-room-3'],
  [0, '14:00', 'MA110-lecture', 1, 'I1', 2, 'demo-room-4'],
  [1, '14:00', 'CS201-tutorial', 1, 'I2', 1, 'demo-room-3'],
  [2, '09:00', 'MA110-lecture', 1, 'I1', 1, 'demo-room-4'],
  [4, '10:00', 'MA110-lecture', 1, 'I1', 2, 'demo-room-4'],
  [1, '09:00', 'DB301-lecture', 2, 'I2', 1, 'demo-room-2'],
  [2, '09:00', 'DB301-lab', 2, 'I2', 1, 'demo-room-6'],
  [3, '14:00', 'SE220-tutorial', 2, 'I1', 1, 'demo-room-4'],
]

// Same rules as the backend (Config/config.json): Monday to Friday, 08:30 to 18:00,
// and at least 15 minutes between classes of the same room, lecturer or students.
const DAY_START = 8 * 60 + 30 // suggestions are offered every 30 minutes
const DAY_END = 18 * 60
const STEP = 30
const GAP = 15

const pad = (n) => String(n).padStart(2, '0')
const toMin = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
const fromMin = (m) => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`
const overlaps = (a1, a2, b1, b2) => a1 < b2 + GAP && b1 < a2 + GAP // too close counts as a clash
const isWeekend = (iso) => [0, 6].includes(new Date(`${iso}T00:00:00Z`).getUTCDay())
const nameOf = (s) => `${s.course.code} ${s.course.type}`

/** @param now a function returning the current Date; tests pass a fixed one. */
export function createDemoApi(now = () => new Date()) {
  // Kuala Lumpur wall clock as "YYYY-MM-DDTHH:MM".
  const klNow = () => new Date(now().getTime() + 8 * 3600e3).toISOString().slice(0, 16)
  const klToday = () => klNow().slice(0, 10)

  // --- build three weeks of classes starting with this week's Monday ---
  const monday = mondayOf(klToday())
  const sessions = []
  for (let week = 0; week < 3; week++) {
    for (const [day, start, courseKey, lecturerIndex, intake, group, roomId] of WEEKLY) {
      sessions.push({
        id: `demo-session-${sessions.length + 1}`,
        lecturerId: LECTURERS[lecturerIndex].id,
        course: COURSES[courseKey],
        intake,
        group,
        date: addDays(monday, week * 7 + day),
        start,
        roomId,
        status: 'scheduled',
        moved: false,
      })
    }
  }
  sessions[1 + WEEKLY.length].status = 'cancelled' // Aisha's lab next week, so the cancelled style is visible
  sessions[3 + WEEKLY.length].moved = true // and one class that was moved before

  const room = (id) => ROOMS.find((r) => r.id === id)
  const endOf = (s, start = s.start) => fromMin(toMin(start) + s.course.minutes)
  const students = (s) => STUDENTS[`${s.intake}|${s.group}`] ?? 0
  const startsInFuture = (date, start) => `${date}T${start}` > klNow()

  function view(s) {
    const r = room(s.roomId)
    return {
      id: s.id,
      course_code: s.course.code,
      course_name: s.course.name,
      course_type: s.course.type,
      duration_minutes: s.course.minutes,
      intake_code: s.intake,
      group_number: INTAKES[s.intake].maxGroup > 1 ? s.group : null,
      required_room_type: roomTypesOf(s)[0],
      allowed_room_types: roomTypesOf(s),
      student_count: students(s),
      session_date: s.date,
      start_time: s.start,
      end_time: endOf(s),
      room_id: s.roomId,
      room_name: r?.name ?? null,
      building: r?.building ?? null,
      status: s.status,
      moved: s.moved,
      can_reschedule: s.status === 'scheduled' && startsInFuture(s.date, s.start),
    }
  }

  /** Every clash the proposed slot would cause for session s (an empty list means it is free). */
  function conflictsFor(s, date, startMin, roomId) {
    const endMin = startMin + s.course.minutes
    const found = []
    for (const other of sessions) {
      if (other.id === s.id || other.status !== 'scheduled' || other.date !== date) continue
      const o1 = toMin(other.start)
      const o2 = o1 + other.course.minutes
      if (!overlaps(startMin, endMin, o1, o2)) continue
      const when = `${other.start} – ${endOf(other)}`
      if (other.roomId === roomId) {
        found.push({ type: 'room', message: `${room(roomId).name} is already booked for ${nameOf(other)} (${when}).` })
      }
      if (other.lecturerId === s.lecturerId) {
        found.push({ type: 'lecturer', message: `You already have ${nameOf(other)} (${when}).` })
      }
      if (other.intake === s.intake && other.group === s.group) {
        found.push({ type: 'student', message: `This group already has ${nameOf(other)} (${when}).` })
      }
    }
    return found
  }

  const fits = (s, r) => roomTypesOf(s).includes(r.room_type) && r.capacity >= students(s)

  function ownSession(lecturerId, sessionId) {
    const s = sessions.find((x) => x.id === sessionId)
    if (!s) throw new ApiError('Class not found.')
    if (s.lecturerId !== lecturerId) throw new ApiError('You do not teach this class.')
    if (s.status !== 'scheduled') throw new ApiError('A cancelled class cannot be rescheduled.')
    if (!startsInFuture(s.date, s.start)) throw new ApiError('Classes that have already started cannot be rescheduled.')
    return s
  }

  return {
    async listLecturers() {
      return LECTURERS.map((l) => ({ ...l }))
    },

    async getTimetable(lecturerId, { start, end } = {}) {
      if (!LECTURERS.some((l) => l.id === lecturerId)) throw new ApiError('Lecturer not found.')
      return sessions
        .filter((s) => s.lecturerId === lecturerId && (!start || s.date >= start) && (!end || s.date <= end))
        .sort((a, b) => (a.date + a.start).localeCompare(b.date + b.start))
        .map(view)
    },

    /**
     * Free slots near the lecturer's request, best first, at most `limit`, at least an hour apart on a
     * day. Same contract as GET /api/lecturers/{id}/sessions/{id}/suggestions.
     */
    async suggestSlots(lecturerId, sessionId, { date, time, flexDays = 1, limit = 6 } = {}) {
      const s = ownSession(lecturerId, sessionId)
      const wanted = toMin(time || s.start)
      const candidates = []
      for (let offset = -flexDays; offset <= flexDays; offset++) {
        const day = addDays(date, offset)
        if (day < klToday() || isWeekend(day)) continue
        for (let m = DAY_START; m + s.course.minutes <= DAY_END; m += STEP) {
          const start = fromMin(m)
          if ((day === s.date && start === s.start) || !startsInFuture(day, start)) continue
          const free = ROOMS.filter((r) => fits(s, r))
            .sort((a, b) => a.capacity - b.capacity || a.name.localeCompare(b.name))
            .find((r) => conflictsFor(s, day, m, r.id).length === 0)
          if (!free) continue
          candidates.push({
            score: Math.abs(offset) * 1000 + Math.abs(m - wanted),
            slot: {
              session_date: day,
              start_time: start,
              end_time: fromMin(m + s.course.minutes),
              room_id: free.id,
              room_name: free.name,
              building: free.building,
              capacity: free.capacity,
            },
          })
        }
      }
      candidates.sort((a, b) => a.score - b.score)
      const chosen = []
      for (const { slot } of candidates) {
        const crowded = chosen.some(
          (c) => c.session_date === slot.session_date && Math.abs(toMin(c.start_time) - toMin(slot.start_time)) < 60,
        )
        if (!crowded) chosen.push(slot)
        if (chosen.length === limit) break
      }
      return chosen
    },

    /** Applies the move if it is still free (a stale suggestion fails with the clashes listed). */
    async reschedule(lecturerId, sessionId, { session_date, start_time, room_id }) {
      const s = ownSession(lecturerId, sessionId)
      if (!startsInFuture(session_date, start_time)) throw new ApiError('Choose a start time in the future.')
      if (isWeekend(session_date)) throw new ApiError('Classes run Monday to Friday only.')
      const endMin = toMin(start_time) + s.course.minutes
      if (toMin(start_time) < DAY_START || endMin > DAY_END) {
        throw new ApiError('Classes must start at 08:30 or later and finish by 18:00.')
      }
      const target = room(room_id)
      if (!target) throw new ApiError('That room is not available.')
      if (!fits(s, target)) {
        throw new ApiError(`${target.name} does not suit this class (needs ${roomTypesOf(s).join(' or ')} for ${students(s)} students).`)
      }
      const conflicts = conflictsFor(s, session_date, toMin(start_time), room_id)
      if (conflicts.length) throw new ApiError('That slot clashes with another booking.', conflicts)
      Object.assign(s, { date: session_date, start: start_time, roomId: room_id, moved: true })
      return { id: s.id, session_date, start_time, end_time: endOf(s), room_id }
    },
  }
}

// The instance the page uses; each function is also a named export so `import * as demoApi` works.
export const { listLecturers, getTimetable, suggestSlots, reschedule } = createDemoApi()
