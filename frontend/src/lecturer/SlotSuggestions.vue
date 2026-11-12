<script setup>
// The recommended time slots as a group of radio cards. Order is the backend's ranking (best first).
import { formatDate, formatTime } from './time'
import { isRequestedSlot, slotKey } from './session'

defineProps({
  slots: { type: Array, required: true }, // [{ session_date, start_time, end_time, room_id, room_name, building, capacity }]
  modelValue: { type: String, default: '' }, // the picked slot's key
  request: { type: Object, default: null }, // { date, time }: what the lecturer asked for
})
defineEmits(['update:modelValue'])
</script>

<template>
  <fieldset class="lc-slots">
    <legend class="lc-sr">Recommended times</legend>
    <label
      v-for="(slot, i) in slots"
      :key="slotKey(slot)"
      class="lc-slotpick"
      :class="{ 'is-picked': modelValue === slotKey(slot) }"
    >
      <input
        class="lc-sr"
        type="radio"
        name="lc-slot"
        :value="slotKey(slot)"
        :checked="modelValue === slotKey(slot)"
        @change="$emit('update:modelValue', slotKey(slot))"
      />
      <span class="lc-slotpick-day">
        <span class="lc-slotpick-dow">{{ formatDate(slot.session_date, { weekday: 'short' }) }}</span>
        <span class="lc-slotpick-dom">{{ formatDate(slot.session_date, { day: 'numeric' }) }}</span>
        <span class="lc-slotpick-mon">{{ formatDate(slot.session_date, { month: 'short' }) }}</span>
      </span>
      <span class="lc-slotpick-body">
        <span class="lc-slotpick-time">{{ formatTime(slot.start_time) }} – {{ formatTime(slot.end_time) }}</span>
        <span class="lc-slotpick-room">{{ slot.room_name }} · {{ slot.building }} · seats {{ slot.capacity }}</span>
      </span>
      <span v-if="isRequestedSlot(slot, request)" class="lc-chip lc-chip-good">Your requested time</span>
      <span v-else-if="i === 0" class="lc-chip lc-chip-close">Closest to your request</span>
    </label>
  </fieldset>
</template>
