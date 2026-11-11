<script setup>
// Login Page: email + password from Supabase Auth. No sign-up or password reset (out of scope).
// Google-like look: white surface, neutral greys, and only blue, red, yellow and light green as accents.
import { ref } from 'vue'
import { login } from './session'

const props = defineProps({ appName: { type: String, default: 'SClass' } })
const emit = defineEmits(['logged-in'])

const email = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
const tones = ['blue', 'red', 'yellow', 'green']

async function submit() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    const user = await login(email.value.trim(), password.value)
    password.value = ''
    emit('logged-in', user)
  } catch (e) {
    error.value = e.message
    password.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <form class="card" novalidate :aria-busy="busy" @submit.prevent="submit">
      <div class="progress" :class="{ on: busy }" aria-hidden="true"><span v-for="t in tones" :key="t" :class="t"></span></div>

      <p class="wordmark">
        <span class="sr-only">{{ props.appName }}</span>
        <span v-for="(ch, i) in [...props.appName]" :key="i" :class="tones[i % 4]" aria-hidden="true">{{ ch }}</span>
      </p>
      <h1>Sign in</h1>
      <p class="lead">to continue to {{ props.appName }}</p>

      <p v-if="error" class="error" role="alert"><span class="error-icon" aria-hidden="true">!</span>{{ error }}</p>

      <label class="field">
        <span>Email</span>
        <input v-model="email" type="email" name="email" autocomplete="username" required autofocus :disabled="busy" />
      </label>
      <label class="field">
        <span>Password</span>
        <input v-model="password" type="password" name="password" autocomplete="current-password" required :disabled="busy" />
      </label>

      <ul class="roles" aria-label="Who signs in here">
        <li class="blue">Students</li>
        <li class="yellow">Lecturers</li>
        <li class="green">Administrators</li>
      </ul>

      <div class="actions">
        <p class="hint">Can't sign in? Ask an administrator.</p>
        <button class="submit" type="submit" :disabled="busy || !email.trim() || !password">
          {{ busy ? 'Signing in…' : 'Sign in' }}
        </button>
      </div>
    </form>
    <p class="foot">{{ props.appName }} · Class scheduling workspace</p>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500&display=swap');

.login {
  --blue: #1a73e8;   --blue-tint: #e8f0fe;   --blue-ink: #174ea6;
  --red: #d93025;    --red-tint: #fce8e6;    --red-ink: #c5221f;
  --yellow: #fbbc04; --yellow-tint: #fef7e0; --yellow-ink: #8a5300;
  --green: #81c995;  --green-tint: #e6f4ea;  --green-ink: #137333;
  --text: #202124;   --muted: #5f6368;       --line: #dadce0;

  min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 18px; padding: 32px 16px; background: #fff; color: var(--text);
  font-family: Roboto, Arial, sans-serif; font-size: 14px;
}

.card {
  position: relative; overflow: hidden; width: min(450px, 100%);
  padding: 44px 40px 36px; background: #fff;
  border: 1px solid var(--line); border-radius: 8px;
  display: flex; flex-direction: column;
}

/* Four-colour strip along the top; it slides while signing in. */
.progress { position: absolute; inset: 0 0 auto 0; display: flex; height: 4px; }
.progress span { flex: 1; }
.progress .blue { background: var(--blue); }
.progress .red { background: var(--red); }
.progress .yellow { background: var(--yellow); }
.progress .green { background: var(--green); }
.progress.on span { animation: slide 1.2s ease-in-out infinite; }
.progress.on span:nth-child(2) { animation-delay: .15s; }
.progress.on span:nth-child(3) { animation-delay: .3s; }
.progress.on span:nth-child(4) { animation-delay: .45s; }
@keyframes slide { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }

.wordmark { margin: 0 0 18px; text-align: center; font-size: 26px; font-weight: 500; letter-spacing: -.5px; }
.wordmark .blue { color: var(--blue); }
.wordmark .red { color: var(--red); }
.wordmark .yellow { color: var(--yellow); }
.wordmark .green { color: var(--green); }

h1 { margin: 0; text-align: center; font-family: inherit; font-size: 24px; font-weight: 400; letter-spacing: 0; color: var(--text); }
.lead { margin: 8px 0 28px; text-align: center; font-size: 16px; color: var(--text); }

.error {
  display: flex; align-items: flex-start; gap: 10px; margin: 0 0 20px; padding: 10px 14px;
  border-radius: 8px; background: var(--red-tint); color: var(--red-ink); line-height: 1.45;
}
.error-icon {
  flex-shrink: 0; display: grid; place-items: center; width: 18px; height: 18px; margin-top: 1px;
  border-radius: 50%; background: var(--red); color: #fff; font-size: 12px; font-weight: 700;
}

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 18px; }
.field span { font-size: 12px; font-weight: 500; color: var(--muted); }
.field input {
  height: 52px; padding: 0 15px; border: 1px solid #747775; border-radius: 4px;
  font: inherit; font-size: 16px; color: var(--text); background: #fff;
  transition: border-color .15s, box-shadow .15s;
}
.field input:hover:not(:disabled) { border-color: var(--text); }
.field input:focus { outline: none; border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
.field input:disabled { background: #f8f9fa; color: var(--muted); }

.roles { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 30px; padding: 0; }
.roles li { padding: 4px 12px; border-radius: 16px; font-size: 12px; font-weight: 500; }
.roles .blue { background: var(--blue-tint); color: var(--blue-ink); }
.roles .yellow { background: var(--yellow-tint); color: var(--yellow-ink); }
.roles .green { background: var(--green-tint); color: var(--green-ink); }

.actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.hint { margin: 0; font-size: 13px; color: var(--muted); }
.submit {
  flex-shrink: 0; height: 40px; padding: 0 24px; border: 0; border-radius: 20px;
  background: var(--blue); color: #fff; font: inherit; font-weight: 500; letter-spacing: .25px;
  transition: background .15s, box-shadow .15s;
}
.submit:hover:not(:disabled) { background: #1765cc; box-shadow: 0 1px 2px rgba(60, 64, 67, .3), 0 1px 3px 1px rgba(60, 64, 67, .15); }
.submit:focus-visible { outline: 2px solid var(--blue-ink); outline-offset: 2px; }
.submit:disabled { background: #e8eaed; color: #9aa0a6; cursor: not-allowed; opacity: 1; }

.foot { margin: 0; font-size: 12px; color: var(--muted); }

.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}

@media (max-width: 600px) {
  .login { justify-content: flex-start; padding: 0 0 24px; }
  .card { border: 0; border-radius: 0; padding: 40px 24px 28px; }
  .actions { flex-direction: column-reverse; align-items: stretch; }
  .submit { width: 100%; }
  .hint { text-align: center; }
}
@media (prefers-reduced-motion: reduce) {
  .progress.on span { animation: none; }
}
</style>
