<script setup>
// Student Page (Bi Jin): weekly timetable with cancellations and reschedules.
// Shown at /student for the logged-in student; App.vue passes their code as :student-code.
import { computed, ref, watch } from 'vue'
import './student.css'
import AgendaList from './AgendaList.vue'
import SessionDialog from './SessionDialog.vue'
import WeekTimetable from './WeekTimetable.vue'
import { fetchTimetable } from './studentApi'
import { addDays, fmtDateTime, fmtTime, fmtWeekRange, fromDateInput, startOfWeek, timeAgo, toDateInput } from './time'

const props = defineProps({ studentCode: { type: String, default: '' } })

const weekStart = ref(startOfWeek(new Date()))
const view = ref(window.innerWidth < 760 ? 'list' : 'week')
const data = ref(null)
const loading = ref(false)
const error = ref(null) // { message, backendDown }
const selected = ref(null)
const hasCode = computed(() => Boolean(props.studentCode))
let requestId = 0

async function load() {
  const id = ++requestId
  const start = weekStart.value
  error.value = null
  if (!hasCode.value) {
    data.value = null
    loading.value = false
    return
  }
  loading.value = true
  try {
    const result = await fetchTimetable(props.studentCode, start, addDays(start, 7))
    if (id === requestId) data.value = result
  } catch (e) {
    if (id !== requestId) return
    if (e.status === 401) {
      // Login expired: go back to the login page and return here afterwards.
      window.location.assign(`/login?next=${encodeURIComponent('/student')}`)
      return
    }
    error.value = { message: e.message, backendDown: Boolean(e.backendUnavailable) }
    if (!e.backendUnavailable) data.value = null
  } finally {
    if (id === requestId) loading.value = false
  }
}
watch([() => props.studentCode, weekStart], load, { immediate: true })

// Week navigation
const shiftWeek = (n) => { weekStart.value = addDays(weekStart.value, 7 * n) }
const goToday = () => { weekStart.value = startOfWeek(new Date()) }
const goTo = (date) => { weekStart.value = startOfWeek(date) }
const isThisWeek = computed(() => weekStart.value.getTime() === startOfWeek(new Date()).getTime())
const dateInput = computed({
  get: () => toDateInput(weekStart.value),
  set: (v) => { if (v) goTo(fromDateInput(v)) },
})

// Normalise classes and meetings into one event list for the grid and list.
const roomText = (r) => (r ? `${r.name} · ${r.building}` : 'Room to be confirmed')
const events = computed(() => {
  if (!data.value) return []
  const classes = data.value.classes.map((c) => ({
    key: `c-${c.id}`,
    kind: 'class',
    type: c.course_type,
    title: c.course_name,
    subtitle: `${c.course_code} · ${c.course_type.charAt(0).toUpperCase() + c.course_type.slice(1)}`,
    start: new Date(c.starts_at),
    end: new Date(c.ends_at),
    cancelled: c.status === 'cancelled',
    moved: c.latest_change?.action === 'reschedule',
    place: roomText(c.room),
    lecturer: c.lecturer,
    intake_code: c.intake_code,
    group_number: c.group_number,
    change: c.latest_change,
  }))
  const meetings = data.value.meetings.map((m) => ({
    key: `m-${m.id}`,
    kind: 'meeting',
    type: 'meeting',
    title: m.lecturer ? `Meeting with ${m.lecturer}` : 'Meeting',
    subtitle: 'Consultation',
    start: new Date(m.starts_at),
    end: new Date(m.ends_at),
    cancelled: m.status === 'cancelled',
    moved: false,
    place: m.room ? roomText(m.room) : 'Online',
    lecturer: m.lecturer,
    change: null,
  }))
  return [...classes, ...meetings].sort((a, b) => a.start - b.start)
})

