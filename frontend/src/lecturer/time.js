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
