<script setup>
// App shell: routing + login. Every page except /login needs a logged-in user;
// each role is sent to its own page (/student, /lecturer, /admin; admins also /admin/schedule).
// The student and lecturer pages themselves are unchanged (owned by their teams).
import { computed, ref, watch } from 'vue'
import { getJson } from './api'
import LoginPage from './auth/LoginPage.vue'
import { loadSession, logout, session } from './auth/session'
import AdminPage from './admin/AdminPage.vue'
import SchedulePage from './admin/SchedulePage.vue'
import LecturerPage from './lecturer/LecturerPage.vue'
import { ROLE_PAGES, landingFor, legacyHashTarget, navigate, path } from './router'
import StudentPage from './student/StudentPage.vue'

const appName = ref('SClass')
const checked = ref(false) // has /api/auth/me been asked yet?
const loadError = ref('')
const loggingOut = ref(false)

getJson('/api/config').then((config) => { appName.value = config.name || 'SClass' }).catch(() => {})

const roleLabel = computed(() => ({ admin: 'Administrator', lecturer: 'Lecturer', student: 'Student' })[session.value?.role] || '')
const page = computed(() => {
  if (!checked.value) return 'loading'
  if (path.value === '/login') return 'login'
  if (session.value && ROLE_PAGES[path.value] === session.value.role) {
    return path.value === '/admin/schedule' ? 'schedule' : session.value.role
  }
  return 'loading' // a redirect is on its way
})

async function resolve() {
  const legacy = legacyHashTarget(window.location.hash)
  if (legacy) return navigate(legacy, { replace: true })
  if (!checked.value) {
    try {
      await loadSession()
      loadError.value = ''
      checked.value = true
    } catch (e) {
      loadError.value = e.message
      return
    }
  }
  const current = path.value
  const user = session.value
  if (current === '/login') {
    if (user) goAfterLogin(user)
    return
  }
  if (!user) {
    const next = ROLE_PAGES[current] ? `?next=${encodeURIComponent(current)}` : ''
    return navigate(`/login${next}`, { replace: true })
  }
  if (ROLE_PAGES[current] !== user.role) navigate(user.home, { replace: true })
}

function goAfterLogin(user) {
  const target = landingFor(user, new URLSearchParams(window.location.search).get('next'))
  // Pages outside this app (the backend-served scheduling page) need a full load.
  if (ROLE_PAGES[target]) navigate(target, { replace: true })
  else window.location.replace(target)
}

async function signOut() {
  loggingOut.value = true
  try { await logout() } finally {
    loggingOut.value = false
    navigate('/login', { replace: true })
  }
}

watch(path, resolve, { immediate: true })
window.addEventListener('hashchange', resolve)
watch([page, appName], ([name, app]) => {
  const titles = { login: 'Log in', student: 'Student timetable', lecturer: 'Lecturer timetable', admin: 'Admin', schedule: 'Schedule classes' }
  document.title = titles[name] ? `${app} · ${titles[name]}` : app
}, { immediate: true })
</script>

<template>
  <div v-if="loadError" class="shell-state" role="alert">
    <p>{{ loadError }}</p>
    <button type="button" @click="resolve">Try again</button>
  </div>
  <div v-else-if="page === 'loading'" class="shell-state" aria-busy="true">Loading…</div>
  <LoginPage v-else-if="page === 'login'" :app-name="appName" @logged-in="goAfterLogin" />
  <template v-else>
    <div class="session-bar">
      <span>Signed in as <strong>{{ session.name || session.email }}</strong> · {{ roleLabel }}</span>
      <button type="button" :disabled="loggingOut" @click="signOut">{{ loggingOut ? 'Logging out…' : 'Log out' }}</button>
    </div>
    <StudentPage v-if="page === 'student'" :student-code="session.code || ''" />
    <LecturerPage v-else-if="page === 'lecturer'" :app-name="appName" />
    <AdminPage v-else-if="page === 'admin'" />
    <SchedulePage v-else-if="page === 'schedule'" />
  </template>
</template>

<style scoped>
.shell-state {
  min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  color: #5f6368; background: #fff; font-family: Roboto, Arial, sans-serif;
}
.shell-state button, .session-bar button {
  border: 1px solid #d8dfd2; border-radius: 6px; background: #fff; color: #214f40; padding: 4px 12px; font-size: 12px;
}
.session-bar {
  display: flex; align-items: center; justify-content: flex-end; gap: 14px;
  padding: 6px 24px; background: #153e37; color: #eaf2e9; font-size: 12px;
}
.session-bar strong { font-weight: 600; }
</style>
