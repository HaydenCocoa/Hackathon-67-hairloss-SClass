<script setup>
// Admin > Timetable > Reschedule: move one class to another start time and/or room.
// The backend decides what is free (GET .../availability, the same rules as timetable generation):
// rooms that cannot take the class at the chosen time are greyed out, and start times at which the
// chosen room is not free cannot be picked. Cancel and Save both ask again when something changed.
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { addDays, formatMinutes, todayIso } from './roomCalendar'
import {
  classLabel, classTime, isDirty, isMoved, longDay, moveBody, reschedulable, roomChoice, slotBlock, teachingDays, toMinutes,
} from './reschedule'
import { getAvailability, rescheduleClass } from './scheduleApi'

const props = defineProps({
  open: Boolean,
  sessions: { type: Array, default: () => [] }, // the loaded week's classes (GET /api/admin/timetable rows)
  initialId: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const dialog = ref(null)
const classSelect = ref(null)
const today = ref(todayIso())
const classId = ref('')
const original = ref(null) // { date, start, roomId } of the class as loaded
const form = reactive({ date: '', start: '', roomId: '', reason: '' })
const availability = ref(null)
const loading = ref(false)
const loadError = ref('')
const notice = ref('')
const confirming = ref('') // '' | 'discard' | 'save'
const pendingClassId = ref('') // a class picked while there were unsaved changes
const saving = ref(false)
const saveError = ref('')
let latest = 0

const choices = computed(() => reschedulable(props.sessions))
const session = computed(() => choices.value.find((item) => item.id === classId.value) || null)
const current = computed(() => (session.value ? classTime(session.value) : null))
const days = computed(() => (form.date ? teachingDays(form.date, today.value) : []))
const shown = computed(() => (availability.value?.date === form.date ? availability.value : null))
const slots = computed(() => shown.value?.slots || [])
const rooms = computed(() => (shown.value?.rooms || []).map((room) => ({ ...room, ...roomChoice(room, { start: form.start, availability: shown.value }) })))
const selectedRoom = computed(() => rooms.value.find((room) => room.id === form.roomId) || null)
const dirty = computed(() => isDirty(original.value, form))
const moved = computed(() => isMoved(original.value, form))
const timeChecked = computed(() => shown.value?.selected?.start === form.start ? shown.value.selected : null)
const roomFree = computed(() => Boolean(timeChecked.value?.available_room_ids.includes(form.roomId)))
const newRange = computed(() => (form.start && shown.value
  ? `${formatMinutes(toMinutes(form.start))} – ${formatMinutes(toMinutes(form.start) + shown.value.duration_minutes)}` : ''))
const saveHint = computed(() => {
  if (!moved.value) return form.start ? 'Change the time or the room to save.' : 'Choose a start time.'
  if (loading.value) return 'Checking availability…'
  if (!roomFree.value) return 'The chosen room is not free at this time.'
  if (!form.reason.trim()) return 'Enter a reason for the change.'
  return ''
})
const canSave = computed(() => !saveHint.value && !saving.value)
const prevWeekDisabled = computed(() => addDays(days.value[4]?.iso || form.date, -7) < today.value)

watch(() => props.open, async (open) => {
  await nextTick()
  if (open) {
    today.value = todayIso()
    const first = choices.value.find((item) => item.id === props.initialId) || choices.value[0]
    load(first?.id || '')
    if (!dialog.value.open) dialog.value.showModal()
  } else if (dialog.value?.open) {
    dialog.value.close()
  }
})

function load(id) {
  classId.value = id
  confirming.value = ''
  pendingClassId.value = ''
  notice.value = ''
  saveError.value = ''
  availability.value = null
  if (!session.value) {
    original.value = null
    return
  }
  const time = classTime(session.value)
  original.value = { date: time.date, start: time.start, roomId: session.value.room_id }
  Object.assign(form, { date: time.date, start: time.start, roomId: session.value.room_id, reason: '' })
  check()
}

// Ask the backend which rooms/times are free for the form's date (and start, when chosen).
async function check() {
  const request = ++latest
  loading.value = true
  loadError.value = ''
  try {
    const data = await getAvailability(classId.value, form.date, form.start || undefined)
    if (request !== latest) return null
    availability.value = data
    return data
  } catch (e) {
    if (request === latest) loadError.value = e.message
    return null
  } finally {
    if (request === latest) loading.value = false
  }
}

function pickDate(iso) {
  if (iso === form.date || iso < today.value) return
  form.date = iso
  form.start = iso === original.value.date ? original.value.start : '' // a new day starts without a time
  notice.value = ''
  check()
}

function moveWeek(weeks) {
  const target = addDays(form.date, weeks * 7)
  pickDate(target < today.value ? today.value : target)
}

async function pickSlot(slot) {
  if (slotBlock(slot, form.roomId)) return
  if (form.start === slot.start) { // clicking the chosen time again clears it
    form.start = ''
    return
  }
  const previous = form.start
  form.start = slot.start
  notice.value = ''
  const data = await check()
  const checked = data?.selected
  if (checked && checked.start === slot.start && !checked.available_room_ids.includes(form.roomId)) {
    // Booked by someone else since the grid was loaded: keep the previous time.
    notice.value = `${selectedRoom.value?.name || 'The selected room'} is no longer free at ${formatMinutes(toMinutes(slot.start))}. Choose another time or room.`
    form.start = previous
    check()
  }
}

function switchClass(event) {
  const id = event.target.value
  if (dirty.value) {
    pendingClassId.value = id
    confirming.value = 'discard'
    event.target.value = classId.value // keep showing the current class until the change is confirmed
  } else {
    load(id)
  }
}

function requestClose() {
  if (saving.value) return
  if (dirty.value) confirming.value = 'discard'
  else emit('close')
}

function discard() {
  if (pendingClassId.value) {
    load(pendingClassId.value)
    nextTick(() => { if (classSelect.value) classSelect.value.value = classId.value })
  } else {
    confirming.value = ''
    emit('close')
  }
}

async function publish() {
  saving.value = true
  saveError.value = ''
  const moving = session.value
  try {
    const { data } = await rescheduleClass(moving.id, moveBody(moving, form))
    confirming.value = ''
    emit('saved', { session: moving, result: data, room: selectedRoom.value })
  } catch (e) {
    confirming.value = ''
    saveError.value = e.message + (e.requestId ? ` (request ID ${e.requestId})` : '')
    if (['SLOT_TAKEN', 'SLOT_UNAVAILABLE', 'CLASS_CHANGED'].includes(e.code)) check()
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="rd" aria-labelledby="rd-title" @cancel.prevent="requestClose">
    <header class="rd-head">
      <h2 id="rd-title">Reschedule class</h2>
      <label class="rd-class">Class
        <select ref="classSelect" :value="classId" :disabled="saving || !choices.length" @change="switchClass">
          <option v-for="item in choices" :key="item.id" :value="item.id">{{ classLabel(item) }}</option>
        </select>
      </label>
      <p v-if="classId" class="rd-id">Class ID <code>{{ classId }}</code></p>
    </header>

    <div class="rd-body">
      <p v-if="!choices.length" class="rd-state">There are no upcoming classes in this week to reschedule. Choose another week in the timetable.</p>

      <template v-else-if="session">
        <dl class="rd-details" aria-label="Current class">
          <div><dt>Course</dt><dd><strong>{{ session.course_code }}</strong> {{ session.course_name }}</dd></div>
          <div><dt>Class type</dt><dd class="rd-cap">{{ session.course_type }}</dd></div>
          <div><dt>Intake &amp; group</dt><dd>{{ session.intake?.intake_code || 'Unknown intake' }} · Group {{ session.group_number }}</dd></div>
          <div><dt>Lecturer</dt><dd>{{ session.lecturer?.full_name || 'Unknown lecturer' }}</dd></div>
          <div><dt>Venue now</dt><dd>{{ session.room?.name || 'No room' }}<small v-if="session.room?.building"> · {{ session.room.building }}</small></dd></div>
          <div><dt>Time now</dt><dd>{{ longDay(current.date) }}, {{ current.range }}</dd></div>
        </dl>

        <section class="rd-section" aria-labelledby="rd-time">
          <div class="rd-row">
            <h3 id="rd-time">New time</h3>
            <div class="rd-week">
              <button type="button" class="rd-icon" aria-label="Previous week" :disabled="prevWeekDisabled || saving" @click="moveWeek(-1)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z" /></svg>
              </button>
              <button type="button" class="rd-icon" aria-label="Next week" :disabled="saving" @click="moveWeek(1)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.6 16.6 10 18l6-6-6-6-1.4 1.4 4.6 4.6z" /></svg>
              </button>
            </div>
          </div>
          <div class="rd-days" role="group" aria-label="Day">
            <button
              v-for="day in days" :key="day.iso" type="button" class="rd-day" :class="{ 'is-on': day.iso === form.date }"
              :aria-pressed="day.iso === form.date" :disabled="day.past || saving" @click="pickDate(day.iso)"
            >{{ day.label }}</button>
          </div>

          <p v-if="loadError" class="rd-alert rd-error" role="alert">{{ loadError }} <button type="button" class="rd-link" @click="check">Try again</button></p>
          <p v-else-if="loading && !shown" class="rd-state" aria-busy="true">Checking availability…</p>
          <p v-else-if="shown && !slots.length" class="rd-state">No teaching hours on {{ longDay(form.date) }}. Choose another day.</p>
          <div v-else class="rd-slots" :class="{ 'is-loading': loading }" role="group" aria-label="Start time">
            <button
              v-for="slot in slots" :key="slot.start" type="button" class="rd-slot"
              :class="{ 'is-on': slot.start === form.start, 'is-now': form.date === original?.date && slot.start === original?.start }"
              :disabled="Boolean(slotBlock(slot, form.roomId)) || saving" :aria-pressed="slot.start === form.start"
              :title="slotBlock(slot, form.roomId) || `${formatMinutes(toMinutes(slot.start))} – ${formatMinutes(toMinutes(slot.end))}`"
              @click="pickSlot(slot)"
            >{{ formatMinutes(toMinutes(slot.start)) }}</button>
          </div>
          <p class="rd-legend">
            <span><i class="rd-swatch is-on"></i>Chosen</span><span><i class="rd-swatch is-now"></i>Current time</span>
            <span><i class="rd-swatch is-off"></i>Not possible in the selected room</span>
            <button v-if="form.start" type="button" class="rd-link" :disabled="saving" @click="form.start = ''">Clear time</button>
          </p>
          <p v-if="timeChecked?.time_issues.length" class="rd-alert rd-error" role="alert">
            {{ timeChecked.time_issues.map((issue) => issue.detail).join(' ') }}
          </p>
        </section>

        <section class="rd-section" aria-labelledby="rd-venue">
          <h3 id="rd-venue">Venue</h3>
          <label class="rd-sr" for="rd-room">Venue</label>
          <select id="rd-room" v-model="form.roomId" class="rd-select" :disabled="saving || !rooms.length">
            <option v-for="room in rooms" :key="room.id" :value="room.id" :disabled="room.disabled && room.id !== form.roomId">
              {{ room.name }} · {{ room.building }} · {{ room.room_type }} · {{ room.capacity }} seats{{ room.note ? ` — ${room.note}` : '' }}
            </option>
          </select>
          <p class="rd-hint">{{ form.start ? 'Greyed-out venues are not available at the chosen time.' : 'Greyed-out venues have no free time on this day. Choose a start time to check a venue for that time.' }}</p>
        </section>

        <section class="rd-section">
          <label class="rd-label" for="rd-reason">Reason for the change <span class="rd-hint">(kept in the change history)</span></label>
          <textarea id="rd-reason" v-model="form.reason" rows="2" maxlength="500" :disabled="saving" placeholder="For example: lecturer attending a conference"></textarea>
        </section>

        <p class="rd-summary" :class="{ 'is-ready': moved && roomFree }" aria-live="polite">
          <template v-if="moved">
            New: <strong>{{ longDay(form.date) }}, {{ newRange }}</strong> in <strong>{{ selectedRoom?.name || '—' }}</strong>
          </template>
          <template v-else>No changes yet.</template>
        </p>
        <p v-if="notice" class="rd-alert rd-warning" role="status">{{ notice }}</p>
        <p v-if="saveError" class="rd-alert rd-error" role="alert">{{ saveError }}</p>
      </template>
    </div>

    <footer class="rd-foot">
      <div v-if="confirming === 'discard'" class="rd-confirm" role="alertdialog" aria-labelledby="rd-discard-title">
        <p><strong id="rd-discard-title">Discard your changes?</strong> The changes you made will not be saved.</p>
        <div class="rd-actions">
          <button type="button" class="rd-btn rd-plain" @click="confirming = ''; pendingClassId = ''">Keep editing</button>
          <button type="button" class="rd-btn rd-danger" @click="discard">Discard changes</button>
        </div>
      </div>
      <div v-else-if="confirming === 'save'" class="rd-confirm" role="alertdialog" aria-labelledby="rd-save-title">
        <p>
          <strong id="rd-save-title">Publish this change?</strong>
          {{ session.course_code }} moves to {{ longDay(form.date) }}, {{ newRange }} in {{ selectedRoom?.name }}.
          It is published straight away to everyone involved: the students of {{ session.intake?.intake_code || 'the intake' }}
          group {{ session.group_number }}, {{ session.lecturer?.full_name || 'the lecturer' }} and administrators.
        </p>
        <div class="rd-actions">
          <button type="button" class="rd-btn rd-plain" :disabled="saving" @click="confirming = ''">Back</button>
          <button type="button" class="rd-btn rd-blue" :disabled="saving" @click="publish">{{ saving ? 'Publishing…' : 'Publish change' }}</button>
        </div>
      </div>
      <div v-else class="rd-actions">
        <span v-if="session && saveHint" class="rd-hint">{{ saveHint }}</span>
        <button type="button" class="rd-btn rd-plain" @click="requestClose">Cancel</button>
        <button type="button" class="rd-btn rd-blue" :disabled="!canSave" @click="confirming = 'save'">Save</button>
      </div>
    </footer>
  </dialog>
</template>

<style scoped>
.rd {
  width: min(780px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); box-sizing: border-box; padding: 0;
  display: flex; flex-direction: column; border: 1px solid #e2e7ef; border-radius: 16px; background: #fff; color: #202124;
  box-shadow: 0 12px 36px rgba(60, 64, 67, .28);
}
.rd:not([open]) { display: none; }
.rd::backdrop { background: rgba(32, 33, 36, .4); }
.rd h2 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -.3px; }
.rd h3 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: 0; }
.rd button, .rd select, .rd textarea { font: inherit; }
.rd button { cursor: pointer; }
.rd button:disabled { cursor: not-allowed; }
.rd-head { display: flex; flex-direction: column; gap: 8px; padding: 20px 24px 14px; border-bottom: 1px solid #e2e7ef; }
.rd-class { display: flex; flex-direction: column; gap: 6px; margin: 0; font-size: 13px; font-weight: 600; color: #3c4043; text-transform: none; }
.rd select { width: 100%; padding: 9px 10px; border: 1px solid #cdd5e0; border-radius: 8px; background: #fff; color: #202124; font-weight: 400; }
.rd-id { margin: 0; color: #5f6368; font-size: 12px; }
.rd-id code { padding: 2px 6px; border-radius: 6px; background: #f1f3f4; color: #202124; font-size: 12px; overflow-wrap: anywhere; }
.rd-body { flex: 1; min-height: 0; overflow: auto; padding: 16px 24px; display: flex; flex-direction: column; gap: 16px; }
.rd-details { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px 16px; margin: 0; padding: 14px 16px; border-radius: 12px; background: #f8f9fa; }
.rd-details div { min-width: 0; }
.rd-details dt { color: #5f6368; font-size: 12px; font-weight: 600; }
.rd-details dd { margin: 2px 0 0; overflow-wrap: anywhere; }
.rd-details small { color: #5f6368; }
.rd-cap { text-transform: capitalize; }
.rd-section { display: flex; flex-direction: column; gap: 10px; }
.rd-row { display: flex; align-items: center; justify-content: space-between; }
.rd-week { display: flex; gap: 2px; }
.rd-icon { display: grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%; background: transparent; }
.rd-icon svg { width: 22px; height: 22px; fill: #3c4043; }
.rd-icon:hover:not(:disabled) { background: #f1f3f4; }
.rd-icon:disabled svg { fill: #bdc1c6; }
.rd-days { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
.rd-day { padding: 8px 4px; border: 1px solid #dadce0; border-radius: 8px; background: #fff; color: #3c4043; white-space: nowrap; }
.rd-day:hover:not(:disabled) { background: #f8f9fa; }
.rd-day.is-on { border-color: #1a73e8; background: #e8f0fe; color: #1967d2; font-weight: 600; }
.rd-day:disabled { background: #f1f3f4; color: #9aa0a6; }
.rd-slots { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 6px; transition: opacity .15s; }
.rd-slots.is-loading { opacity: .6; }
.rd-slot { position: relative; padding: 7px 4px; border: 1px solid #dadce0; border-radius: 8px; background: #fff; color: #202124; font-size: 13px; font-variant-numeric: tabular-nums; }
.rd-slot:hover:not(:disabled) { border-color: #1a73e8; background: #e8f0fe; }
.rd-slot.is-now { border-style: dashed; border-color: #1a73e8; }
.rd-slot.is-on { border: 1px solid #1a73e8; background: #1a73e8; color: #fff; font-weight: 600; }
.rd-slot:disabled { border-color: #f1f3f4; background: #f1f3f4; color: #9aa0a6; text-decoration: line-through; }
.rd-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; margin: 0; color: #5f6368; font-size: 12px; }
.rd-legend span { display: inline-flex; align-items: center; gap: 6px; }
.rd-swatch { display: inline-block; width: 14px; height: 14px; border-radius: 4px; border: 1px solid #dadce0; }
.rd-swatch.is-on { background: #1a73e8; border-color: #1a73e8; }
.rd-swatch.is-now { border: 1px dashed #1a73e8; }
.rd-swatch.is-off { background: #f1f3f4; border-color: #f1f3f4; }
.rd-label { font-size: 15px; font-weight: 600; }
.rd textarea { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid #cdd5e0; border-radius: 8px; resize: vertical; }
.rd-hint { color: #5f6368; font-size: 12px; font-weight: 400; }
.rd-state { margin: 0; padding: 12px 14px; border-radius: 8px; background: #f8f9fa; color: #5f6368; font-size: 14px; }
.rd-alert { margin: 0; padding: 10px 14px; border-radius: 8px; font-size: 13px; line-height: 1.5; }
.rd-error { background: #fce8e6; color: #a50e0e; }
.rd-warning { background: #fef7e0; color: #7a4f01; }
.rd-summary { margin: 0; padding: 10px 14px; border-radius: 8px; background: #f8f9fa; color: #5f6368; font-size: 14px; }
.rd-summary.is-ready { background: #e8f0fe; color: #174ea6; }
.rd-link { padding: 0; border: 0; background: none; color: #1a73e8; font-weight: 600; font-size: 12px; }
.rd-link:hover { text-decoration: underline; }
.rd-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.rd-foot { padding: 14px 24px 18px; border-top: 1px solid #e2e7ef; }
.rd-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.rd-actions .rd-hint { margin-right: auto; }
.rd-confirm { display: flex; flex-direction: column; gap: 12px; padding: 14px; border-radius: 10px; background: #fef7e0; }
.rd-confirm p { margin: 0; font-size: 14px; line-height: 1.5; }
.rd-confirm strong { display: block; margin-bottom: 2px; }
.rd-btn { padding: 10px 18px; border-radius: 8px; font-weight: 600; }
.rd-btn:disabled { opacity: .5; }
.rd-plain { border: 1px solid #dadce0; background: #fff; color: #1a73e8; }
.rd-plain:hover:not(:disabled) { background: #f8f9fa; }
.rd-blue { border: 0; background: #1a73e8; color: #fff; }
.rd-blue:hover:not(:disabled) { background: #1765cc; }
.rd-danger { border: 0; background: #d93025; color: #fff; }
.rd-danger:hover { background: #b3261e; }
.rd button:focus-visible, .rd select:focus-visible, .rd textarea:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
@media (max-width: 560px) {
  .rd-head, .rd-body, .rd-foot { padding-left: 16px; padding-right: 16px; }
  .rd-days { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
