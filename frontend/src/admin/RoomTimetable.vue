<script setup>
// Admin > Timetable: one room's classes for one week (Monday to Sunday) as a calendar,
// with the "Schedule Class" entry point to /admin/schedule (opens in a new tab).
// Read-only. Data: GET /api/admin/timetable/rooms and GET /api/admin/timetable (whole week, all rooms,
// filtered here by the selected room so switching rooms needs no new request).
import { computed, onMounted, ref, watch } from 'vue'
import {
  CAMPUS_TZ, addDays, eventLines, formatRange, hourLabel, layoutWeek, mondayOf, roomLabel, sortRooms, todayIso, toneOf,
  weekDays, weekLabel, weekRange,
} from './roomCalendar'

const props = defineProps({
  token: { type: String, default: '' }, // optional pasted Supabase token; otherwise the login session is used
  demo: { type: Boolean, default: false },
  demoRooms: { type: Array, default: () => [] },
  demoSessions: { type: Array, default: () => [] },
  refresh: { type: Number, default: 0 }, // the admin page bumps this when "Connect" or the tab is chosen
})

const HOUR_PX = 56 // height of one hour in the grid

const today = ref(todayIso())
const weekStart = ref(mondayOf(today.value))
const rooms = ref([])
const roomId = ref('')
const sessions = ref([])
const loading = ref(false)
const error = ref('')
let latest = 0 // ignore replies to requests that are no longer current

const days = computed(() => weekDays(weekStart.value, today.value))
const label = computed(() => weekLabel(weekStart.value))
const selectedRoom = computed(() => rooms.value.find((room) => room.id === roomId.value) || null)
const layout = computed(() => layoutWeek(sessions.value, roomId.value, weekStart.value))
const hours = computed(() => Array.from({ length: layout.value.lastHour - layout.value.firstHour }, (_, i) => layout.value.firstHour + i))
const gridHeight = computed(() => hours.value.length * HOUR_PX)
const classCount = computed(() => Object.values(layout.value.days).reduce((sum, list) => sum + list.length, 0))

function headers() {
  return props.token.trim() ? { Authorization: `Bearer ${props.token.trim()}` } : {}
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json', ...headers() } })
  let body = null
  try { body = await response.json() } catch { /* handled below */ }
  if (!response.ok) {
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'The timetable could not be loaded.')
  }
  return body
}

function pickRoom(list) {
  if (!list.some((room) => room.id === roomId.value)) roomId.value = list[0]?.id ?? ''
}

async function load() {
  const request = ++latest
  error.value = ''
  if (props.demo) {
    rooms.value = sortRooms(props.demoRooms)
    pickRoom(rooms.value)
    sessions.value = props.demoSessions
    return
  }
  loading.value = true
  try {
    const { start, end } = weekRange(weekStart.value)
    const query = new URLSearchParams({ start, end })
    const [roomRows, sessionRows] = await Promise.all([
      getJson('/api/admin/timetable/rooms'),
      getJson(`/api/admin/timetable?${query}`),
    ])
    if (request !== latest) return
    rooms.value = sortRooms(roomRows)
    pickRoom(rooms.value)
    sessions.value = sessionRows
  } catch (e) {
    if (request !== latest) return
    sessions.value = []
    error.value = e.message
  } finally {
    if (request === latest) loading.value = false
  }
}

function goToday() {
  today.value = todayIso()
  weekStart.value = mondayOf(today.value)
}

function eventStyle(event) {
  const top = ((event.startMinutes - layout.value.firstHour * 60) / 60) * HOUR_PX
  const height = Math.max(((event.endMinutes - event.startMinutes) / 60) * HOUR_PX, 22)
  const width = 100 / event.lanes
  return { top: `${top}px`, height: `${height}px`, left: `calc(${event.lane * width}% + 2px)`, width: `calc(${width}% - 4px)` }
}

