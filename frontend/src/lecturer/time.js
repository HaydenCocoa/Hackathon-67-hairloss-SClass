// Date and time helpers for the Lecturer page.
// Dates travel as "YYYY-MM-DD" strings and times as "HH:MM" in Asia/Kuala_Lumpur (UTC+8), exactly as
// the API sends them. Day maths runs at noon UTC so no browser time zone can shift a date.

export const TZ = 'Asia/Kuala_Lumpur'

const pad = (n) => String(n).padStart(2, '0')
const parseIso = (iso) => new Date(`${iso}T12:00:00Z`)

/** Today's date in Kuala Lumpur, whatever the browser's own time zone is. */
export const todayIso = (now = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(now)

export const toIso = (date) => date.toISOString().slice(0, 10)
export const addDays = (iso, n) => toIso(new Date(parseIso(iso).getTime() + n * 86400000))

/** The Monday of the week containing iso (weeks run Monday to Sunday). */
export const mondayOf = (iso) => addDays(iso, -((parseIso(iso).getUTCDay() + 6) % 7))

export const formatDate = (iso, options) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', ...options }).format(parseIso(iso))

export const longDate = (iso) =>
  formatDate(iso, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

/** "13:05" -> "1:05 PM" */
export function formatTime(hhmm) {
  const [h, m] = hhmm.split(':').map(Number)
  return `${h % 12 || 12}:${pad(m)} ${h < 12 ? 'AM' : 'PM'}`
}

/** The end of a class: start + the course's duration. Returns null until the start time is valid. */
export function endTime(startHhmm, minutes) {
  if (!/^\d{2}:\d{2}$/.test(startHhmm || '')) return null
  const [h, m] = startHhmm.split(':').map(Number)
  const total = h * 60 + m + minutes
  return { hhmm: `${pad(Math.floor(total / 60) % 24)}:${pad(total % 60)}`, nextDay: total >= 1440 }
}

// When classes can run: Monday to Friday, 08:30 to 18:00 (Config/config.json opening_hours; the backend
// checks the configured hours and closed dates with the scheduling engine).
export const OPEN_TIME = '08:30'
export const CLOSE_TIME = '18:00'
const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
const fromMinutes = (m) => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`

export const isWeekend = (iso) => [0, 6].includes(parseIso(iso).getUTCDay())

/** The current time in Kuala Lumpur as "HH:MM". */
export const nowTime = (now = new Date()) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now)

/** The latest start time that still lets a class of this length finish by 18:00, or null if it never fits. */
export const latestStart = (minutes) => {
  const latest = toMinutes(CLOSE_TIME) - minutes
  return latest >= toMinutes(OPEN_TIME) ? fromMinutes(latest) : null
}

/**
 * Why the date / start time the lecturer typed cannot be used. Returns { date, time } with a message,
 * or an empty string when that field is fine. A field left empty has no message (the form asks for it).
 */
export function requestProblems(date, time, minutes, today, now = nowTime()) {
  const out = { date: '', time: '' }
  if (date) {
    if (date < today) out.date = 'That date has already passed. Choose today or a later date.'
    else if (isWeekend(date)) out.date = 'Classes run Monday to Friday only. Choose a weekday.'
  }
  if (/^\d{2}:\d{2}$/.test(time || '')) {
    const latest = latestStart(minutes)
    if (time < OPEN_TIME) out.time = `Classes start at ${formatTime(OPEN_TIME)} or later.`
    else if (latest === null) out.time = `A ${minutes}-minute class does not fit between ${formatTime(OPEN_TIME)} and ${formatTime(CLOSE_TIME)}.`
    else if (time > latest) {
      out.time = `This class lasts ${minutes} minutes, so it must start by ${formatTime(latest)} to finish by ${formatTime(CLOSE_TIME)}.`
    } else if (date === today && !out.date && time <= now) out.time = 'That time has already passed today.'
  }
  return out
}

/** "9 – 15 Nov 2026" or "28 Dec – 3 Jan 2027" */
export function weekLabel(startIso) {
  const end = addDays(startIso, 6)
  const sameMonth = startIso.slice(0, 7) === end.slice(0, 7)
  const from = formatDate(startIso, sameMonth ? { day: 'numeric' } : { day: 'numeric', month: 'short' })
  return `${from} – ${formatDate(end, { day: 'numeric', month: 'short', year: 'numeric' })}`
}

/** The seven days of the week starting at startIso, ready for display. */
export function weekDays(startIso, today) {
  return Array.from({ length: 7 }, (_, i) => {
    const iso = addDays(startIso, i)
    return {
      iso,
      dow: formatDate(iso, { weekday: 'short' }),
      dom: formatDate(iso, { day: 'numeric' }),
      long: formatDate(iso, { weekday: 'long', day: 'numeric', month: 'long' }),
      isToday: iso === today,
    }
  })
}