// Summary numbers for this week
const stats = computed(() => {
  const active = events.value.filter((e) => e.kind === 'class' && !e.cancelled)
  const hours = active.reduce((sum, e) => sum + (e.end - e.start) / 3600000, 0)
  return {
    classes: active.length,
    hours: Math.round(hours * 10) / 10,
    moved: events.value.filter((e) => e.moved).length,
    cancelled: events.value.filter((e) => e.cancelled).length,
  }
})

const nextUp = computed(() => {
  const now = new Date()
  return events.value.find((e) => !e.cancelled && e.end > now) || null
})
const nextUpLabel = computed(() => {
  const e = nextUp.value
  if (!e) return ''
  const now = new Date()
  if (e.start <= now) return 'Happening now'
  const minutes = Math.round((e.start - now) / 60000)
  if (minutes < 60) return `Starts in ${minutes} min`
  if (e.start.toDateString() === now.toDateString()) return `Today at ${fmtTime(e.start)}`
  return fmtDateTime(e.start)
})

const recentChanges = computed(() => (data.value?.recent_changes || []).map((c) => ({
  ...c,
  when: new Date(c.current_starts_at),
  old: c.old_starts_at ? new Date(c.old_starts_at) : null,
  ago: timeAgo(new Date(c.created_at)),
})))

function openChange(change) {
  const match = events.value.find((e) => e.key === `c-${change.class_session_id}`)
  if (match) selected.value = match
  else goTo(change.when)
}

const firstName = computed(() => (data.value?.student.full_name || '').split(' ')[0])
const greeting = computed(() => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
})
</script>