function eventLabel(event) {
  const parts = [
    `${event.course_code} ${event.course_type || ''}`.trim(), event.course_name,
    formatRange(event.startMinutes, event.endMinutes),
    `${event.intake?.intake_code || 'Intake'} · Group ${event.group_number}`,
    event.lecturer?.full_name, event.status === 'cancelled' ? 'Cancelled' : event.status === 'rescheduled' ? 'Rescheduled' : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

watch(weekStart, load)
watch(() => [props.refresh, props.demo], load)
onMounted(load)
</script>

<template>
  <section class="rt" aria-labelledby="rt-title">
    <header class="rt-head">
      <div>
        <h2 id="rt-title">Room timetable</h2>
        <p class="rt-sub">One room's classes for the week, in campus time ({{ CAMPUS_TZ }}).</p>
      </div>
      <label class="rt-room">Room
        <select v-model="roomId" :disabled="!rooms.length">
          <option v-if="!rooms.length" value="">No rooms</option>
          <option v-for="room in rooms" :key="room.id" :value="room.id">{{ roomLabel(room) }}</option>
        </select>
      </label>
    </header>

    <div class="rt-toolbar">
      <div class="rt-nav">
        <button type="button" class="rt-btn" @click="goToday">Today</button>
        <button type="button" class="rt-icon" aria-label="Previous week" @click="weekStart = addDays(weekStart, -7)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z" /></svg>
        </button>
        <button type="button" class="rt-icon" aria-label="Next week" @click="weekStart = addDays(weekStart, 7)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.6 16.6 10 18l6-6-6-6-1.4 1.4 4.6 4.6z" /></svg>
        </button>
        <strong class="rt-week" aria-live="polite">{{ label }}</strong>
      </div>
      <ul class="rt-legend" aria-label="Course types">
        <li><span class="rt-dot rt-blue"></span>Lecture</li>
        <li><span class="rt-dot rt-green"></span>Tutorial</li>
        <li><span class="rt-dot rt-yellow"></span>Lab</li>
        <li><span class="rt-dot rt-red"></span>Other</li>
        <li><span class="rt-dot rt-cancelled"></span>Cancelled</li>
      </ul>
    </div>

    <p v-if="error" class="rt-state rt-error" role="alert">
      {{ error }} <button type="button" class="rt-btn" @click="load">Try again</button>
    </p>
    <p v-else-if="loading" class="rt-state" aria-busy="true">Loading the week…</p>
    <p v-else-if="selectedRoom && !classCount" class="rt-state">No classes in {{ selectedRoom.name }} this week.</p>

    <div class="rt-scroll">
      <div class="rt-grid" :class="{ 'is-loading': loading }">
        <div class="rt-corner" aria-hidden="true"></div>
        <div v-for="day in days" :key="day.iso" class="rt-day-head" :class="{ 'is-weekend': day.weekend, 'is-today': day.isToday }">
          <span class="rt-dow">{{ day.dow }}</span>
          <span class="rt-dom" :aria-label="day.label">{{ day.dom }}</span>
        </div>

        <div class="rt-gutter" :style="{ height: `${gridHeight}px` }" aria-hidden="true">
          <span v-for="hour in hours" :key="hour" class="rt-hour" :style="{ top: `${(hour - layout.firstHour) * HOUR_PX}px` }">{{ hourLabel(hour) }}</span>
        </div>
        <div
          v-for="day in days" :key="`col-${day.iso}`" class="rt-col"
          :class="{ 'is-weekend': day.weekend, 'is-today': day.isToday }"
          :style="{ height: `${gridHeight}px`, backgroundSize: `100% ${HOUR_PX}px` }"
          role="list" :aria-label="`${day.label}${day.weekend ? ' (weekend)' : ''}`"
        >
          <article
            v-for="event in layout.days[day.iso]" :key="event.id" role="listitem"
            class="rt-event" :class="[`rt-${toneOf(event.course_type)}`, { 'is-cancelled': event.status === 'cancelled' }]"
            :style="eventStyle(event)" :title="eventLabel(event)" :aria-label="eventLabel(event)" tabindex="0"
          >
            <strong>{{ event.course_code }}<span v-if="event.status === 'rescheduled'" class="rt-chip">Moved</span></strong>
            <span>{{ formatRange(event.startMinutes, event.endMinutes) }}</span>
            <span v-if="eventLines(event.endMinutes - event.startMinutes) >= 3">{{ event.intake?.intake_code || 'Intake' }} · G{{ event.group_number }}</span>
            <span v-if="eventLines(event.endMinutes - event.startMinutes) >= 4">{{ event.lecturer?.full_name }}</span>
          </article>
        </div>
      </div>
    </div>

    <div class="rt-actions">
      <a class="rt-schedule" href="/admin/schedule" target="_blank" rel="noopener">Schedule Class</a>
      <small>Opens the scheduling workspace in a new tab.</small>
    </div>
  </section>
</template>

<style scoped>
.rt { --blue: #1a73e8; --green: #188038; --line: #e2e7ef; --muted: #5f6368; --grey: #f1f3f4; color: #202124; }
.rt h2 { margin: 0; text-transform: none; }
.rt-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.rt-sub { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.rt-room { margin: 0; min-width: min(100%, 340px); text-transform: none; }
.rt-room { display: block; font-size: 14px; font-weight: 600; }
.rt-room select {
  display: block; width: 100%; margin-top: 6px; padding: 10px; border: 1px solid #cdd5e0; border-radius: 8px;
  background: #fff; color: #202124; font: inherit; font-weight: 400;
}
.rt button { font: inherit; cursor: pointer; }
.rt-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin: 18px 0 12px; }
.rt-nav { display: flex; align-items: center; gap: 6px; }
.rt-week { margin-left: 8px; font-size: 18px; font-weight: 500; }
.rt-btn { border: 1px solid #dadce0; border-radius: 8px; background: #fff; color: #3c4043; padding: 7px 14px; }
.rt-btn:hover { background: var(--grey); }
.rt-icon { display: grid; place-items: center; border: 0; background: transparent; width: 36px; height: 36px; padding: 0; border-radius: 50%; }
.rt-icon svg { width: 22px; height: 22px; fill: #3c4043; }
.rt-icon:hover { background: var(--grey); }
button:focus-visible, .rt-event:focus-visible, .rt-schedule:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.rt-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 0; padding: 0; list-style: none; font-size: 13px; color: var(--muted); }
.rt-legend li { display: flex; align-items: center; gap: 6px; }
.rt-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.rt-dot.rt-blue { background: #4285f4; } .rt-dot.rt-green { background: #34a853; } .rt-dot.rt-yellow { background: #fbbc04; }
.rt-dot.rt-red { background: #ea4335; } .rt-dot.rt-cancelled { background: #bdc1c6; }
.rt-state { margin: 0 0 12px; padding: 10px 14px; border-radius: 8px; background: #f8f9fa; color: var(--muted); font-size: 14px; }
.rt-error { background: #fce8e6; color: #b3261e; }

.rt-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: #fff; }
.rt-grid { display: grid; grid-template-columns: 56px repeat(7, minmax(96px, 1fr)); min-width: 760px; transition: opacity .15s; }
.rt-grid.is-loading { opacity: .55; }
.rt-corner, .rt-day-head { border-bottom: 1px solid var(--line); }
.rt-day-head { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 10px 0 8px; border-left: 1px solid var(--line); }
.rt-dow { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.rt-dom { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; font-size: 20px; }
.rt-day-head.is-today .rt-dow { color: var(--blue); }
.rt-day-head.is-today .rt-dom { background: var(--blue); color: #fff; }
.rt-day-head.is-weekend { background: var(--grey); }
.rt-day-head.is-weekend .rt-dow, .rt-day-head.is-weekend .rt-dom { color: #9aa0a6; }

.rt-gutter { position: relative; }
.rt-hour { position: absolute; right: 8px; transform: translateY(-50%); font-size: 11px; color: var(--muted); white-space: nowrap; }
.rt-hour:first-child { transform: none; }
.rt-col {
  position: relative; border-left: 1px solid var(--line);
  background-image: linear-gradient(to bottom, var(--line) 1px, transparent 1px);
}
.rt-col.is-weekend { background-color: var(--grey); }

.rt-event {
  position: absolute; box-sizing: border-box; overflow: hidden; display: flex; flex-direction: column; gap: 1px;
  padding: 4px 6px; border-radius: 6px; border-left: 4px solid; font-size: 12px; line-height: 1.3; cursor: default;
}
.rt-event > * { flex-shrink: 0; }
.rt-event strong { display: flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; }
.rt-event span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rt-event.rt-blue { background: #e8f0fe; border-color: #4285f4; }
.rt-event.rt-green { background: #e6f4ea; border-color: #34a853; }
.rt-event.rt-yellow { background: #fef7e0; border-color: #fbbc04; }
.rt-event.rt-red { background: #fce8e6; border-color: #ea4335; }
.rt-event.is-cancelled { background: #f8f9fa; border-color: #bdc1c6; color: #80868b; text-decoration: line-through; }
.rt-chip { padding: 0 5px; border-radius: 8px; background: #fbbc04; color: #202124; font-size: 10px; font-weight: 600; text-decoration: none; }

.rt-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 18px; }
.rt-schedule {
  display: inline-block; padding: 11px 22px; border-radius: 8px; background: var(--green); color: #fff;
  font-weight: 600; text-decoration: none; box-shadow: 0 1px 2px rgba(60, 64, 67, .3);
}
.rt-schedule:hover { background: #137333; }
.rt-actions small { color: var(--muted); }
</style>
