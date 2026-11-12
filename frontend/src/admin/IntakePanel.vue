<script setup>
// Left panel of /admin/schedule: the teaching week and the intakes to schedule (checkboxes).
import { computed, ref } from 'vue'
import { addDays, mondayOf, weekLabel } from './roomCalendar'

const props = defineProps({
  intakes: { type: Array, default: () => [] }, // [{ id, intake_code, max_group }]
  selected: { type: Array, default: () => [] }, // ticked intake ids (owned by the page)
  loading: Boolean,
  error: { type: String, default: '' },
  disabled: Boolean, // while a preview is generated or saved
})
const week = defineModel('week', { type: String, required: true })
// The page applies each change to its own list straight away, so quick successive clicks are never lost.
const emit = defineEmits(['retry', 'toggle', 'add', 'clear'])

const search = ref('')
const sorted = computed(() => [...props.intakes].sort((a, b) => a.intake_code.localeCompare(b.intake_code, 'en', { numeric: true })))
const shown = computed(() => {
  const text = search.value.trim().toLowerCase()
  return text ? sorted.value.filter((intake) => intake.intake_code.toLowerCase().includes(text)) : sorted.value
})
const chosen = computed(() => new Set(props.selected))
const allShownChosen = computed(() => shown.value.length > 0 && shown.value.every((intake) => chosen.value.has(intake.id)))

function selectShown() {
  emit('add', shown.value.map((intake) => intake.id))
}

function pickWeek(value) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) week.value = mondayOf(value)
}
</script>

<template>
  <div class="ip">
    <section class="ip-block" aria-labelledby="ip-week">
      <h2 id="ip-week">Teaching week</h2>
      <div class="ip-week">
        <button type="button" class="ip-icon" aria-label="Previous week" :disabled="disabled" @click="week = addDays(week, -7)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z" /></svg>
        </button>
        <strong aria-live="polite">{{ weekLabel(week) }}</strong>
        <button type="button" class="ip-icon" aria-label="Next week" :disabled="disabled" @click="week = addDays(week, 7)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.6 16.6 10 18l6-6-6-6-1.4 1.4 4.6 4.6z" /></svg>
        </button>
      </div>
      <label class="ip-date">Jump to a date
        <input type="date" :value="week" :disabled="disabled" @change="pickWeek($event.target.value)" />
      </label>
      <p class="ip-hint">Weeks run Monday to Sunday. Classes are only placed in opening hours (Mon–Fri).</p>
    </section>

    <section class="ip-block ip-intakes" aria-labelledby="ip-intakes">
      <div class="ip-title">
        <h2 id="ip-intakes">Intakes</h2>
        <span class="ip-count">{{ selected.length }} of {{ intakes.length }} selected</span>
      </div>
      <p class="ip-hint">Tick the intakes to schedule. They are scheduled together, so they never clash with each other; existing classes stay fixed.</p>
      <input v-model="search" class="ip-search" type="search" placeholder="Search intake code" aria-label="Search intakes" />
      <div class="ip-bulk">
        <button type="button" class="ip-link" :disabled="disabled || allShownChosen || !shown.length" @click="selectShown()">
          Select {{ search.trim() ? 'shown' : 'all' }}
        </button>
        <button type="button" class="ip-link" :disabled="disabled || !selected.length" @click="emit('clear')">Clear</button>
      </div>

      <p v-if="loading" class="ip-state" aria-busy="true">Loading intakes…</p>
      <p v-else-if="error" class="ip-state ip-error" role="alert">
        {{ error }} <button type="button" class="ip-link" @click="$emit('retry')">Try again</button>
      </p>
      <p v-else-if="!intakes.length" class="ip-state">No intakes in the database yet.</p>
      <p v-else-if="!shown.length" class="ip-state">No intake matches "{{ search }}".</p>
      <ul v-else class="ip-list">
        <li v-for="intake in shown" :key="intake.id">
          <label class="ip-item" :class="{ 'is-on': chosen.has(intake.id) }">
            <input
              type="checkbox" :checked="chosen.has(intake.id)" :disabled="disabled"
              @change="emit('toggle', intake.id, $event.target.checked)"
            />
            <span class="ip-code">{{ intake.intake_code }}</span>
            <span class="ip-groups">{{ intake.max_group }} {{ intake.max_group === 1 ? 'group' : 'groups' }}</span>
          </label>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.ip { display: flex; flex-direction: column; gap: 22px; color: #202124; }
.ip h2 { margin: 0; font-size: 15px; font-weight: 600; }
.ip-block { display: flex; flex-direction: column; gap: 10px; }
.ip-hint { margin: 0; color: #5f6368; font-size: 13px; line-height: 1.45; }
.ip button { font: inherit; cursor: pointer; }
.ip button:disabled { cursor: not-allowed; opacity: .5; }
.ip-week { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 6px; border: 1px solid #e2e7ef; border-radius: 10px; }
.ip-week strong { font-weight: 500; text-align: center; }
.ip-icon { display: grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%; background: transparent; }
.ip-icon svg { width: 22px; height: 22px; fill: #3c4043; }
.ip-icon:hover:not(:disabled) { background: #f1f3f4; }
.ip-date { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600; color: #3c4043; }
.ip-date input, .ip-search {
  box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid #cdd5e0; border-radius: 8px;
  background: #fff; color: #202124; font: inherit; font-weight: 400;
}
.ip-title { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.ip-count { color: #1a73e8; font-size: 13px; font-weight: 600; }
.ip-bulk { display: flex; gap: 14px; }
.ip-link { padding: 0; border: 0; background: none; color: #1a73e8; font-weight: 600; font-size: 13px; }
.ip-link:hover:not(:disabled) { text-decoration: underline; }
.ip-state { margin: 0; padding: 10px 12px; border-radius: 8px; background: #f8f9fa; color: #5f6368; font-size: 13px; }
.ip-error { background: #fce8e6; color: #b3261e; }
.ip-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.ip-item {
  display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; padding: 9px 10px;
  border: 1px solid transparent; border-radius: 8px; cursor: pointer;
}
.ip-item:hover { background: #f8f9fa; }
.ip-item.is-on { background: #e8f0fe; border-color: #d2e3fc; }
.ip-item input { width: 18px; height: 18px; margin: 0; accent-color: #1a73e8; cursor: pointer; }
.ip-code { font-weight: 500; overflow-wrap: anywhere; }
.ip-groups { color: #5f6368; font-size: 12px; white-space: nowrap; }
button:focus-visible, input:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
</style>
