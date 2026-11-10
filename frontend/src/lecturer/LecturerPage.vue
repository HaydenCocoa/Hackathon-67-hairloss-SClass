<script setup>
// Lecturer page: pick a lecturer, view their timetable (read-only) and reschedule their classes.
// Opened from the main menu at #/lecturer (see src/App.vue).
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import './lecturer.css'
import { getTimetable, listLecturers, listRooms } from './lecturerApi'
import { addDays, mondayOf, todayIso, weekDays, weekLabel } from './time'
import LecturerTimetable from './LecturerTimetable.vue'
import RescheduleDialog from './RescheduleDialog.vue'
import RescheduleList from './RescheduleList.vue'

const props = defineProps({ appName: { type: String, default: 'SClass' } })

const today = ref(todayIso())
const tab = ref('timetable')

const lecturers = ref([])
const lecturersError = ref('')
const lecturerId = ref('') // a UUID; there is no login yet, so the lecturer is chosen here

const weekStart = ref(mondayOf(today.value))
const weekSessions = ref([])
const loadingWeek = ref(false)
const errorWeek = ref('')

const upcoming = ref([])
const loadingUpcoming = ref(false)
const errorUpcoming = ref('')

const rooms = ref([])
const roomsError = ref('')

const editing = ref(null) // the class open in the reschedule dialog
const toast = ref('')
let toastTimer = null

const lecturerIndex = computed(() => Math.max(0, lecturers.value.findIndex((l) => l.id === lecturerId.value)))
const initials = computed(() => {
  const lecturer = lecturers.value[lecturerIndex.value]
  if (!lecturer) return ''
  const parts = lecturer.name.replace(/\b(Dr|Prof|Mr|Ms|Mrs)\.?\s/gi, '').split(/\s+/).filter(Boolean)
  return ((parts[0] || '')[0] || '').toUpperCase() + ((parts[1] || '')[0] || '').toUpperCase()
})

const days = computed(() =>
  weekDays(weekStart.value, today.value).map((day) => ({
    ...day,
    sessions: weekSessions.value.filter((s) => s.session_date === day.iso),
  })),
)
const label = computed(() => weekLabel(weekStart.value))

function showToast(text) {
  toast.value = text
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 4000)
}

async function loadLecturers() {
  lecturersError.value = ''
  try {
    lecturers.value = await listLecturers()
    let saved = ''
    try {
      saved = localStorage.getItem('lecturerId') || ''
    } catch {
      // Storage can be blocked (private window); the first lecturer is used instead.
    }
    const pick = lecturers.value.find((l) => l.id === saved) || lecturers.value[0]
    lecturerId.value = pick ? pick.id : ''
    if (!pick) lecturersError.value = 'No lecturers found in the database.'
  } catch (e) {
    lecturersError.value = e.message
  }
}

async function loadRooms() {
  roomsError.value = ''
  try {
    rooms.value = await listRooms()
  } catch (e) {
    roomsError.value = e.message
  }
}

async function loadWeek() {
  if (!lecturerId.value) return
  const id = lecturerId.value
  const start = weekStart.value
  loadingWeek.value = true
  errorWeek.value = ''
  try {
    const rows = await getTimetable(id, { start, end: addDays(start, 6) })
    if (id === lecturerId.value && start === weekStart.value) weekSessions.value = rows // ignore stale replies
  } catch (e) {
    errorWeek.value = e.message
  } finally {
    loadingWeek.value = false
  }
}

async function loadUpcoming() {
  if (!lecturerId.value) return
  const id = lecturerId.value
  loadingUpcoming.value = true
  errorUpcoming.value = ''
  try {
    const rows = await getTimetable(id, { start: today.value })
    if (id === lecturerId.value) upcoming.value = rows.filter((s) => s.can_reschedule)
  } catch (e) {
    errorUpcoming.value = e.message
  } finally {
    loadingUpcoming.value = false
  }
}

function goToday() {
  today.value = todayIso()
  weekStart.value = mondayOf(today.value)
}

async function onSaved() {
  showToast('Class rescheduled')
  await Promise.all([loadWeek(), loadUpcoming()])
}

watch(lecturerId, (id) => {
  if (!id) return
  try {
    localStorage.setItem('lecturerId', id)
  } catch {
    // Ignore: remembering the choice is only a convenience.
  }
  weekSessions.value = []
  upcoming.value = []
  loadWeek()
  loadUpcoming()
})
watch(weekStart, loadWeek)

onMounted(() => {
  loadLecturers()
  loadRooms()
})
onBeforeUnmount(() => clearTimeout(toastTimer))
</script>

<template>
  <div class="lecturer">
    <header class="lc-topbar">
      <div class="lc-brand">
        <a class="lc-back" href="#main">← Main menu</a>
        <span class="lc-wordmark">
          <span class="lc-sr">{{ props.appName }}</span>
          <span v-for="(ch, i) in [...props.appName]" :key="i" :class="'lc-c' + (i % 4)" aria-hidden="true">{{ ch }}</span>
        </span>
        <span class="lc-role">Lecturer</span>
      </div>

      <label class="lc-picker">
        <span class="lc-avatar" :class="'lc-tone-' + (lecturerIndex % 4)" aria-hidden="true">{{ initials }}</span>
        <span class="lc-sr">Lecturer</span>
        <select v-model="lecturerId" :disabled="!lecturers.length">
          <option v-for="l in lecturers" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
      </label>
    </header>

    <nav class="lc-tabs" role="tablist" aria-label="Lecturer sections">
      <button id="lc-tab-timetable" type="button" role="tab" aria-controls="lc-panel-timetable" :aria-selected="tab === 'timetable'"
              :class="{ 'is-active': tab === 'timetable' }" @click="tab = 'timetable'">Timetable</button>
      <button id="lc-tab-reschedule" type="button" role="tab" aria-controls="lc-panel-reschedule" :aria-selected="tab === 'reschedule'"
              :class="{ 'is-active': tab === 'reschedule' }" @click="tab = 'reschedule'">Reschedule</button>
    </nav>

    <div class="lc-main">
      <p v-if="lecturersError" class="lc-state lc-state-error" role="alert">
        {{ lecturersError }} <button class="lc-btn lc-btn-text" type="button" @click="loadLecturers">Try again</button>
      </p>

      <LecturerTimetable
        v-show="tab === 'timetable'"
        :days="days"
        :label="label"
        :loading="loadingWeek"
        :error="errorWeek"
        :has-classes="weekSessions.length > 0"
        @prev="weekStart = addDays(weekStart, -7)"
        @next="weekStart = addDays(weekStart, 7)"
        @today="goToday"
        @retry="loadWeek"
      />

      <RescheduleList
        v-show="tab === 'reschedule'"
        :sessions="upcoming"
        :loading="loadingUpcoming"
        :error="errorUpcoming"
        @pick="editing = $event"
        @retry="loadUpcoming"
      />
    </div>

    <RescheduleDialog
      :session="editing"
      :rooms="rooms"
      :rooms-error="roomsError"
      :lecturer-id="lecturerId"
      :today="today"
      @close="editing = null"
      @saved="onSaved"
    />

    <div class="lc-toast" :class="{ 'is-shown': toast }" role="status" aria-live="polite">{{ toast }}</div>
  </div>
</template>
