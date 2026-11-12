<script setup>
// Shown instead of the user's own page until they replace the temporary password an
// administrator created for them. The backend blocks every other page and API meanwhile.
import { computed, ref } from 'vue'
import { PASSWORD_MAX, PASSWORD_MIN, changePassword, passwordProblem } from './session'

const props = defineProps({ appName: { type: String, default: 'SClass' }, user: { type: Object, required: true } })
const emit = defineEmits(['changed', 'expired'])

const current = ref('')
const next = ref('')
const confirm = ref('')
const show = ref(false)
const busy = ref(false)
const error = ref('')
const problem = computed(() => passwordProblem(current.value, next.value, confirm.value))

async function submit() {
  if (busy.value) return
  error.value = problem.value
  if (error.value) return
  busy.value = true
  try {
    const user = await changePassword(current.value, next.value)
    emit('changed', user)
  } catch (e) {
    if (e.code === 'AUTH_REQUIRED') return emit('expired')
    error.value = e.message
  } finally {
    current.value = next.value = confirm.value = ''
    busy.value = false
  }
}
</script>

<template>
  <div class="change">
    <form class="card" novalidate :aria-busy="busy" @submit.prevent="submit">
      <p class="brand">{{ props.appName }}</p>
      <h1>Choose a new password</h1>
      <p class="lead">Hi {{ user.name || user.email }}. You signed in with a temporary password, so set your own before continuing.</p>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <input type="email" name="email" autocomplete="username" :value="user.email" hidden readonly />
      <label class="field"><span>Current (temporary) password</span>
        <input v-model="current" :type="show ? 'text' : 'password'" autocomplete="current-password" required :disabled="busy" />
      </label>
      <label class="field"><span>New password</span>
        <input v-model="next" :type="show ? 'text' : 'password'" autocomplete="new-password" required
               :minlength="PASSWORD_MIN" :maxlength="PASSWORD_MAX" aria-describedby="password-rules" :disabled="busy" />
      </label>
      <label class="field"><span>Confirm new password</span>
        <input v-model="confirm" :type="show ? 'text' : 'password'" autocomplete="new-password" required :disabled="busy" />
      </label>
      <p id="password-rules" class="hint">At least {{ PASSWORD_MIN }} characters, different from the temporary one. A longer phrase is stronger.</p>
      <label class="show"><input v-model="show" type="checkbox" /> Show passwords</label>

      <button class="submit" type="submit" :disabled="busy || !current || !next || !confirm">
        {{ busy ? 'Saving…' : 'Change password' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.change {
  min-height: calc(100vh - 32px); display: flex; align-items: center; justify-content: center;
  padding: 32px 16px; box-sizing: border-box; background: #fff; color: #202124; font-family: Roboto, Arial, sans-serif; font-size: 14px;
}
.card { width: min(450px, 100%); padding: 40px; border: 1px solid #dadce0; border-radius: 8px; border-top: 4px solid #1a73e8; display: flex; flex-direction: column; box-sizing: border-box; }
.brand { margin: 0 0 12px; text-align: center; font-size: 20px; font-weight: 500; color: #1a73e8; }
h1 { margin: 0; text-align: center; font-size: 24px; font-weight: 400; }
.lead { margin: 8px 0 24px; text-align: center; color: #5f6368; line-height: 1.5; }
.error { margin: 0 0 18px; padding: 10px 14px; border-radius: 8px; background: #fce8e6; color: #c5221f; line-height: 1.45; }
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.field span { font-size: 12px; font-weight: 500; color: #5f6368; }
.field input { height: 48px; padding: 0 14px; border: 1px solid #747775; border-radius: 4px; font: inherit; font-size: 16px; }
.field input:focus { outline: none; border-color: #1a73e8; box-shadow: inset 0 0 0 1px #1a73e8; }
.hint { margin: 0 0 12px; font-size: 13px; color: #5f6368; }
.show { display: flex; align-items: center; gap: 8px; margin-bottom: 24px; font-size: 13px; color: #5f6368; }
.submit { align-self: flex-end; height: 40px; padding: 0 24px; border: 0; border-radius: 20px; background: #1a73e8; color: #fff; font: inherit; font-weight: 500; cursor: pointer; }
.submit:disabled { background: #e8eaed; color: #9aa0a6; cursor: not-allowed; }
@media (max-width: 600px) { .card { border: 0; padding: 32px 8px; } .submit { align-self: stretch; } }
</style>
