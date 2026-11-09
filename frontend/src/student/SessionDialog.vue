<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { fmtDateTime, fmtDayLong, fmtTime } from './time'

const props = defineProps({ event: { type: Object, required: true } })
const emit = defineEmits(['close'])
const closeBtn = ref(null)

const onKey = (e) => { if (e.key === 'Escape') emit('close') }
onMounted(() => { document.addEventListener('keydown', onKey); closeBtn.value?.focus() })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

const typeLabel = { lecture: 'Lecture', tutorial: 'Tutorial', lab: 'Lab', others: 'Class', meeting: 'Meeting' }
const roomText = (r) => (r ? `${r.name}, ${r.building}` : null)
const change = props.event.change
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div
      :class="['dialog', `type-${event.type}`, { 'is-cancelled': event.cancelled }]"
      role="dialog" aria-modal="true" :aria-label="event.title"
    >
      <div class="strip"></div>
      <div class="head">
        <span class="sp-badge type-chip">{{ typeLabel[event.type] || 'Class' }}</span>
        <span v-if="event.cancelled" class="sp-badge cancelled">Cancelled</span>
        <span v-else-if="event.moved" class="sp-badge moved">Rescheduled</span>
        <button ref="closeBtn" class="sp-icon-btn close" type="button" aria-label="Close" @click="emit('close')">×</button>
      </div>

      <h2>{{ event.title }}</h2>
      <p class="code">{{ event.subtitle }}</p>

      <dl>
        <div><dt>🕘</dt><dd>{{ fmtDayLong(event.start) }}<br /><span class="muted">{{ fmtTime(event.start) }} – {{ fmtTime(event.end) }}</span></dd></div>
        <div><dt>📍</dt><dd>{{ event.place }}</dd></div>
        <div v-if="event.lecturer"><dt>👤</dt><dd>{{ event.lecturer }}</dd></div>
        <div v-if="event.intake_code"><dt>👥</dt><dd>{{ event.intake_code }} · Group {{ event.group_number }}</dd></div>
      </dl>

      <div v-if="change" :class="['change', change.action]">
        <strong v-if="change.action === 'cancel'">This class has been cancelled</strong>
        <strong v-else>This class has been rescheduled</strong>
        <p v-if="change.action === 'reschedule' && change.old_starts_at">
          Was: <s>{{ fmtDateTime(new Date(change.old_starts_at)) }}<template v-if="change.old_room"> · {{ roomText(change.old_room) }}</template></s>
          <br />Now: {{ fmtDateTime(event.start) }} · {{ event.place }}
        </p>
        <p v-if="change.reason" class="reason">“{{ change.reason }}”</p>
        <small>Updated {{ fmtDateTime(new Date(change.created_at)) }}</small>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50; background: rgba(32, 33, 36, .45);
  display: grid; place-items: center; padding: 16px;
}
.dialog {
  position: relative; width: min(440px, 100%); max-height: 90vh; overflow: auto;
  background: #fff; border-radius: 16px; box-shadow: var(--shadow-lg); padding: 20px 24px 24px;
}
.strip { position: absolute; inset: 0 0 auto 0; height: 6px; background: var(--c); }
.head { display: flex; align-items: center; gap: 8px; margin: 4px 0 12px; }
.type-chip { background: var(--c-soft); color: var(--c-text); }
.type-meeting .type-chip { background: var(--green-soft); }
.close { margin-left: auto; font-size: 26px; }
h2 { font-size: 22px; font-weight: 400; line-height: 1.3; }
.is-cancelled h2 { text-decoration: line-through; color: var(--red-text); }
.code { margin: 4px 0 16px; color: var(--grey-700); }
dl { margin: 0; display: grid; gap: 12px; }
dl div { display: grid; grid-template-columns: 28px 1fr; align-items: start; }
dt { font-size: 16px; line-height: 1.4; }
dd { margin: 0; }
.muted { color: var(--grey-700); }
.change {
  margin-top: 18px; padding: 12px 14px; border-radius: 10px;
  background: var(--yellow-soft); border: 1px solid #fde293;
}
.change.cancel { background: var(--red-soft); border-color: #f6aea9; }
.change strong { display: block; margin-bottom: 4px; }
.change.cancel strong { color: var(--red-text); }
.change p { margin: 4px 0; }
.reason { font-style: italic; color: var(--grey-700); }
.change small { color: var(--grey-700); }
</style>