<template>
  <div class="sp">
    <div class="page">
      <!-- Problem banners -->
      <div v-if="!hasCode" class="banner bad" role="alert">
        <span>Your account is not linked to a student record yet, so there is no timetable to show. Please ask the admin to link your account.</span>
      </div>
      <div v-if="error" :class="['banner', error.backendDown ? 'warn' : 'bad']" role="alert">
        <span>{{ error.message }}</span>
        <span class="banner-actions">
          <button class="sp-btn text" type="button" @click="load">Retry</button>
        </span>
      </div>
      <!-- Greeting + summary -->
      <section v-if="data" class="hero">
        <div>
          <h1>{{ greeting }}{{ firstName ? `, ${firstName}` : '' }}</h1>
          <div class="intakes">
            <span v-for="m in data.student.intakes" :key="m.intake_id" class="chip">{{ m.intake_code }} · Group {{ m.group_number }}</span>
            <span v-if="!data.student.intakes.length" class="chip muted">No intake assigned yet</span>
          </div>
        </div>
        <div class="stats">
          <div class="stat blue"><strong>{{ stats.classes }}</strong><span>classes</span></div>
          <div class="stat green"><strong>{{ stats.hours }}</strong><span>hours</span></div>
          <div class="stat yellow"><strong>{{ stats.moved }}</strong><span>rescheduled</span></div>
          <div class="stat red"><strong>{{ stats.cancelled }}</strong><span>cancelled</span></div>
        </div>
      </section>

      <!-- Week toolbar -->
      <div class="toolbar">
        <button class="sp-btn" type="button" :disabled="isThisWeek" @click="goToday">Today</button>
        <button class="sp-icon-btn" type="button" aria-label="Previous week" @click="shiftWeek(-1)">‹</button>
        <button class="sp-icon-btn" type="button" aria-label="Next week" @click="shiftWeek(1)">›</button>
        <h2 class="range">{{ fmtWeekRange(weekStart) }}</h2>
        <input v-model="dateInput" class="date-pick" type="date" aria-label="Jump to date" />
        <span v-if="loading" class="spinner" aria-label="Loading"></span>
        <div class="toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" :aria-selected="view === 'week'" :class="{ on: view === 'week' }" @click="view = 'week'">Week</button>
          <button type="button" role="tab" :aria-selected="view === 'list'" :class="{ on: view === 'list' }" @click="view = 'list'">List</button>
        </div>
      </div>

      <div class="layout">
        <div class="main-col">
          <WeekTimetable v-if="view === 'week'" :week-start="weekStart" :events="events" @select="selected = $event" />
          <AgendaList v-else :week-start="weekStart" :events="events" @select="selected = $event" />
          <p v-if="data && !events.length && !loading" class="empty">No classes scheduled this week.</p>
        </div>

        <aside class="side">
          <section class="card next" v-if="data">
            <h3>Up next</h3>
            <button v-if="nextUp" type="button" :class="['next-item', `type-${nextUp.type}`]" @click="selected = nextUp">
              <span class="when">{{ nextUpLabel }}</span>
              <strong>{{ nextUp.title }}</strong>
              <span class="meta">{{ fmtTime(nextUp.start) }} – {{ fmtTime(nextUp.end) }} · {{ nextUp.place }}</span>
            </button>
            <p v-else class="muted-text">{{ isThisWeek ? 'No more classes this week.' : 'Nothing upcoming in this week.' }}</p>
          </section>

          <section class="card" v-if="data">
            <h3>Schedule changes <span v-if="recentChanges.length" class="count">{{ recentChanges.length }}</span></h3>
            <p class="hint">Cancelled or rescheduled in the last 14 days</p>
            <p v-if="!recentChanges.length" class="muted-text">No recent changes. Your timetable is up to date.</p>
            <ul class="changes">
              <li v-for="c in recentChanges" :key="c.class_session_id + c.created_at">
                <button type="button" :class="['change', c.action]" @click="openChange(c)">
                  <span class="icon" aria-hidden="true">{{ c.action === 'cancel' ? '✕' : '↻' }}</span>
                  <span class="body">
                    <strong>{{ c.course_name }}</strong>
                    <span v-if="c.action === 'cancel'">Cancelled · {{ fmtDateTime(c.old || c.when) }}</span>
                    <span v-else>
                      <s v-if="c.old">{{ fmtDateTime(c.old) }}</s> → {{ fmtDateTime(c.when) }}
                    </span>
                    <small>{{ c.ago }}<template v-if="c.reason"> · {{ c.reason }}</template></small>
                  </span>
                </button>
              </li>
            </ul>
          </section>

          <section class="card legend">
            <h3>Legend</h3>
            <span class="type-lecture"><i></i>Lecture</span>
            <span class="type-tutorial"><i></i>Tutorial</span>
            <span class="type-lab"><i></i>Lab</span>
            <span class="type-meeting"><i class="dashed"></i>Meeting</span>
            <span class="is-cancelled"><i></i>Cancelled</span>
          </section>
        </aside>
      </div>
    </div>

    <SessionDialog v-if="selected" :key="selected.key" :event="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
