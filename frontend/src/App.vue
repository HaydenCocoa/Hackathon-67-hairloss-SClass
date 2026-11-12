<script setup>
// App shell: routing + login. Every page except /login needs a logged-in user;
// each role is sent to its own page (/student, /lecturer, /admin).
// The student and lecturer pages themselves are unchanged (owned by their teams).
import { computed, ref, watch } from 'vue'
import { getJson } from './api'
import LoginPage from './auth/LoginPage.vue'
import { loadSession, logout, session } from './auth/session'
import AdminPage from './admin/AdminPage.vue'
import LecturerPage from './lecturer/LecturerPage.vue'
import { ROLE_PAGES, landingFor, legacyHashTarget, navigate, path } from './router'
import StudentPage from './student/StudentPage.vue'
import AdminPage from './admin/AdminPage.vue'

const appName = ref('SClass')
const checked = ref(false) // has /api/auth/me been asked yet?
const loadError = ref('')
const loggingOut = ref(false)

getJson('/api/config').then((config) => { appName.value = config.name || 'SClass' }).catch(() => {})

const roleLabel = computed(() => ({ admin: 'Administrator', lecturer: 'Lecturer', student: 'Student' })[session.value?.role] || '')
const page = computed(() => {
  if (!checked.value) return 'loading'
  if (path.value === '/login') return 'login'
  if (session.value && ROLE_PAGES[path.value] === session.value.role) return session.value.role
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
  const titles = { login: 'Log in', student: 'Student timetable', lecturer: 'Lecturer timetable', admin: 'Admin' }
  document.title = titles[name] ? `${app} · ${titles[name]}` : app
}, { immediate: true })
</script>

<template>
Admin
  <AdminPage v-if="route.startsWith('#/admin')" />
  <StudentPage v-else-if="isStudentPage" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="SClass home"><span class="brand-icon">S<span>•</span></span>{{ config?.name || 'SClass' }}</a>
      <p class="nav-label">WORKSPACE</p>
      <a class="nav-item active" href="#main" aria-current="page"><span aria-hidden="true">▦</span> Main menu</a>
      <a class="nav-item" href="#/admin">▦ Admin workspace</a>
      <a class="nav-item" href="#/student"><span aria-hidden="true">▤</span> Student timetable</a>
      <div class="sidebar-note"><span class="small-dot"></span> A little structure.<br />More room to learn.</div>
      <div class="sidebar-footer">SCLASS <span> / </span> MVP 0.1</div>
    </aside>

    <div class="workspace">
      <header class="topbar"><span>Workspace <span class="slash">/</span> <strong>Main menu</strong></span><span class="environment">{{ config?.environment || 'Starting up' }}</span></header>
      <main id="main">
        <div class="page-heading"><p class="eyebrow">YOUR WORKSPACE, READY TO GROW</p><h1>Welcome to {{ config?.name || 'SClass' }}<span>.</span></h1><p>{{ config?.description || 'Your classroom scheduling workspace.' }}</p></div>

        <div v-if="backend === 'offline' || configError" class="error-banner" role="alert">
          <span>{{ configError ? 'Startup configuration could not be loaded.' : 'The backend is currently unavailable.' }} Check that FastAPI is running.</span>
          <button class="text-button" @click="loadApp">Retry connection ↗</button>
        </div>

        <section class="status-strip" aria-label="Workspace status" aria-live="polite">
          <div><span class="status-label">BACKEND</span><span class="status-value"><i :class="['dot', { good: backend === 'online' }]" />{{ backend === 'online' ? 'Online' : backend === 'offline' ? 'Offline' : 'Checking…' }}</span></div>
          <div><span class="status-label">CONFIGURATION</span><span class="status-value"><i :class="['dot', { good: config && !configError }]" />{{ configError ? 'Unavailable' : config ? 'Loaded' : 'Loading…' }}</span></div>
          <div><span class="status-label">DATABASE</span><span class="status-value"><i :class="['dot', { good: database?.status === 'connected' }]" />{{ checkingDatabase ? 'Checking…' : databaseLabel }}</span></div>
        </section>

        <div class="section-heading"><h2>Start here</h2><span>THE ESSENTIALS</span></div>
        <div class="menu-grid">
          <section class="menu-card database-card">
            <div class="card-top"><span class="card-icon" aria-hidden="true">⌁</span><span class="card-number">01</span></div>
            <h3>Database connection</h3><p>Make sure your workspace can reach Supabase before you get started.</p>
            <div class="connection-result" aria-live="polite" aria-atomic="true">
              <template v-if="database"><strong :class="{ success: database.status === 'connected' }">{{ databaseLabel }}<span v-if="database.latency_ms != null"> · {{ database.latency_ms }} ms</span></strong><p>{{ database.message }}</p><small v-if="checkedTime">Last checked at {{ checkedTime }}</small></template>
              <template v-else><span class="result-placeholder">A quick, read-only check. Your data stays as it is.</span></template>
            </div>
            <button class="primary-button" :disabled="checkingDatabase" @click="testDatabase"><span>{{ checkingDatabase ? 'Checking connection…' : database ? 'Check again' : 'Test connection' }}</span><span aria-hidden="true">↗</span></button>
          </section>

          <section class="menu-card">
            <div class="card-top"><span class="card-icon neutral" aria-hidden="true">{ }</span><span class="card-number">02</span></div>
            <h3>Explore the API</h3><p>Open the interactive API reference to explore the endpoints behind your workspace.</p>
            <div class="api-summary"><span>FastAPI</span><span class="api-line"></span><span>HTTP / JSON</span></div>
            <a class="secondary-button" href="/docs" target="_blank" rel="noopener noreferrer"><span>Open API reference</span><span aria-hidden="true">↗</span></a>
          </section>
        </div>

        <div class="future-note"><span class="future-icon" aria-hidden="true">✧</span><div><strong>A foundation for what’s next.</strong><p>Scheduling and personal preferences will arrive in a future release.</p></div><span class="future-tag">ON THE HORIZON</span></div>
        <footer class="page-footer"><span>Built for better class days.</span><span>{{ config?.name || 'SClass' }} · Early preview</span></footer>
      </main>
    </div>

  <div v-if="loadError" class="shell-state" role="alert">
    <p>{{ loadError }}</p>
    <button type="button" @click="resolve">Try again</button>
 main
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
