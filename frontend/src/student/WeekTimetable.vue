<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { addDays, fmtDayShort, fmtTime, minutesOfDay, sameDay } from './time'

const props = defineProps({
  weekStart: { type: Date, required: true },
  events: { type: Array, required: true }, // normalised events from StudentPage
})
const emit = defineEmits(['select'])

const HOUR_PX = 56
const now = ref(new Date())
let timer
onMounted(() => { timer = setInterval(() => { now.value = new Date() }, 60000) })
onBeforeUnmount(() => clearInterval(timer))

// Mon–Fri always; Sat/Sun only when something is scheduled.
const days = computed(() => {
  const all = Array.from({ length: 7 }, (_, i) => addDays(props.weekStart, i))
  return all.filter((d, i) => i < 5 || props.events.some((e) => sameDay(e.start, d)))
})

// 08:00–18:00 by default, stretched to fit early or late classes.
const hours = computed(() => {
  let first = 8
  let last = 18
  for (const e of props.events) {
    first = Math.min(first, e.start.getHours())
    last = Math.max(last, Math.ceil(minutesOfDay(e.end) / 60) || 24)
  }
  return Array.from({ length: last - first }, (_, i) => first + i)
})
const gridStart = computed(() => hours.value[0] * 60)
const gridHeight = computed(() => hours.value.length * HOUR_PX)

// Side-by-side lanes when classes overlap (e.g. two intakes clash).
function layoutDay(dayEvents) {
  const sorted = [...dayEvents].sort((a, b) => a.start - b.start || b.end - a.end)
  const placed = []
  let cluster = []
  let clusterEnd = 0
  let lanes = []
  const flush = () => {
    cluster.forEach((p) => { p.lanes = lanes.length })
    cluster = []
    lanes = []
  }
  for (const e of sorted) {
    if (cluster.length && e.start >= clusterEnd) flush()
    let lane = lanes.findIndex((end) => end <= e.start)
    if (lane === -1) { lane = lanes.length; lanes.push(e.end) } else lanes[lane] = e.end
    const p = { event: e, lane, lanes: 1 }
    cluster.push(p)
    placed.push(p)
    clusterEnd = Math.max(clusterEnd, e.end)
  }
  flush()
  return placed
}

const columns = computed(() => days.value.map((day) => ({
  day,
  isToday: sameDay(day, now.value),
  items: layoutDay(props.events.filter((e) => sameDay(e.start, day))).map((p) => {
    const top = ((minutesOfDay(p.event.start) - gridStart.value) / 60) * HOUR_PX
    const height = Math.max(((p.event.end - p.event.start) / 3600000) * HOUR_PX, 22)
    return {
      ...p,
      style: {
        top: `${top}px`,
        height: `${height - 2}px`,
        left: `calc(${(100 / p.lanes) * p.lane}% + 2px)`,
        width: `calc(${100 / p.lanes}% - 6px)`,
      },
      compact: height < 50,
    }
  }),
})))

const nowTop = computed(() => ((minutesOfDay(now.value) - gridStart.value) / 60) * HOUR_PX)
const showNow = computed(() => nowTop.value >= 0 && nowTop.value <= gridHeight.value)
const label = (h) => `${String(h).padStart(2, '0')}:00`
</script>

