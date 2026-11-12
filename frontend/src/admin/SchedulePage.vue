<script setup>
// /admin/schedule: generate a timetable preview for the selected intakes and week, review it, and
// schedule (save) it. Opened from Admin > Timetable > Schedule Class.
// Left: week + intake checkboxes. Right: the preview. The divider between them can be dragged
// (or moved with the arrow keys). Previews are not stored: leaving the page discards one.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import IntakePanel from './IntakePanel.vue'
import PreviewPanel from './PreviewPanel.vue'
import ScheduleConfirmDialog from './ScheduleConfirmDialog.vue'
import { PAUSED, generatePreview, listIntakes, listLecturers, savePreview, stopPreview } from './scheduleApi'
import { mondayOf, todayIso } from './roomCalendar'
import { errorAdvice, keepsPreview, newRunId, selectionKey, weekTitle } from './schedulePreview'

// ---------- data ----------
const week = ref(mondayOf(todayIso()))
const intakes = ref([])
const intakesLoading = ref(true)
const intakesError = ref('')
const lecturerNames = ref(new Map())
const selected = ref([])

// ---------- preview state ----------
const phase = ref('idle') // idle | generating | result
const preview = ref(null)
const previewKey = ref('')
const usable = ref(false) // false once a save attempt made this preview untrustworthy
const saved = ref(null) // { count, by, week } after a successful save
const error = ref(null)
const elapsed = ref(0)
const confirmOpen = ref(false)
const saving = ref(false)
const pausing = ref(false)
const notice = ref('') // a status line, e.g. after Pause
// The running Generate press: { id, controller, giveUp }. Pause stops this one only.
let run = null
// After the server agrees to stop, how long to wait for its answer before giving up on it.
const PAUSE_WAIT_MS = 15000
let timer = null

const names = computed(() => ({
  intakes: new Map(intakes.value.map((intake) => [String(intake.id), intake.intake_code])),
  lecturers: lecturerNames.value,
}))
const busy = computed(() => phase.value === 'generating' || saving.value)
const outdated = computed(() => Boolean(preview.value) && !saved.value && selectionKey(week.value, selected.value) !== previewKey.value)
const reviewing = computed(() => Boolean(preview.value) && !saved.value) // "Regenerate" + "Schedule with preview"
const canSchedule = computed(() => reviewing.value && preview.value.has_solution && usable.value && !outdated.value && !busy.value)
const scheduleHint = computed(() => {
  if (!reviewing.value || canSchedule.value || busy.value) return ''
  if (outdated.value) return 'The selection changed: regenerate first.'
  if (!preview.value.has_solution) return 'Only a complete timetable can be scheduled.'
  return 'Regenerate the preview before scheduling.'
})
const selectedCodes = computed(() => (preview.value?.intake_ids || []).map((id) => names.value.intakes.get(String(id)) || 'Unknown intake'))

async function loadData() {
  intakesLoading.value = true
  intakesError.value = ''
  try {
    intakes.value = await listIntakes()
  } catch (e) {
    intakesError.value = e.message
  } finally {
    intakesLoading.value = false
  }
  try {
    lecturerNames.value = new Map((await listLecturers()).map((row) => [String(row.id), row.full_name]))
  } catch {
    // Names are a convenience; the preview still works with "Unknown lecturer".
  }
}

// Selection changes read and write this page's own list, so they apply immediately and in order.
function toggleIntake(id, on) {
  const next = new Set(selected.value)
  if (on) next.add(id)
  else next.delete(id)
  selected.value = [...next]
}
function addIntakes(ids) {
  selected.value = [...new Set([...selected.value, ...ids])]
}

function problem(e, title) {
  return { title, message: e.message, advice: errorAdvice(e.code), requestId: e.requestId || '' }
}

async function generate() {
  if (!selected.value.length || busy.value) return
  const key = selectionKey(week.value, selected.value)
  const chosenWeek = week.value
  const chosenIntakes = [...selected.value]
  const mine = { id: newRunId(), controller: new AbortController(), giveUp: null }
  run = mine
  phase.value = 'generating'
  error.value = null
  notice.value = ''
  saved.value = null
  elapsed.value = 0
  timer = setInterval(() => { elapsed.value += 1 }, 1000)
  try {
    const { data } = await generatePreview(chosenWeek, chosenIntakes, { runId: mine.id, signal: mine.controller.signal })
    if (data.stopped && !data.has_solution && preview.value) {
      // Paused before a new timetable was found: keep showing the previous one.
      notice.value = 'Scheduling paused before a new timetable was found. Nothing was saved; the previous preview is still shown.'
    } else {
      preview.value = data
      previewKey.value = key
      usable.value = true
    }
  } catch (e) {
    if (e.code === PAUSED) {
      notice.value = preview.value
        ? 'Scheduling paused. Nothing was saved; the previous preview is still shown.'
        : 'Scheduling paused. Nothing was saved. Generate the preview again to start over.'
    } else {
      error.value = problem(e, 'The preview could not be generated.')
    }
  } finally {
    clearTimeout(mine.giveUp)
    if (run === mine) run = null
    pausing.value = false
    clearInterval(timer)
    timer = null
    phase.value = preview.value ? 'result' : 'idle'
  }
}

