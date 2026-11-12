<script setup>
// Right panel of /admin/schedule: turns a generate response into something people can review
// (outcome, figures, calendar or list, and any classes that could not be placed).
import { computed, ref, watch } from 'vue'
import { eventLines, layoutEvents, todayIso, weekDays } from './roomCalendar'
import {
  FILTER_KINDS, filterChoices, groupChoices, matchesFilter, matchesGroup, outcome, placementRows, rowsByDay, summaryCards,
  weekTitle,
} from './schedulePreview'
import WeekGrid from './WeekGrid.vue'

const props = defineProps({
  phase: { type: String, default: 'idle' }, // idle | generating | result
  preview: { type: Object, default: null },
  error: { type: Object, default: null }, // { title, message, advice, requestId }
  saved: { type: Object, default: null }, // { count, by, week }
  elapsed: { type: Number, default: 0 },
  outdated: Boolean,
  names: { type: Object, required: true }, // { intakes: Map(id -> code), lecturers: Map(id -> name) }
})

const view = ref('calendar')
const kind = ref('intake')
const value = ref('all')
const group = ref('all') // only used when showing one intake

const rows = computed(() => (props.preview ? placementRows(props.preview, props.names) : []))
const result = computed(() => {
  if (!props.preview) return null
  if (!props.saved) return outcome(props.preview)
  const count = `${props.saved.count} ${props.saved.count === 1 ? 'class is' : 'classes are'}`
  return {
    tone: 'success',
    title: `Scheduled: ${count} now live`,
    text: `Saved by ${props.saved.by}. Students, lecturers and administrators now see these classes in their timetables.`,
  }
})
const cards = computed(() => (props.preview ? summaryCards(props.preview) : []))
const choices = computed(() => filterChoices(rows.value, kind.value))
const groups = computed(() => (kind.value === 'intake' ? groupChoices(rows.value, value.value) : []))
const intakeCount = computed(() => groups.value.reduce((sum, item) => sum + item.count, 0))
const shownRows = computed(() => rows.value.filter((row) => matchesFilter(row, kind.value, value.value)
  && (kind.value !== 'intake' || matchesGroup(row, group.value))))
const days = computed(() => (props.preview ? weekDays(props.preview.week_start, todayIso()) : []))
const layout = computed(() => layoutEvents(shownRows.value, props.preview?.week_start || '2000-01-03'))
const byDay = computed(() => (props.preview ? rowsByDay(shownRows.value, props.preview.week_start) : []))
const intakeCodes = computed(() => (props.preview?.intake_ids || []).map((id) => props.names.intakes.get(String(id)) || 'Unknown intake'))
const otherDiagnostics = computed(() => (props.preview && !props.preview.has_solution && !props.preview.unplaced?.length
  ? props.preview.diagnostics.map((item) => item.detail) : []))
const clock = computed(() => `${Math.floor(props.elapsed / 60)}:${String(props.elapsed % 60).padStart(2, '0')}`)

// A new preview starts on its first intake (several intakes in one calendar would crowd it).
watch(() => props.preview, (preview) => {
  if (!preview) return
  kind.value = 'intake'
  value.value = choices.value.length > 1 ? choices.value[0].value : 'all'
  group.value = 'all'
})

// Picking another intake (or another kind of filter) shows all its groups again.
watch([kind, value], () => { group.value = 'all' })

const lines = (event) => eventLines(event.endMinutes - event.startMinutes)
const third = (event) => {
  if (kind.value === 'room') return `${event.intake_code} · G${event.group_number}`
  // One intake with all its groups: say which group each class is for.
  if (kind.value === 'intake' && value.value !== 'all' && group.value === 'all') return `G${event.group_number} · ${event.room_name}`
  return event.room_name
}
const describe = (event) => [
  `${event.course_code} ${event.course_type}`, event.course_name, event.time, `${event.intake_code} · Group ${event.group_number}`,
  `${event.room_name} (${event.room_building})`, event.lecturer_name, `${event.student_count} students`,
].join(' · ')
const dayTitle = (iso) => days.value.find((day) => day.iso === iso)?.label || iso
</script>

