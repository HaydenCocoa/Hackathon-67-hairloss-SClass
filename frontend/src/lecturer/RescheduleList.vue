<script setup>
// Upcoming classes the lecturer can still move. Picking one asks the page to open the dialog.
import { formatDate, formatTime, longDate } from './time'
import { groupText, toneOf, typeLabel } from './session'

defineProps({
  sessions: { type: Array, required: true },
  loading: Boolean,
  error: { type: String, default: '' },
})
defineEmits(['pick', 'retry'])
</script>

<template>
  <section id="lc-panel-reschedule" role="tabpanel" aria-labelledby="lc-tab-reschedule">
    <h2 class="lc-title">Upcoming classes</h2>
    <p class="lc-sub">Pick a class, tell us when you would like to hold it instead, and choose from the free times we suggest.</p>

    <div v-if="loading" class="lc-state"><span class="lc-spinner" aria-hidden="true"></span> Loading classes…</div>
    <p v-else-if="error" class="lc-state lc-state-error" role="alert">
      {{ error }} <button class="lc-btn lc-btn-text" type="button" @click="$emit('retry')">Try again</button>
    </p>
    <p v-else-if="!sessions.length" class="lc-state">You have no upcoming classes to reschedule.</p>
    <ul v-else class="lc-classes">
      <li v-for="s in sessions" :key="s.id" class="lc-row">
        <div class="lc-datebox" :class="'lc-tone-' + toneOf(s.course_code)" aria-hidden="true">
          <span class="lc-datebox-mon">{{ formatDate(s.session_date, { month: 'short' }) }}</span>
          <span class="lc-datebox-day">{{ formatDate(s.session_date, { day: 'numeric' }) }}</span>
        </div>
        <div class="lc-info">
          <p class="lc-row-title">
            {{ s.course_code }} · {{ typeLabel(s) }} · {{ s.course_name }}
            <span v-if="s.moved" class="lc-chip lc-chip-moved">Rescheduled</span>
          </p>
          <p class="lc-row-meta">
            {{ longDate(s.session_date) }} · {{ formatTime(s.start_time) }} – {{ formatTime(s.end_time) }}
            · {{ s.room_name || 'No room' }} · {{ groupText(s) }}
          </p>
        </div>
        <button
          class="lc-btn lc-btn-primary"
          type="button"
          :aria-label="`Reschedule ${s.course_code} ${typeLabel(s)} on ${longDate(s.session_date)}`"
          @click="$emit('pick', s)"
        >
          Reschedule
        </button>
      </li>
    </ul>
  </section>
</template>
