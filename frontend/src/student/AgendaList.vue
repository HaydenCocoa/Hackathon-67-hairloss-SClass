<script setup>
import { computed } from 'vue'
import { addDays, fmtDayLong, fmtTime, sameDay } from './time'

const props = defineProps({
  weekStart: { type: Date, required: true },
  events: { type: Array, required: true },
})
const emit = defineEmits(['select'])

const today = new Date()
const days = computed(() => Array.from({ length: 7 }, (_, i) => addDays(props.weekStart, i))
  .map((day) => ({
    day,
    isToday: sameDay(day, today),
    items: props.events.filter((e) => sameDay(e.start, day)).sort((a, b) => a.start - b.start),
  }))
  .filter((d, i) => i < 5 || d.items.length))
</script>

<template>
  <div class="agenda">
    <section v-for="d in days" :key="d.day.toDateString()" :class="['agenda-day', { today: d.isToday }]">
      <h3>
        {{ fmtDayLong(d.day) }}
        <span v-if="d.isToday" class="sp-badge neutral today-badge">Today</span>
      </h3>
      <p v-if="!d.items.length" class="free">No classes</p>
      <button
        v-for="e in d.items"
        :key="e.key"
        type="button"
        :class="['row', `type-${e.type}`, { 'is-cancelled': e.cancelled }]"
        @click="emit('select', e)"
      >
        <span class="time">{{ fmtTime(e.start) }}<small>{{ fmtTime(e.end) }}</small></span>
        <span class="bar"></span>
        <span class="info">
          <span class="title">{{ e.title }}</span>
          <span class="meta">{{ e.subtitle }}</span>
          <span class="meta">{{ e.place }}<template v-if="e.lecturer"> · {{ e.lecturer }}</template></span>
        </span>
        <span class="badges">
          <span v-if="e.cancelled" class="sp-badge cancelled">Cancelled</span>
          <span v-else-if="e.moved" class="sp-badge moved">Rescheduled</span>
        </span>
      </button>
    </section>
  </div>
</template>

<style scoped>
.agenda {
  border: 1px solid var(--grey-300); border-radius: var(--radius); background: #fff;
  padding: 4px 0;
}
.agenda-day { padding: 12px 20px; }
.agenda-day + .agenda-day { border-top: 1px solid var(--grey-200); }
h3 { font-size: 14px; font-weight: 500; color: var(--grey-700); margin-bottom: 6px !important; display: flex; align-items: center; gap: 8px; }
.agenda-day.today h3 { color: var(--blue); }
.today-badge { background: var(--blue-soft); color: var(--blue-text); }
.free { margin: 0; color: var(--grey-500); font-size: 13px; padding: 4px 0; }

.row {
  display: grid; grid-template-columns: 64px 4px 1fr auto; gap: 14px; align-items: center;
  width: 100%; padding: 10px 12px; margin: 2px 0;
  border: 0; border-radius: 8px; background: transparent; text-align: left; font: inherit; color: inherit;
}
.row:hover { background: var(--grey-50); }
.time { display: flex; flex-direction: column; font-weight: 500; font-size: 14px; }
.time small { font-weight: 400; color: var(--grey-700); font-size: 12px; }
.bar { align-self: stretch; border-radius: 2px; background: var(--c); }
.info { display: flex; flex-direction: column; min-width: 0; }
.title { font-weight: 500; font-size: 15px; }
.is-cancelled .title { text-decoration: line-through; color: var(--red-text); }
.meta { color: var(--grey-700); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