// Pause: the server stops the search and answers the Generate request with the best timetable
// found so far (or none). If this server is not running it (another instance, or the request
// failed), the page simply stops waiting; nothing is ever saved by generating.
async function pause() {
  const mine = run
  if (!mine || pausing.value) return
  pausing.value = true
  let accepted = false
  try {
    accepted = (await stopPreview(mine.id)).data?.stopped === true
  } catch { /* stop waiting below */ }
  if (run !== mine) return // it finished meanwhile
  if (!accepted) {
    mine.controller.abort()
    return
  }
  mine.giveUp = setTimeout(() => mine.controller.abort(), PAUSE_WAIT_MS)
}

async function confirmSchedule() {
  if (!canSchedule.value) return
  saving.value = true
  error.value = null
  notice.value = ''
  try {
    const { data } = await savePreview(preview.value)
    saved.value = { count: data.saved_count, by: data.saved_by, week: weekTitle(preview.value.week_start) }
    confirmOpen.value = false
  } catch (e) {
    confirmOpen.value = false
    if (!keepsPreview(e.code)) usable.value = false // stale, rejected or unknown outcome: regenerate first
    error.value = problem(e, 'The timetable was not scheduled.')
  } finally {
    saving.value = false
  }
}

// Leaving the page discards an unsaved complete preview: ask first.
function warnBeforeLeaving(event) {
  if (reviewing.value && preview.value.has_solution) {
    event.preventDefault()
    event.returnValue = ''
  }
}

// ---------- resizable panels ----------
const STORE_KEY = 'sclass.schedule.leftWidth'
const MIN_LEFT = 260
const MIN_RIGHT = 420
const split = ref(null)
const dragging = ref(false)
const leftWidth = ref(readWidth())

