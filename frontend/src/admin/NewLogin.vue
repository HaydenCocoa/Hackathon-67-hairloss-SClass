<script setup>
// Shows a just-created login (email + temporary password) once, so the admin can pass it on.
// The password is not stored anywhere and cannot be shown again after this box is closed.
import { ref } from 'vue'

const props = defineProps({ login: { type: Object, required: true } })
defineEmits(['close'])
const copied = ref('')

async function copy() {
  try {
    await navigator.clipboard.writeText(`Email: ${props.login.email}\nTemporary password: ${props.login.temporary_password}`)
    copied.value = 'Copied.'
  } catch { copied.value = 'Copy failed; select the text instead.' }
}
</script>

<template>
  <div class="new-login" role="region" aria-label="New login details">
    <strong>Login created for {{ login.name }}</strong>
    <dl>
      <dt>Email</dt><dd>{{ login.email }}</dd>
      <dt>Temporary password</dt><dd><code>{{ login.temporary_password }}</code></dd>
    </dl>
    <p class="hint">Shown only once. Pass it on securely; it cannot be shown again.</p>
    <div><button type="button" @click="copy">Copy</button> <button type="button" @click="$emit('close')">Done</button> <span class="hint">{{ copied }}</span></div>
  </div>
</template>

<style scoped>
.new-login{margin-top:16px;padding:14px 16px;border:1px solid #a8dab5;background:#f1f9f3;border-radius:12px}
.new-login dl{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;margin:10px 0 4px}
.new-login dt{font-size:13px;color:#5b6477}
.new-login dd{margin:0;word-break:break-all}
.new-login code{font-size:15px;font-weight:600;user-select:all}
</style>
