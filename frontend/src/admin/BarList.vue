<script setup>
// Single-series horizontal bar chart: one row per item, value at the bar end, hover/focus tooltip.
// One series, so no legend; the card title names the measure.
import { computed, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] }, // [{ key, label, value, note?, tip? }]
  unit: { type: String, default: '' },        // e.g. 'students'
  empty: { type: String, default: 'No data to display.' },
})

const max = computed(() => Math.max(1, ...props.items.map(item => item.value)))
const active = ref(null)
</script>

<template>
  <p v-if="!items.length" class="empty">{{ empty }}</p>
  <ul v-else class="bars" role="list">
    <li v-for="item in items" :key="item.key" tabindex="0"
        :aria-label="`${item.label}: ${item.value} ${unit}${item.note ? ', ' + item.note : ''}`"
        @mouseenter="active = item.key" @mouseleave="active = null" @focus="active = item.key" @blur="active = null">
      <span class="label"><strong>{{ item.label }}</strong><small v-if="item.note">{{ item.note }}</small></span>
      <span class="track"><span class="bar" :style="{ width: `${(item.value / max) * 100}%` }"></span></span>
      <span class="value">{{ item.value }}</span>
      <span v-if="active === item.key" class="tip" role="tooltip">
        <strong>{{ item.label }}</strong> · {{ item.value }} {{ unit }}<template v-if="item.tip"><br />{{ item.tip }}</template>
      </span>
    </li>
  </ul>
</template>

<style scoped>
.bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
li { position: relative; display: grid; grid-template-columns: minmax(110px, 30%) 1fr 44px; align-items: center; gap: 12px; padding: 7px 6px; border-radius: 8px; outline: none; }
li:hover, li:focus-visible { background: #f3f6fb; }
li:focus-visible { box-shadow: 0 0 0 2px #4285f4; }
.label { display: flex; flex-direction: column; min-width: 0; font-size: 13px; }
.label strong { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.label small { color: #6b7385; font-size: 12px; }
.track { height: 14px; }
.bar { display: block; height: 100%; min-width: 2px; background: #4285f4; border-radius: 0 4px 4px 0; }
.value { font-size: 13px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
.tip { position: absolute; z-index: 2; left: 30%; bottom: calc(100% - 2px); background: #253047; color: #fff; font-size: 12px; line-height: 1.4; padding: 6px 10px; border-radius: 6px; white-space: nowrap; pointer-events: none; }
.empty { color: #6b7385; }
@media (max-width: 560px) { li { grid-template-columns: 96px 1fr 36px; gap: 8px; } .tip { left: 0; } }
</style>