function readWidth() {
  try {
    const value = Number(localStorage.getItem(STORE_KEY))
    return Number.isFinite(value) && value >= MIN_LEFT ? value : 340
  } catch {
    return 340
  }
}
function maxLeft() {
  return Math.max(MIN_LEFT, (split.value?.clientWidth || 1200) - MIN_RIGHT)
}
function setWidth(px) {
  leftWidth.value = Math.round(Math.min(Math.max(px, MIN_LEFT), maxLeft()))
}
function saveWidth() {
  try { localStorage.setItem(STORE_KEY, String(leftWidth.value)) } catch { /* storage blocked: keep it for this visit */ }
}
function startDrag(event) {
  if (event.button !== 0) return
  event.preventDefault()
  const left = split.value.getBoundingClientRect().left
  dragging.value = true
  const move = (e) => setWidth(e.clientX - left)
  const stop = () => {
    dragging.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    saveWidth()
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
}
function resizeWithKeys(event) {
  const steps = { ArrowLeft: -24, ArrowRight: 24 }
  if (event.key in steps) setWidth(leftWidth.value + steps[event.key])
  else if (event.key === 'Home') setWidth(MIN_LEFT)
  else if (event.key === 'End') setWidth(maxLeft())
  else return
  event.preventDefault()
  saveWidth()
}
function resetWidth() {
  setWidth(340)
  saveWidth()
}

onMounted(() => {
  setWidth(leftWidth.value)
  loadData()
  window.addEventListener('beforeunload', warnBeforeLeaving)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('beforeunload', warnBeforeLeaving)
})
</script>

<template>
  <main class="sp" :class="{ 'is-dragging': dragging }">
    <header class="sp-head">
      <div class="sp-titles">
        <p class="sp-eyebrow"><a href="/admin">SCLASS / ADMIN</a> / SCHEDULE</p>
        <h1>Schedule classes</h1>
        <p class="sp-sub">Generate a timetable for the selected intakes, review it, then publish it.</p>
      </div>
      <div class="sp-actions">
        <span v-if="scheduleHint" class="sp-hint" role="status">{{ scheduleHint }}</span>
        <button
          type="button" class="sp-btn sp-green" :disabled="!selected.length || busy"
          :title="selected.length ? '' : 'Tick at least one intake first'" @click="generate"
        >
          {{ phase === 'generating' ? 'Generating…' : reviewing ? 'Regenerate Preview' : 'Generate Preview' }}
        </button>
        <button
          v-if="phase === 'generating'" type="button" class="sp-btn sp-amber" :disabled="pausing"
          title="Stop the search now and show the best timetable found so far, if any" @click="pause"
        >
          {{ pausing ? 'Pausing…' : 'Pause' }}
        </button>
        <button v-if="reviewing" type="button" class="sp-btn sp-blue" :disabled="!canSchedule" @click="confirmOpen = true">
          Schedule with preview
        </button>
      </div>
    </header>

    <div ref="split" class="sp-split" :style="{ '--left': `${leftWidth}px` }">
      <aside class="sp-left" aria-label="Week and intakes">
        <IntakePanel
          v-model:week="week" :selected="selected" :intakes="intakes" :loading="intakesLoading"
          :error="intakesError" :disabled="busy" @retry="loadData"
          @toggle="toggleIntake" @add="addIntakes" @clear="selected = []"
        />
      </aside>
      <div
        class="sp-divider" role="separator" aria-orientation="vertical" aria-label="Resize the panels" tabindex="0"
        :aria-valuenow="leftWidth" :aria-valuemin="MIN_LEFT" :aria-valuemax="maxLeft()"
        title="Drag to resize · double-click to reset" @pointerdown="startDrag" @keydown="resizeWithKeys" @dblclick="resetWidth"
      ><span aria-hidden="true"></span></div>
      <section class="sp-right" aria-label="Preview">
        <PreviewPanel
          :phase="phase" :preview="preview" :error="error" :saved="saved" :elapsed="elapsed"
          :outdated="outdated" :names="names" :pausing="pausing" :notice="notice"
        />
      </section>
    </div>

    <ScheduleConfirmDialog
      :open="confirmOpen" :saving="saving" :count="preview?.placements.length || 0"
      :week="preview ? weekTitle(preview.week_start) : ''" :intakes="selectedCodes"
      @confirm="confirmSchedule" @cancel="confirmOpen = false"
    />
  </main>
</template>

<style scoped>
/* Full width: overrides the global `main { max-width; padding; margin }` page rule in style.css. */
.sp {
  display: flex; flex-direction: column; height: calc(100dvh - 34px); min-height: 520px; box-sizing: border-box;
  max-width: none; margin: 0; padding: 0; background: #fff; color: #202124;
}
.sp.is-dragging { cursor: col-resize; user-select: none; }
.sp-head {
  display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap;
  padding: 18px 24px 16px; border-bottom: 1px solid #e2e7ef;
}
.sp-eyebrow { margin: 0 0 4px; color: #5f6368; font-size: 12px; font-weight: 600; letter-spacing: .08em; }
.sp-eyebrow a { color: inherit; text-decoration: none; }
.sp-eyebrow a:hover { color: #1a73e8; text-decoration: underline; }
.sp h1 { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -.5px; }
.sp-sub { margin: 4px 0 0; color: #5f6368; font-size: 14px; }
.sp-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sp-hint { color: #5f6368; font-size: 13px; }
.sp-btn {
  padding: 11px 20px; border: 0; border-radius: 8px; color: #fff; font: inherit; font-weight: 600; cursor: pointer;
  box-shadow: 0 1px 2px rgba(60, 64, 67, .3);
}
.sp-btn:disabled { cursor: not-allowed; opacity: .5; box-shadow: none; }
.sp-green { background: #188038; }
.sp-green:hover:not(:disabled) { background: #137333; }
.sp-amber { background: #b45309; }
.sp-amber:hover:not(:disabled) { background: #92400e; }
.sp-blue { background: #1a73e8; }
.sp-blue:hover:not(:disabled) { background: #1765cc; }
.sp-btn:focus-visible, .sp-divider:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }

.sp-split { flex: 1; min-height: 0; display: grid; grid-template-columns: var(--left) 10px minmax(0, 1fr); }
.sp-left, .sp-right { min-height: 0; overflow: auto; padding: 20px 24px; }
.sp-left { background: #fff; padding-right: 16px; }
.sp-right { background: #f8f9fa; }
.sp-divider { position: relative; display: flex; justify-content: center; background: #fff; border-left: 1px solid #e2e7ef; cursor: col-resize; touch-action: none; }
.sp-divider span { position: absolute; top: 50%; width: 4px; height: 44px; margin-top: -22px; border-radius: 2px; background: #dadce0; transition: background .15s; }
.sp-divider:hover span, .sp.is-dragging .sp-divider span, .sp-divider:focus-visible span { background: #1a73e8; }

@media (max-width: 820px) {
  .sp { height: auto; }
  .sp-head { padding: 16px; }
  .sp-actions { width: 100%; }
  .sp-split { display: flex; flex-direction: column; }
  .sp-divider { display: none; }
  .sp-left, .sp-right { overflow: visible; padding: 16px; }
  .sp-left { border-bottom: 1px solid #e2e7ef; }
}
</style>
