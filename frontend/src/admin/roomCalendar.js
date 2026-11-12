// Pure helpers for the admin Timetable tab's room calendar (no Vue, no fetch), so they can be unit-tested.
// Dates travel as "YYYY-MM-DD" in the campus time zone; class times come from the API as UTC instants.

export const CAMPUS_TZ = 'Asia/Kuala_Lumpur'
// Kuala Lumpur has no daylight saving, so its offset is fixed. Used for the API's week boundaries.
const CAMPUS_OFFSET = '+08:00'

// The visible day starts and ends on whole hours around the opening hours (08:30–18:00),
// and grows when a booking falls outside them.
const DEFAULT_FIRST_HOUR = 8
const DEFAULT_LAST_HOUR = 19

const pad = (n) => String(n).padStart(2, '0')
// Day maths at noon UTC, so no browser time zone can shift a date.
const noonUtc = (iso) => new Date(`${iso}T12:00:00Z`)
const dateFormat = (options) => new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', ...options })

/** Today's date on campus, whatever the browser's own time zone is. */
export const todayIso = (now = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: CAMPUS_TZ }).format(now)

export const addDays = (iso, days) => new Date(noonUtc(iso).getTime() + days * 86400000).toISOString().slice(0, 10)

/** The Monday of the week containing iso (weeks run Monday to Sunday). */
export const mondayOf = (iso) => addDays(iso, -((noonUtc(iso).getUTCDay() + 6) % 7))

/** start/end for GET /api/admin/timetable: the whole campus week, Monday 00:00 to the next Monday 00:00. */
export const weekRange = (monday) => ({
  start: `${monday}T00:00:00${CAMPUS_OFFSET}`,
  end: `${addDays(monday, 7)}T00:00:00${CAMPUS_OFFSET}`,
})

/** "16 – 22 Nov 2026" or "28 Dec 2026 – 3 Jan 2027" */
export function weekLabel(monday) {
  const sunday = addDays(monday, 6)
  const full = { day: 'numeric', month: 'short', year: 'numeric' }
  const from = monday.slice(0, 4) !== sunday.slice(0, 4) ? full
    : monday.slice(0, 7) !== sunday.slice(0, 7) ? { day: 'numeric', month: 'short' } : { day: 'numeric' }
  return `${dateFormat(from).format(noonUtc(monday))} – ${dateFormat(full).format(noonUtc(sunday))}`
}

/** Monday to Sunday, with Saturday and Sunday marked as the (greyed) weekend. */
export function weekDays(monday, today = todayIso()) {
  return Array.from({ length: 7 }, (_, i) => {
    const iso = addDays(monday, i)
    return {
      iso,
      dow: dateFormat({ weekday: 'short' }).format(noonUtc(iso)),
      dom: dateFormat({ day: 'numeric' }).format(noonUtc(iso)),
      label: dateFormat({ weekday: 'long', day: 'numeric', month: 'long' }).format(noonUtc(iso)),
      weekend: i >= 5,
      isToday: iso === today,
    }
  })
}

const partsFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: CAMPUS_TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

/** A UTC instant as its campus date and minutes after campus midnight. */
export function campusParts(instant) {
  const parts = Object.fromEntries(partsFormat.formatToParts(new Date(instant)).map((p) => [p.type, p.value]))
  return { date: `${parts.year}-${parts.month}-${parts.day}`, minutes: Number(parts.hour) * 60 + Number(parts.minute) }
}

/** 540 -> "9:00 AM" (the lecturer page's 12-hour style). */
export function formatMinutes(total) {
  const h = Math.floor(total / 60) % 24
  return `${h % 12 || 12}:${pad(total % 60)} ${h < 12 ? 'AM' : 'PM'}`
}

/** 510, 630 -> "8:30 – 10:30 AM"; the AM/PM is written once when both ends share it. */
export function formatRange(start, end) {
  const [from, fromHalf] = formatMinutes(start).split(' ')
  const [to, toHalf] = formatMinutes(end).split(' ')
  return fromHalf === toHalf ? `${from} – ${to} ${toHalf}` : `${from} ${fromHalf} – ${to} ${toHalf}`
}

/** How many text lines fit a class block: code + time, then intake/group, then lecturer. */
export const eventLines = (minutes) => (minutes >= 90 ? 4 : minutes >= 60 ? 3 : 2)

/** Hour axis label: 13 -> "1 PM". */
export const hourLabel = (hour) => `${hour % 12 || 12} ${hour % 24 < 12 ? 'AM' : 'PM'}`

/** Google colour per course type (blue, green, yellow, red). */
export const toneOf = (courseType) => ({ lecture: 'blue', tutorial: 'green', lab: 'yellow' })[courseType] || 'red'

export const roomLabel = (room) => `${room.name} · ${room.building} · ${room.room_type} · ${room.capacity} seats`

/** Rooms in a stable order for the drop-down. */
export const sortRooms = (rooms) => [...rooms].sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }))

/**
 * The selected room's classes, grouped by campus day, with minutes and side-by-side lanes for overlaps.
 * Returns { days: { [iso]: event[] }, firstHour, lastHour }.
 */
export function layoutWeek(sessions, roomId, monday) {
  const dayIsos = new Set(Array.from({ length: 7 }, (_, i) => addDays(monday, i)))
  const days = Object.fromEntries([...dayIsos].map((iso) => [iso, []]))
  let first = DEFAULT_FIRST_HOUR * 60
  let last = DEFAULT_LAST_HOUR * 60
  for (const session of sessions) {
    if (!roomId || String(session.room_id) !== String(roomId)) continue
    const start = campusParts(session.starts_at)
    if (!dayIsos.has(start.date)) continue
    const end = campusParts(session.ends_at)
    const endMinutes = end.date === start.date ? Math.max(end.minutes, start.minutes + 1) : 24 * 60
    days[start.date].push({ ...session, startMinutes: start.minutes, endMinutes })
    first = Math.min(first, start.minutes)
    last = Math.max(last, endMinutes)
  }
  for (const iso of dayIsos) assignLanes(days[iso])
  return { days, firstHour: Math.floor(first / 60), lastHour: Math.min(24, Math.ceil(last / 60)) }
}

// Overlapping classes share their cluster's width; each gets its own lane (column).
function assignLanes(events) {
  events.sort((a, b) => a.startMinutes - b.startMinutes || b.endMinutes - a.endMinutes)
  let cluster = []
  let clusterEnd = -1
  const close = () => {
    const lanes = Math.max(1, ...cluster.map((e) => e.lane + 1))
    for (const e of cluster) e.lanes = lanes
    cluster = []
  }
  for (const event of events) {
    if (event.startMinutes >= clusterEnd && cluster.length) close()
    const laneEnds = []
    for (const other of cluster) laneEnds[other.lane] = Math.max(laneEnds[other.lane] ?? -1, other.endMinutes)
    let lane = 0
    while (laneEnds[lane] !== undefined && laneEnds[lane] > event.startMinutes) lane++
    event.lane = lane
    cluster.push(event)
    clusterEnd = Math.max(clusterEnd, event.endMinutes)
  }
  if (cluster.length) close()
}
