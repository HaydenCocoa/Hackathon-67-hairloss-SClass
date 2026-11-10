<script setup>
// Modal form for moving one class. The end time is shown, not entered: start + the course duration.
// The server decides whether the new slot is allowed and answers with the exact clashes if not.
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { reschedule } from './lecturerApi'
import { endTime, formatTime, longDate } from './time'
import { groupText, roomsFor, typeLabel } from './session'

const props = defineProps({
  session: { type: Object, default: null }, // the class being moved; null keeps the dialog closed
  rooms: { type: Array, default: () => [] },
  roomsError: { type: String, default: '' },
  lecturerId: { type: String, default: '' },
  today: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const dialog = ref(null)
const form = reactive({ date: '', start: '', roomId: '', reason: '' })
const error = ref(null) // { message, conflicts }
const saving = ref(false)

const choices = computed(() => (props.session ? roomsFor(props.session, props.rooms) : []))
const end = computed(() => (props.session ? endTime(form.start, props.session.duration_minutes) : null))
const endLabel = computed(() => (end.value ? formatTime(end.value.hhmm) + (end.value.nextDay ? ' (next day)' : '') : '–'))

function pickDefaultRoom() {
  if (!choices.value.some((room) => room.id === form.roomId)) form.roomId = choices.value[0]?.id ?? ''
}

watch(
  () => props.session,
  async (session) => {
    if (session) {
      Object.assign(form, { date: session.session_date, start: session.start_time, roomId: session.room_id || '', reason: '' })
      pickDefaultRoom()
      error.value = null
      await nextTick()
      if (!dialog.value.open) dialog.value.showModal()
    } else if (dialog.value?.open) {
      dialog.value.close()
    }
  },
)
watch(choices, () => props.session && pickDefaultRoom()) // rooms may finish loading after the dialog opens

async function submit() {
  if (!form.date || !form.start || !form.roomId) {
    error.value = { message: 'Choose a date, start time and room.', conflicts: [] }
    return
  }
  saving.value = true
  error.value = null
  try {
    await reschedule(props.lecturerId, props.session.id, {
      session_date: form.date,
      start_time: form.start,
      room_id: form.roomId,
      reason: form.reason.trim() || null,
    })
    dialog.value.close()
    emit('saved')
  } catch (e) {
    error.value = { message: e.message, conflicts: e.conflicts || [] }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="lc-dialog" aria-labelledby="lc-dialog-title" @close="emit('close')">
    <form v-if="session" novalidate @submit.prevent="submit">
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

      <div class="lc-field-row">
        <div class="lc-field">
          <label for="lc-date">New date</label>
          <input id="lc-date" v-model="form.date" type="date" :min="today" required />
        </div>
        <div class="lc-field">
          <label for="lc-start">Start time</label>
          <input id="lc-start" v-model="form.start" type="time" required />
        </div>
      </div>
      <p class="lc-end" aria-live="polite">Ends at <strong>{{ endLabel }}</strong> ({{ session.duration_minutes }} min)</p>

      <div class="lc-field">
        <label for="lc-room">Room</label>
        <select id="lc-room" v-model="form.roomId" required>
          <option v-for="room in choices" :key="room.id" :value="room.id">
            {{ room.name }} · {{ room.building }} · seats {{ room.capacity }}
          </option>
        </select>
        <p v-if="!choices.length" class="lc-hint">{{ roomsError || 'No active room fits this class.' }}</p>
        <p v-else class="lc-hint">
          Showing {{ session.required_room_type }} rooms that seat {{ session.student_count }} students.
        </p>
      </div>

      <div class="lc-field">
        <label for="lc-reason">Reason <span class="lc-optional">(optional)</span></label>
        <textarea id="lc-reason" v-model="form.reason" maxlength="300" rows="2"></textarea>
      </div>

      <div class="lc-actions">
        <button type="button" class="lc-btn lc-btn-text" :disabled="saving" @click="dialog.close()">Cancel</button>
        <button type="submit" class="lc-btn lc-btn-primary" :disabled="saving || !choices.length">
          {{ saving ? 'Saving…' : 'Save new time' }}
        </button>
      </div>
    </form>
  </dialog>
</template>