<template>
  <div class="pp">
    <div v-if="error" class="pp-banner pp-error" role="alert">
      <strong>{{ error.title }}</strong> {{ error.message }}
      <span v-if="error.advice"> {{ error.advice }}</span>
      <small v-if="error.requestId" class="pp-request">Request ID: {{ error.requestId }}</small>
    </div>

    <div v-if="phase === 'generating'" class="pp-empty" aria-busy="true">
      <span class="pp-spinner" aria-hidden="true"></span>
      <h2>Generating the preview… <span class="pp-clock">{{ clock }}</span></h2>
      <p>Placing every pending class of the selected intakes while keeping existing classes fixed. This can take up to about five minutes.</p>
    </div>

    <div v-else-if="!preview" class="pp-empty">
      <span class="pp-dots" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <h2>No preview yet</h2>
      <p>Choose a teaching week and tick one or more intakes on the left, then select <strong>Generate Preview</strong>. Nothing is saved until you schedule the preview.</p>
    </div>

    <template v-else>
      <div v-if="outdated" class="pp-banner pp-warning" role="status">
        The week or intake selection has changed since this preview. Regenerate it to schedule the new selection.
      </div>

      <section class="pp-outcome" :class="`is-${result.tone}`" aria-live="polite">
        <p class="pp-eyebrow">{{ weekTitle(preview.week_start) }} · {{ intakeCodes.join(', ') }}</p>
        <h2>{{ result.title }}</h2>
        <p>{{ result.text }}</p>
      </section>

      <ul v-if="preview.required_count" class="pp-cards" aria-label="Preview figures">
        <li v-for="card in cards" :key="card.label">
          <span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.hint }}</small>
        </li>
      </ul>

      <section v-if="preview.unplaced?.length" class="pp-section" aria-labelledby="pp-unplaced">
        <h3 id="pp-unplaced">Classes that cannot be placed</h3>
        <ul class="pp-unplaced">
          <li v-for="item in preview.unplaced" :key="item.occurrence_id">
            <strong>{{ item.course_code }} · {{ item.course_type }}</strong> {{ item.course_name }}
            <span class="pp-muted">· {{ names.intakes.get(String(item.intake_id)) || 'Unknown intake' }} · Group {{ item.group_number }}</span>
            <ul><li v-for="(reason, i) in item.reasons" :key="i">{{ reason }}</li></ul>
          </li>
        </ul>
      </section>
      <section v-else-if="otherDiagnostics.length" class="pp-section" aria-labelledby="pp-why">
        <h3 id="pp-why">Details</h3>
        <ul class="pp-plain"><li v-for="(text, i) in otherDiagnostics" :key="i">{{ text }}</li></ul>
      </section>

      <section v-if="rows.length" class="pp-section" aria-labelledby="pp-classes">
        <div class="pp-toolbar">
          <h3 id="pp-classes">Proposed classes</h3>
          <div class="pp-controls">
            <label>Show
              <select v-model="kind" aria-label="Show classes by" @change="value = 'all'">
                <option v-for="option in FILTER_KINDS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <select v-model="value" :aria-label="`Which ${kind}`">
              <option value="all">All ({{ rows.length }})</option>
              <option v-for="choice in choices" :key="choice.value" :value="choice.value">{{ choice.label }} ({{ choice.count }})</option>
            </select>
            <label v-if="kind === 'intake'">Group
              <select v-model="group" aria-label="Which group of the intake" :disabled="value === 'all'"
                      :title="value === 'all' ? 'Choose an intake first' : ''">
                <option value="all">All groups{{ value === 'all' ? '' : ` (${intakeCount})` }}</option>
                <option v-for="item in groups" :key="item.value" :value="item.value">{{ item.label }} ({{ item.count }})</option>
              </select>
            </label>
            <div class="pp-toggle" role="group" aria-label="View">
              <button type="button" :aria-pressed="view === 'calendar'" @click="view = 'calendar'">Calendar</button>
              <button type="button" :aria-pressed="view === 'list'" @click="view = 'list'">List</button>
            </div>
          </div>
        </div>
        <p class="pp-muted pp-note">New classes only, in campus time. Existing bookings are not shown but were kept fixed.</p>

        <WeekGrid v-if="view === 'calendar'" :days="days" :layout="layout" :describe="describe">
          <template #event="{ event }">
            <strong>{{ event.course_code }}</strong>
            <span>{{ event.time }}</span>
            <span v-if="lines(event) >= 3">{{ third(event) }}</span>
            <span v-if="lines(event) >= 4">{{ event.lecturer_name }}</span>
          </template>
        </WeekGrid>

        <div v-else class="pp-list">
          <section v-for="day in byDay" :key="day.iso">
            <h4>{{ dayTitle(day.iso) }}</h4>
            <div class="pp-table-wrap">
              <table>
                <thead><tr><th scope="col">Time</th><th scope="col">Class</th><th scope="col">Intake</th><th scope="col">Room</th><th scope="col">Lecturer</th><th scope="col">Students</th></tr></thead>
                <tbody>
                  <tr v-for="row in day.rows" :key="row.occurrence_id">
                    <td class="pp-nowrap">{{ row.time }}</td>
                    <td><strong>{{ row.course_code }}</strong> · {{ row.course_type }}<small>{{ row.course_name }}</small></td>
                    <td>{{ row.intake_code }}<small>Group {{ row.group_number }}</small></td>
                    <td>{{ row.room_name }}<small>{{ row.room_building }}</small></td>
                    <td>{{ row.lecturer_name }}</td>
                    <td>{{ row.student_count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <p v-if="!byDay.length" class="pp-muted">No classes for this selection.</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.pp { display: flex; flex-direction: column; gap: 16px; color: #202124; }
.pp h2, .pp h3, .pp h4 { margin: 0; }
.pp button, .pp select { font: inherit; }
.pp-muted { color: #5f6368; }
.pp-banner { padding: 12px 14px; border-radius: 10px; font-size: 14px; line-height: 1.5; }
.pp-error { background: #fce8e6; color: #a50e0e; }
.pp-warning { background: #fef7e0; color: #7a4f01; }
.pp-request { display: block; margin-top: 4px; opacity: .85; }

.pp-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; margin: auto; padding: 56px 24px; max-width: 460px; text-align: center; }
.pp-empty h2 { font-size: 20px; font-weight: 500; }
.pp-empty p { margin: 0; color: #5f6368; line-height: 1.5; }
.pp-dots { display: flex; gap: 6px; margin-bottom: 6px; }
.pp-dots i { width: 12px; height: 12px; border-radius: 50%; }
.pp-dots i:nth-child(1) { background: #4285f4; } .pp-dots i:nth-child(2) { background: #ea4335; }
.pp-dots i:nth-child(3) { background: #fbbc04; } .pp-dots i:nth-child(4) { background: #34a853; }
.pp-spinner { width: 36px; height: 36px; border: 4px solid #e8f0fe; border-top-color: #1a73e8; border-radius: 50%; animation: pp-spin 1s linear infinite; }
.pp-clock { color: #1a73e8; font-variant-numeric: tabular-nums; }
@keyframes pp-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .pp-spinner { animation-duration: 3s; } }

.pp-outcome { padding: 16px 18px; border: 1px solid #e2e7ef; border-left: 6px solid #9aa0a6; border-radius: 12px; background: #fff; }
.pp-outcome h2 { font-size: 20px; font-weight: 500; margin: 2px 0 6px; }
.pp-outcome p { margin: 0; line-height: 1.5; color: #3c4043; }
.pp-outcome .pp-eyebrow { color: #5f6368; font-size: 12px; font-weight: 600; letter-spacing: .04em; }
.pp-outcome.is-success { border-left-color: #34a853; }
.pp-outcome.is-error { border-left-color: #ea4335; }
.pp-outcome.is-warning { border-left-color: #fbbc04; }

.pp-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
.pp-cards li { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; border: 1px solid #e2e7ef; border-radius: 10px; background: #fff; }
.pp-cards span { color: #5f6368; font-size: 12px; font-weight: 600; }
.pp-cards strong { font-size: 20px; font-weight: 500; }
.pp-cards small { color: #5f6368; font-size: 12px; }

.pp-section { display: flex; flex-direction: column; gap: 10px; }
.pp-section h3 { font-size: 16px; font-weight: 600; }
.pp-unplaced, .pp-plain { margin: 0; padding-left: 18px; line-height: 1.5; }
.pp-unplaced > li { margin-bottom: 8px; }
.pp-unplaced ul { margin: 2px 0 0; padding-left: 18px; color: #5f6368; font-size: 13px; }

.pp-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.pp-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pp-controls label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: #3c4043; }
.pp-controls select { max-width: 260px; padding: 7px 10px; border: 1px solid #cdd5e0; border-radius: 8px; background: #fff; color: #202124; }
.pp-controls select:disabled { background: #f1f3f4; color: #80868b; cursor: not-allowed; }
.pp-toggle { display: inline-flex; border: 1px solid #dadce0; border-radius: 8px; overflow: hidden; }
.pp-toggle button { padding: 7px 14px; border: 0; background: #fff; color: #3c4043; cursor: pointer; }
.pp-toggle button + button { border-left: 1px solid #dadce0; }
.pp-toggle button[aria-pressed="true"] { background: #e8f0fe; color: #1967d2; font-weight: 600; }
.pp-note { margin: -4px 0 0; font-size: 13px; }

.pp-list { display: flex; flex-direction: column; gap: 16px; }
.pp-list h4 { margin-bottom: 6px; font-size: 14px; font-weight: 600; color: #3c4043; }
.pp-table-wrap { overflow-x: auto; border: 1px solid #e2e7ef; border-radius: 10px; }
.pp-list table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pp-list th { padding: 8px 10px; background: #f8f9fa; color: #5f6368; font-weight: 600; text-align: left; white-space: nowrap; }
.pp-list td { padding: 8px 10px; border-top: 1px solid #e2e7ef; vertical-align: top; }
.pp-list td small { display: block; color: #5f6368; }
.pp-nowrap { white-space: nowrap; }
button:focus-visible, select:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
</style>