/* Page */
.page { max-width: 1440px; margin: 0 auto; padding: 20px 24px 40px; }
.banner {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  padding: 10px 12px 10px 16px; border-radius: 10px; margin-bottom: 16px;
}
.banner.warn { background: var(--yellow-soft); color: #7a4100; }
.banner.bad { background: var(--red-soft); color: var(--red-text); }
.banner.info { background: var(--blue-soft); color: #174ea6; }
.banner-actions { display: flex; gap: 6px; }

.hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap; margin: 8px 0 20px; }
.hero h1 { font-size: 28px; font-weight: 400; }
.intakes { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.chip {
  display: inline-flex; align-items: center; height: 28px; padding: 0 12px;
  border: 1px solid var(--grey-300); border-radius: 14px; font-size: 13px; color: var(--grey-700);
}
.chip.muted { border-style: dashed; }
.stats { display: flex; gap: 10px; }
.stat {
  min-width: 92px; padding: 10px 14px; border-radius: 12px; display: flex; flex-direction: column;
}
.stat strong { font-size: 24px; font-weight: 500; line-height: 1.1; }
.stat span { font-size: 12px; }
.stat.blue { background: var(--blue-soft); color: var(--blue-text); }
.stat.green { background: var(--green-soft); color: var(--green-text); }
.stat.yellow { background: var(--yellow-soft); color: var(--yellow-text); }
.stat.red { background: var(--red-soft); color: var(--red-text); }

.toolbar { display: flex; align-items: center; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
.toolbar .sp-icon-btn { font-size: 26px; }
.range { font-size: 20px; font-weight: 400; margin: 0 8px !important; }
.date-pick {
  height: 36px; padding: 0 10px; border: 1px solid var(--grey-300); border-radius: 18px;
  font: inherit; color: var(--grey-700); background: #fff;
}
.spinner {
  width: 18px; height: 18px; margin-left: 6px; border-radius: 50%;
  border: 2px solid var(--blue-soft); border-top-color: var(--blue); animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.toggle { margin-left: auto; display: flex; border: 1px solid var(--grey-300); border-radius: 18px; overflow: hidden; }
.toggle button {
  height: 34px; padding: 0 16px; border: 0; background: #fff; font: inherit; font-weight: 500; color: var(--grey-700);
}
.toggle button + button { border-left: 1px solid var(--grey-300); }
.toggle button.on { background: var(--blue-soft); color: var(--blue-text); }

.layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; align-items: start; }
.empty { text-align: center; color: var(--grey-700); margin-top: 12px; }

/* Side cards */
.side { display: flex; flex-direction: column; gap: 16px; }
.card { border: 1px solid var(--grey-300); border-radius: var(--radius); padding: 16px; background: #fff; }
.card h3 { font-size: 16px; font-weight: 500; display: flex; align-items: center; gap: 8px; }
.count {
  display: inline-grid; place-items: center; min-width: 22px; height: 22px; padding: 0 6px;
  border-radius: 11px; background: var(--red); color: #fff; font-size: 12px;
}
.hint { margin: 2px 0 10px; font-size: 12px; color: var(--grey-700); }
.muted-text { margin: 8px 0 0; color: var(--grey-700); font-size: 13px; }

.next-item {
  margin-top: 10px; width: 100%; display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  padding: 12px 14px; border: 0; border-left: 4px solid var(--c); border-radius: 8px;
  background: var(--c-soft); text-align: left; font: inherit; color: var(--grey-900);
}
.next-item .when { font-size: 12px; font-weight: 500; color: var(--c-text); text-transform: uppercase; letter-spacing: .5px; }
.next-item strong { font-weight: 500; font-size: 15px; }
.next-item .meta { font-size: 13px; color: var(--grey-700); }

.changes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.change {
  width: 100%; display: flex; gap: 12px; padding: 10px 8px; border: 0; border-radius: 8px;
  background: transparent; text-align: left; font: inherit; color: inherit;
}
.change:hover { background: var(--grey-50); }
.change .icon {
  flex-shrink: 0; display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%;
  font-size: 14px; font-weight: 700;
}
.change.cancel .icon { background: var(--red-soft); color: var(--red); }
.change.reschedule .icon { background: var(--yellow-soft); color: var(--yellow-text); }
.change .body { display: flex; flex-direction: column; font-size: 13px; min-width: 0; }
.change .body strong { font-weight: 500; font-size: 14px; }
.change .body small { color: var(--grey-700); font-size: 12px; }
.change s { color: var(--grey-500); }

.legend { display: flex; flex-wrap: wrap; gap: 8px 14px; }
.legend h3 { width: 100%; }
.legend span { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--grey-700); }
.legend i { width: 12px; height: 12px; border-radius: 3px; background: var(--c-soft); border-left: 4px solid var(--c); }
.legend i.dashed { border: 1px dashed var(--c); border-left: 4px solid var(--c); background: #fff; }

@media (max-width: 1100px) {
  .layout { grid-template-columns: 1fr; }
  .side { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
}
@media (max-width: 640px) {
  .page { padding: 12px 12px 32px; }
  .stats { width: 100%; }
  .stat { flex: 1; min-width: 0; padding: 8px 10px; }
  .date-pick { display: none; }
}
</style>
