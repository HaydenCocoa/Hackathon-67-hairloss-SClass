<script setup>
// Monday-to-Sunday calendar grid shared by the room timetable and the schedule preview.
// The parent gives the days (weekDays), the laid-out events (layoutWeek/layoutEvents) and
// what each block says (the "event" slot). Saturday and Sunday are greyed.
import { computed } from 'vue'
import { hourLabel, toneOf } from './roomCalendar'

const props = defineProps({
  days: { type: Array, required: true },
  layout: { type: Object, required: true }, // { days: { [iso]: event[] }, firstHour, lastHour }
  describe: { type: Function, required: true }, // event -> full text for the tooltip and screen readers
  hourPx: { type: Number, default: 56 },
  dimmed: { type: Boolean, default: false },
  selectedId: { type: String, default: '' }, // highlighted block (click selects, double-click/Enter opens)
})
defineEmits(['select', 'open'])

const hours = computed(() => Array.from({ length: props.layout.lastHour - props.layout.firstHour }, (_, i) => props.layout.firstHour + i))
const height = computed(() => hours.value.length * props.hourPx)

function blockStyle(event) {
  const top = ((event.startMinutes - props.layout.firstHour * 60) / 60) * props.hourPx
  const tall = Math.max(((event.endMinutes - event.startMinutes) / 60) * props.hourPx, 22)
  const width = 100 / event.lanes
  return { top: `${top}px`, height: `${tall}px`, left: `calc(${event.lane * width}% + 2px)`, width: `calc(${width}% - 4px)` }
}
</script>

<template>
  <div class="wg-scroll">
    <div class="wg" :class="{ 'is-dimmed': dimmed }">
      <div class="wg-corner" aria-hidden="true"></div>
      <div v-for="day in days" :key="day.iso" class="wg-head" :class="{ 'is-weekend': day.weekend, 'is-today': day.isToday }">
        <span class="wg-dow">{{ day.dow }}</span>
        <span class="wg-dom" :aria-label="day.label">{{ day.dom }}</span>
      </div>

      <div class="wg-gutter" :style="{ height: `${height}px` }" aria-hidden="true">
        <span v-for="hour in hours" :key="hour" class="wg-hour" :style="{ top: `${(hour - layout.firstHour) * hourPx}px` }">{{ hourLabel(hour) }}</span>
      </div>
      <div
        v-for="day in days" :key="`col-${day.iso}`" class="wg-col" :class="{ 'is-weekend': day.weekend }"
        :style="{ height: `${height}px`, backgroundSize: `100% ${hourPx}px` }"
        role="list" :aria-label="`${day.label}${day.weekend ? ' (weekend)' : ''}`"
      >
        <article
          v-for="event in layout.days[day.iso]" :key="event.id || event.occurrence_id" role="listitem" tabindex="0"
          class="wg-event"
          :class="[`wg-${toneOf(event.course_type)}`, { 'is-cancelled': event.status === 'cancelled', 'is-selected': selectedId && event.id === selectedId }]"
          :style="blockStyle(event)" :title="describe(event)" :aria-label="describe(event)"
          :aria-current="selectedId && event.id === selectedId ? 'true' : undefined"
          @click="$emit('select', event)" @dblclick="$emit('open', event)"
          @keydown.enter.prevent="$emit('open', event)" @keydown.space.prevent="$emit('select', event)"
        >
          <slot name="event" :event="event" />
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wg-scroll { overflow-x: auto; border: 1px solid #e2e7ef; border-radius: 12px; background: #fff; }
.wg { display: grid; grid-template-columns: 52px repeat(7, minmax(84px, 1fr)); min-width: 640px; color: #202124; transition: opacity .15s; }
.wg.is-dimmed { opacity: .55; }
.wg-corner, .wg-head { border-bottom: 1px solid #e2e7ef; }
.wg-head { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 10px 0 8px; border-left: 1px solid #e2e7ef; }
.wg-dow { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: #5f6368; }
.wg-dom { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; font-size: 20px; }
.wg-head.is-today .wg-dow { color: #1a73e8; }
.wg-head.is-today .wg-dom { background: #1a73e8; color: #fff; }
.wg-head.is-weekend { background: #f1f3f4; }
.wg-head.is-weekend .wg-dow, .wg-head.is-weekend .wg-dom { color: #9aa0a6; }

.wg-gutter { position: relative; }
.wg-hour { position: absolute; right: 8px; transform: translateY(-50%); font-size: 11px; color: #5f6368; white-space: nowrap; }
.wg-hour:first-child { transform: none; }
.wg-col { position: relative; border-left: 1px solid #e2e7ef; background-image: linear-gradient(to bottom, #e2e7ef 1px, transparent 1px); }
.wg-col.is-weekend { background-color: #f1f3f4; }

.wg-event {
  position: absolute; box-sizing: border-box; overflow: hidden; display: flex; flex-direction: column; gap: 1px;
  padding: 4px 6px; border-radius: 6px; border-left: 4px solid; font-size: 12px; line-height: 1.3; cursor: pointer; user-select: none;
}
.wg-event:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
.wg-event :slotted(*) { flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wg-event :slotted(strong) { display: flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; }
.wg-event.wg-blue { background: #e8f0fe; border-color: #4285f4; }
.wg-event.wg-green { background: #e6f4ea; border-color: #34a853; }
.wg-event.wg-yellow { background: #fef7e0; border-color: #fbbc04; }
.wg-event.wg-red { background: #fce8e6; border-color: #ea4335; }
.wg-event.is-cancelled { background: #f8f9fa; border-color: #bdc1c6; color: #80868b; text-decoration: line-through; }
.wg-event.is-selected { z-index: 1; box-shadow: 0 0 0 2px #1a73e8, 0 2px 6px rgba(26, 115, 232, .35); }
</style>
