<script setup>
// View-only weekly timetable. It renders what it is given and offers no way to change a class.
import { formatTime } from './time'
import { groupText, toneOf, typeLabel } from './session'

defineProps({
  days: { type: Array, required: true }, // [{ iso, dow, dom, long, isToday, sessions: [...] }]
  label: { type: String, default: '' },
  loading: Boolean,
  error: { type: String, default: '' },
  hasClasses: Boolean,
})
defineEmits(['prev', 'next', 'today', 'retry'])
</script>

<template>
  <section id="lc-panel-timetable" role="tabpanel" aria-labelledby="lc-tab-timetable">
    <div class="lc-toolbar">
      <button class="lc-btn lc-btn-outline" type="button" @click="$emit('today')">Today</button>
      <button class="lc-icon-btn" type="button" aria-label="Previous week" @click="$emit('prev')">
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z" fill="currentColor" /></svg>
      </button>
      <button class="lc-icon-btn" type="button" aria-label="Next week" @click="$emit('next')">
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z" fill="currentColor" /></svg>
      </button>
      <h2 class="lc-range">{{ label }}</h2>
      <span class="lc-chip lc-chip-view">View only</span>
    </div>

    <div v-if="loading" class="lc-state"><span class="lc-spinner" aria-hidden="true"></span> Loading timetable…</div>
    <p v-else-if="error" class="lc-state lc-state-error" role="alert">
      {{ error }} <button class="lc-btn lc-btn-text" type="button" @click="$emit('retry')">Try again</button>
    </p>
    <template v-else>
      <p v-if="!hasClasses" class="lc-state">No classes this week.</p>
      <div class="lc-week">
        <section v-for="day in days" :key="day.iso" class="lc-day" :class="{ 'is-today': day.isToday }" :aria-label="day.long">
          <header class="lc-day-head">
            <span class="lc-dow">{{ day.dow }}</span>
            <span class="lc-dom">{{ day.dom }}</span>
          </header>
          <div class="lc-day-body">
            <article
              v-for="s in day.sessions"
              :key="s.id"
              class="lc-slot"
              :class="['lc-tone-' + toneOf(s.course_code), { 'is-cancelled': s.status === 'cancelled' }]"
            >
              <p class="lc-slot-time">{{ formatTime(s.start_time) }} – {{ formatTime(s.end_time) }}</p>
              <p class="lc-slot-code">
                {{ s.course_code }} · {{ typeLabel(s) }}
                <span v-if="s.status === 'cancelled'" class="lc-chip lc-chip-cancelled">Cancelled</span>
                <span v-else-if="s.moved" class="lc-chip lc-chip-moved">Rescheduled</span>
              </p>
              <p class="lc-slot-line">{{ s.course_name }}</p>
              <p class="lc-slot-line">{{ groupText(s) }}</p>
              <p v-if="s.room_name" class="lc-slot-room">
                <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" fill="currentColor" /></svg>
                {{ s.room_name }}
              </p>
            </article>
            <p v-if="!day.sessions.length" class="lc-none">No classes</p>
          </div>
        </section>
      </div>
    </template>
  </section>
</template>