<template>
  <div class="week" :style="{ '--cols': days.length }">
    <div class="week-head">
      <div class="gutter"></div>
      <div v-for="col in columns" :key="col.day.toDateString()" :class="['day-head', { today: col.isToday }]">
        <span class="dow">{{ fmtDayShort(col.day) }}</span>
        <span class="date">{{ col.day.getDate() }}</span>
      </div>
    </div>

    <div class="week-body">
      <div class="gutter">
        <div v-for="h in hours" :key="h" class="hour-label" :style="{ height: HOUR_PX + 'px' }">{{ label(h) }}</div>
      </div>
      <div v-for="col in columns" :key="col.day.toDateString()" class="day-col" :style="{ height: gridHeight + 'px' }">
        <div v-for="h in hours" :key="h" class="hour-line" :style="{ height: HOUR_PX + 'px' }"></div>
        <div v-if="col.isToday && showNow" class="now-line" :style="{ top: nowTop + 'px' }"></div>

        <button
          v-for="item in col.items"
          :key="item.event.key"
          type="button"
          :class="['event', `type-${item.event.type}`, { 'is-cancelled': item.event.cancelled, compact: item.compact }]"
          :style="item.style"
          :title="`${item.event.title} · ${fmtTime(item.event.start)}–${fmtTime(item.event.end)}`"
          @click="emit('select', item.event)"
        >
          <span class="ev-title">
            <span v-if="item.event.cancelled" class="sp-badge cancelled">Cancelled</span>
            <span v-else-if="item.event.moved" class="sp-badge moved">Moved</span>
            {{ item.event.title }}
          </span>
          <span class="ev-meta">{{ fmtTime(item.event.start) }} – {{ fmtTime(item.event.end) }}</span>
          <span v-if="!item.compact" class="ev-meta">{{ item.event.place }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.week {
  border: 1px solid var(--grey-300);
  border-radius: var(--radius);
  background: #fff;
  overflow: auto;
  max-height: calc(100vh - 230px);
  min-height: 420px;
}
.week-head, .week-body {
  display: grid;
  grid-template-columns: 56px repeat(var(--cols), minmax(120px, 1fr));
}
.week-head {
  position: sticky; top: 0; z-index: 3; background: #fff;
  border-bottom: 1px solid var(--grey-300);
}
.day-head {
  display: flex; flex-direction: column; align-items: center; padding: 10px 0 8px;
  color: var(--grey-700);
}
.dow { font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: .8px; }
.date {
  display: grid; place-items: center; width: 40px; height: 40px; margin-top: 2px;
  border-radius: 50%; font-size: 22px; color: var(--grey-900);
}
.day-head.today .dow { color: var(--blue); }
.day-head.today .date { background: var(--blue); color: #fff; }

.gutter { position: relative; }
.hour-label {
  font-size: 10px; color: var(--grey-700); text-align: right; padding-right: 8px;
  transform: translateY(-7px);
}
.hour-label:first-child { visibility: hidden; }
.day-col { position: relative; border-left: 1px solid var(--grey-200); }
.hour-line { border-bottom: 1px solid var(--grey-200); }

.now-line {
  position: absolute; left: 0; right: 0; height: 2px; background: var(--red); z-index: 2;
  pointer-events: none;
}
.now-line::before {
  content: ''; position: absolute; left: -6px; top: -5px; width: 12px; height: 12px;
  border-radius: 50%; background: var(--red);
}

.event {
  position: absolute; z-index: 1;
  display: flex; flex-direction: column; align-items: flex-start; gap: 1px;
  padding: 4px 8px; overflow: hidden; text-align: left;
  border: 0; border-left: 4px solid var(--c); border-radius: 6px;
  background: var(--c-soft); color: var(--c-text);
  font: inherit; font-size: 12px; cursor: pointer;
  transition: box-shadow .15s, transform .15s;
}
.event:hover { box-shadow: var(--shadow-lg); z-index: 4; }
.event.type-meeting { border: 1px dashed var(--c); border-left: 4px solid var(--c); }
.event.compact { flex-direction: row; align-items: center; gap: 6px; padding-top: 2px; padding-bottom: 2px; }
.ev-title {
  font-weight: 500; color: var(--grey-900); line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.event.compact .ev-title { -webkit-line-clamp: 1; }
.is-cancelled .ev-title { text-decoration: line-through; color: var(--red-text); }
.ev-meta { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.ev-title .sp-badge { height: 16px; padding: 0 6px; font-size: 10px; margin-right: 2px; vertical-align: 1px; }
</style>
