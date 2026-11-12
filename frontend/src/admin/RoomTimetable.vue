<script setup>
// Admin > Timetable: one room's classes for one week (Monday to Sunday) as a calendar,
// with the "Schedule Class" entry point to /admin/schedule (opens in a new tab).
// Read-only. Data: GET /api/admin/timetable/rooms and GET /api/admin/timetable (whole week, all rooms,
// filtered here by the selected room so switching rooms needs no new request).
import { computed, onMounted, ref, watch } from 'vue'
import {
  CAMPUS_TZ, addDays, eventLines, formatRange, layoutWeek, mondayOf, roomLabel, sortRooms, todayIso,
  weekDays, weekLabel, weekRange,
} from './roomCalendar'
import RescheduleClassDialog from './RescheduleClassDialog.vue'
import { classLabel, reschedulable } from './reschedule'
import WeekGrid from './WeekGrid.vue'

const props = defineProps({
  token: { type: String, default: '' }, // optional pasted Supabase token; otherwise the login session is used
  demo: { type: Boolean, default: false },
  demoRooms: { type: Array, default: () => [] },
  demoSessions: { type: Array, default: () => [] },
  refresh: { type: Number, default: 0 }, // the admin page bumps this when "Connect" or the tab is chosen
})

const today = ref(todayIso())
const weekStart = ref(mondayOf(today.value))
const rooms = ref([])
const roomId = ref('')
const sessions = ref([])
const loading = ref(false)
const error = ref('')
let latest = 0 // ignore replies to requests that are no longer current
const selectedId = ref('') // class picked in the calendar
const dialogOpen = ref(false)
const dialogClassId = ref('')
const message = ref('') // result of the last reschedule

const days = computed(() => weekDays(weekStart.value, today.value))
const label = computed(() => weekLabel(weekStart.value))
const selectedRoom = computed(() => rooms.value.find((room) => room.id === roomId.value) || null)
const layout = computed(() => layoutWeek(sessions.value, roomId.value, weekStart.value))
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

const lines = (event) => eventLines(event.endMinutes - event.startMinutes)
const movable = computed(() => reschedulable(sessions.value))
const selected = computed(() => sessions.value.find((item) => item.id === selectedId.value) || null)

// Click selects a class; double-click (or Enter) and the Reschedule button open the dialog.
function selectClass(event) {
  selectedId.value = event.id
  message.value = ''
}
function openReschedule(event) {
  if (event) selectedId.value = event.id
  const target = event || selected.value
  if (target && !movable.value.some((item) => item.id === target.id)) {
    message.value = `${classLabel(target)} has started or is cancelled, so it cannot be moved.`
    return
  }
  // Without a selection, start with this room's next class (the dialog lists the whole week).
  dialogClassId.value = target?.id || movable.value.find((item) => item.room_id === roomId.value)?.id || ''
  message.value = ''
  dialogOpen.value = true
}
function onRescheduled({ session, result, room }) {
  dialogOpen.value = false
  message.value = `Rescheduled: ${classLabel({ ...session, starts_at: result.starts_at, ends_at: result.ends_at, room })}. Everyone involved now sees the new time and venue.`
  load()
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

    <WeekGrid
      :days="days" :layout="layout" :describe="eventLabel" :dimmed="loading" :selected-id="selectedId"
      @select="selectClass" @open="openReschedule"
    >
      <template #event="{ event }">
        <strong>{{ event.course_code }}<span v-if="event.status === 'rescheduled'" class="rt-chip">Moved</span></strong>
        <span>{{ formatRange(event.startMinutes, event.endMinutes) }}</span>
        <span v-if="lines(event) >= 3">{{ event.intake?.intake_code || 'Intake' }} · G{{ event.group_number }}</span>
        <span v-if="lines(event) >= 4">{{ event.lecturer?.full_name }}</span>
      </template>
    </WeekGrid>

    <p v-if="message" class="rt-state rt-done" role="status">{{ message }}</p>
    <div class="rt-actions">
      <a class="rt-schedule" href="/admin/schedule" target="_blank" rel="noopener">Schedule Class</a>
      <button type="button" class="rt-reschedule" :disabled="demo" :title="demo ? 'Not available with demo data' : ''" @click="openReschedule()">
        Reschedule
      </button>
      <small>{{ selected ? `Selected: ${classLabel(selected)}` : 'Select a class, then Reschedule; or double-click a class.' }}</small>
    </div>

    <RescheduleClassDialog
      :open="dialogOpen" :sessions="sessions" :initial-id="dialogClassId"
      @close="dialogOpen = false" @saved="onRescheduled"
    />
  </section>
</template>

<style scoped>
.rt { --blue: #1a73e8; --green: #188038; --muted: #5f6368; --grey: #f1f3f4; color: #202124; }
.rt h2 { margin: 0; text-transform: none; }
.rt-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.rt-sub { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.rt-room { display: block; margin: 0; min-width: min(100%, 340px); font-size: 14px; font-weight: 600; text-transform: none; }
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
button:focus-visible, .rt-schedule:focus-visible, .rt-reschedule:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.rt-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 0; padding: 0; list-style: none; font-size: 13px; color: var(--muted); }
.rt-legend li { display: flex; align-items: center; gap: 6px; }
.rt-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.rt-dot.rt-blue { background: #4285f4; } .rt-dot.rt-green { background: #34a853; } .rt-dot.rt-yellow { background: #fbbc04; }
.rt-dot.rt-red { background: #ea4335; } .rt-dot.rt-cancelled { background: #bdc1c6; }
.rt-state { margin: 0 0 12px; padding: 10px 14px; border-radius: 8px; background: #f8f9fa; color: var(--muted); font-size: 14px; }
.rt-error { background: #fce8e6; color: #b3261e; }
.rt-chip { padding: 0 5px; border-radius: 8px; background: #fbbc04; color: #202124; font-size: 10px; font-weight: 600; text-decoration: none; }

.rt-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 18px; }
.rt-schedule {
  display: inline-block; padding: 11px 22px; border-radius: 8px; background: var(--green); color: #fff;
  font-weight: 600; text-decoration: none; box-shadow: 0 1px 2px rgba(60, 64, 67, .3);
}
.rt-schedule:hover { background: #137333; }
.rt-reschedule {
  padding: 11px 22px; border: 0; border-radius: 8px; background: var(--blue); color: #fff; font-weight: 600;
  box-shadow: 0 1px 2px rgba(60, 64, 67, .3);
}
.rt-reschedule:hover:not(:disabled) { background: #1765cc; }
.rt-reschedule:disabled { opacity: .5; cursor: not-allowed; }
.rt-done { margin: 14px 0 0; background: #e6f4ea; color: #0d652d; }
.rt-actions small { color: var(--muted); }
</style>
