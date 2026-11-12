<script setup>
// Second confirmation before a preview is saved: summary, warning, and a required acknowledgement.
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: Boolean,
  saving: Boolean,
  count: { type: Number, default: 0 },
  week: { type: String, default: '' }, // "Week of 16 – 22 Nov 2026"
  intakes: { type: Array, default: () => [] }, // intake codes
})
const emit = defineEmits(['confirm', 'cancel'])

const dialog = ref(null)
const understood = ref(false)
const checkbox = ref(null)

watch(() => props.open, async (open) => {
  await nextTick()
  if (open) {
    understood.value = false
    if (!dialog.value.open) dialog.value.showModal()
    checkbox.value?.focus()
  } else if (dialog.value?.open) {
    dialog.value.close()
  }
})

function cancel() {
  if (!props.saving) emit('cancel')
}
</script>

<template>
  <dialog ref="dialog" class="cd" aria-labelledby="cd-title" aria-describedby="cd-warning" @cancel.prevent="cancel">
    <h2 id="cd-title">Schedule {{ count }} {{ count === 1 ? 'class' : 'classes' }}?</h2>
    <p class="cd-summary">
      {{ week }} · {{ intakes.length }} {{ intakes.length === 1 ? 'intake' : 'intakes' }}: {{ intakes.join(', ') }}
    </p>

    <div id="cd-warning" class="cd-warning" role="note">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" /></svg>
      <div>
        <strong>This cannot be undone.</strong>
        The classes are saved to the database and published straight away to everyone on the system:
        students, lecturers and administrators will see them in their timetables. This page cannot remove them again.
      </div>
    </div>

    <label class="cd-check">
      <input ref="checkbox" v-model="understood" type="checkbox" :disabled="saving" />
      I have reviewed this preview and understand that scheduling it is permanent and visible to everyone.
    </label>

    <div class="cd-actions">
      <button type="button" class="cd-cancel" :disabled="saving" @click="cancel">Cancel</button>
      <button type="button" class="cd-confirm" :disabled="!understood || saving" @click="emit('confirm')">
        {{ saving ? 'Scheduling…' : 'Confirm and schedule' }}
      </button>
    </div>
  </dialog>
</template>

<style scoped>
.cd {
  width: min(520px, calc(100vw - 32px)); box-sizing: border-box; padding: 26px; border: 1px solid #e2e7ef;
  border-radius: 16px; background: #fff; color: #202124; box-shadow: 0 12px 36px rgba(60, 64, 67, .28);
}
.cd::backdrop { background: rgba(32, 33, 36, .4); }
.cd h2 { margin: 0 0 6px; font-size: 22px; font-weight: 500; }
.cd-summary { margin: 0 0 16px; color: #5f6368; font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.cd-warning { display: flex; gap: 12px; padding: 14px; border-radius: 10px; background: #fce8e6; color: #a50e0e; font-size: 14px; line-height: 1.5; }
.cd-warning svg { flex: none; width: 22px; height: 22px; fill: #d93025; }
.cd-warning strong { display: block; }
.cd-check { display: flex; gap: 10px; align-items: flex-start; margin: 18px 0 22px; font-size: 14px; line-height: 1.45; cursor: pointer; }
.cd-check input { flex: none; width: 18px; height: 18px; margin: 1px 0 0; accent-color: #1a73e8; }
.cd-actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.cd button { padding: 10px 18px; border-radius: 8px; font: inherit; font-weight: 600; cursor: pointer; }
.cd button:disabled { cursor: not-allowed; opacity: .55; }
.cd-cancel { border: 1px solid #dadce0; background: #fff; color: #1a73e8; }
.cd-cancel:hover:not(:disabled) { background: #f8f9fa; }
.cd-confirm { border: 0; background: #1a73e8; color: #fff; }
.cd-confirm:hover:not(:disabled) { background: #1765cc; }
.cd button:focus-visible, .cd input:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
</style>
