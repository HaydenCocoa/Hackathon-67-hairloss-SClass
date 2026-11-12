<script setup>
// Two steps in one modal:
//   1. The lecturer writes when they would like to hold the class (a date, a start time and how flexible they are).
//   2. The backend answers with free times and rooms from the timetable; the lecturer picks one and confirms.
// The end time is never typed: it is the start time plus the course length. The server re-checks the
// chosen slot when it is saved, so a slot taken in the meantime comes back as a clear clash message.
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { api } from './dataSource'
import { CLOSE_TIME, OPEN_TIME, endTime, formatTime, latestStart, longDate, requestProblems } from './time'
import { groupText, slotKey, typeLabel } from './session'
import SlotSuggestions from './SlotSuggestions.vue'

const props = defineProps({
  session: { type: Object, default: null }, // the class being moved; null keeps the dialog closed
  lecturerId: { type: String, default: '' },
  today: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const FLEXIBILITY = [
  { value: 0, label: 'Only that day' },
  { value: 1, label: 'Up to 1 day either side' },
  { value: 3, label: 'Up to 3 days either side' },
  { value: 7, label: 'Up to a week either side' },
]

const dialog = ref(null)
const dateInput = ref(null)
const timeInput = ref(null)
const step = ref('request') // 'request' | 'pick'
const form = reactive({ date: '', time: '', flex: 1, reason: '' })
const asked = ref(null) // the request the shown slots answer: { date, time, flexDays }
const slots = ref([])
const picked = ref('')
const searching = ref(false)
const saving = ref(false)
const error = ref(null) // { message, conflicts }

const endHint = computed(() => (props.session ? endTime(form.time, props.session.duration_minutes) : null))
// Date and start time must be inside the opening days and hours; otherwise a prompt appears and the next step is blocked.
const problems = computed(() =>
  props.session ? requestProblems(form.date, form.time, props.session.duration_minutes, props.today) : { date: '', time: '' },
)
const hasProblem = computed(() => !!(problems.value.date || problems.value.time))
const latestTime = computed(() => (props.session ? latestStart(props.session.duration_minutes) : null))
// The browser's own validity message doubles as the pop-up prompt.
watch(problems, (p) => {
  dateInput.value?.setCustomValidity(p.date)
  timeInput.value?.setCustomValidity(p.time)
}, { flush: 'post' })
// Show the prompt as soon as a value is chosen outside the range.
const showPrompt = (el) => nextTick(() => el?.value && !el.value.validity.valid && el.value.reportValidity())

const askedText = computed(() => {
  if (!asked.value) return ''
  const flex = FLEXIBILITY.find((f) => f.value === asked.value.flexDays)?.label.toLowerCase()
  return `Around ${formatTime(asked.value.time)} on ${longDate(asked.value.date)} · ${flex}`
})

watch(
  () => props.session,
  async (session) => {
    if (session) {
      Object.assign(form, { date: session.session_date, time: session.start_time, flex: 1, reason: '' })
      step.value = 'request'
      slots.value = []
      picked.value = ''
      asked.value = null
      error.value = null
      await nextTick()
      if (!dialog.value.open) dialog.value.showModal()
    } else if (dialog.value?.open) {
      dialog.value.close()
    }
  },
)

async function search() {
  if (hasProblem.value) {
    ;(problems.value.date ? dateInput : timeInput).value?.reportValidity()
    return
  }
  if (!form.date || !form.time) {
    error.value = { message: 'Choose the date and start time you would like.', conflicts: [] }
    return
  }
  searching.value = true
  error.value = null
  const request = { date: form.date, time: form.time, flexDays: Number(form.flex) }
  try {
    slots.value = await api.suggestSlots(props.lecturerId, props.session.id, { ...request, limit: 6 })
    asked.value = request
    picked.value = slots.value.length ? slotKey(slots.value[0]) : ''
    step.value = 'pick'
  } catch (e) {
    error.value = { message: e.message, conflicts: e.conflicts || [] }
  } finally {
    searching.value = false
  }
}

function backToRequest() {
  error.value = null
  step.value = 'request'
}

async function confirm() {
  const slot = slots.value.find((s) => slotKey(s) === picked.value)
  if (!slot) return
  saving.value = true
  error.value = null
  try {
    await api.reschedule(props.lecturerId, props.session.id, {
      session_date: slot.session_date,
      start_time: slot.start_time,
      room_id: slot.room_id,
      reason: form.reason.trim() || null,
    })
    dialog.value.close()
    emit('saved', slot)
  } catch (e) {
    error.value = { message: e.message, conflicts: e.conflicts || [] }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="lc-dialog" aria-labelledby="lc-dialog-title" @close="emit('close')">
    <div v-if="session">
      <h2 id="lc-dialog-title">Reschedule class</h2>
      <p class="lc-current">
        <strong>{{ session.course_code }} · {{ typeLabel(session) }}</strong> · {{ session.course_name }}<br />
        {{ groupText(session) }}<br />
        Now: {{ longDate(session.session_date) }}, {{ formatTime(session.start_time) }} – {{ formatTime(session.end_time) }},
        {{ session.room_name || 'no room' }}
      </p>

      <div v-if="error" class="lc-form-error" role="alert">
        <p>{{ error.message }}</p>
        <ul v-if="error.conflicts.length">
          <li v-for="(conflict, i) in error.conflicts" :key="i">{{ conflict.message }}</li>
        </ul>
      </div>

      <!-- Step 1: when would you like it? -->
      <form v-if="step === 'request'" novalidate @submit.prevent="search">
        <p class="lc-step">Step 1 of 2 · When would you like to hold this class?</p>
        <div class="lc-field-row">
          <div class="lc-field">
            <label for="lc-date">Move it to</label>
            <input id="lc-date" ref="dateInput" v-model="form.date" type="date" :min="today" required
                   :aria-invalid="!!problems.date" @change="showPrompt(dateInput)" />
            <p v-if="problems.date" class="lc-field-error" role="alert">{{ problems.date }}</p>
          </div>
          <div class="lc-field">
            <label for="lc-time">Preferred start time</label>
            <input id="lc-time" ref="timeInput" v-model="form.time" type="time" required
                   :min="OPEN_TIME" :max="latestTime || CLOSE_TIME" :aria-invalid="!!problems.time" @change="showPrompt(timeInput)" />
            <p v-if="problems.time" class="lc-field-error" role="alert">{{ problems.time }}</p>
          </div>
        </div>
        <p class="lc-end" aria-live="polite">
          <template v-if="endHint">It would end at <strong>{{ formatTime(endHint.hhmm) }}<span v-if="endHint.nextDay"> (next day)</span></strong> ({{ session.duration_minutes }} min).</template>
          <template v-else>Class length: {{ session.duration_minutes }} min.</template>
        </p>

        <div class="lc-field">
          <label for="lc-flex">If that exact time is not free</label>
          <select id="lc-flex" v-model="form.flex">
            <option v-for="f in FLEXIBILITY" :key="f.value" :value="f.value">{{ f.label }}</option>
          </select>
          <p class="lc-hint">We check the timetable and suggest free times and rooms nearest to your request. Classes run Monday to Friday, 08:30 to 18:00, with at least 15 minutes between classes.</p>
        </div>

        <div class="lc-field">
          <label for="lc-reason">Reason <span class="lc-optional">(optional)</span></label>
          <textarea id="lc-reason" v-model="form.reason" maxlength="300" rows="2"></textarea>
        </div>

        <div class="lc-actions">
          <button type="button" class="lc-btn lc-btn-text" @click="dialog.close()">Cancel</button>
          <button type="submit" class="lc-btn lc-btn-primary" :disabled="searching || hasProblem">
            {{ searching ? 'Checking the timetable…' : 'Find available times' }}
          </button>
        </div>
      </form>

      <!-- Step 2: choose one of the recommended slots -->
      <form v-else novalidate @submit.prevent="confirm">
        <p class="lc-step">Step 2 of 2 · Pick a time</p>
        <p class="lc-asked">{{ askedText }} <button type="button" class="lc-btn lc-btn-text" @click="backToRequest">Change</button></p>

        <SlotSuggestions v-if="slots.length" v-model="picked" :slots="slots" :request="asked" />
        <p v-else class="lc-state">
          No free time matches that request. Go back and try another date or allow more flexibility.
        </p>

        <div class="lc-actions">
          <button type="button" class="lc-btn lc-btn-text" :disabled="saving" @click="backToRequest">Back</button>
          <button type="submit" class="lc-btn lc-btn-primary" :disabled="saving || !picked">
            {{ saving ? 'Saving…' : 'Confirm new time' }}
          </button>
        </div>
      </form>
    </div>
  </dialog>
</template>
