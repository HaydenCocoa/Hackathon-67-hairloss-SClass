<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJson } from './api'
import StudentPage from './student/StudentPage.vue'

// Simple hash routes: #/student opens the Student Page.
const route = ref(window.location.hash)
window.addEventListener('hashchange', () => { route.value = window.location.hash })
const isStudentPage = computed(() => route.value.startsWith('#/student'))
watch(isStudentPage, (student) => {
  document.title = `${config.value?.name || 'SClass'} · ${student ? 'Student timetable' : 'Main menu'}`
})

const config = ref(null)
const backend = ref('checking')
const configError = ref(false)
const database = ref(null)
const checkingDatabase = ref(false)
const checkedTime = computed(() => database.value?.checked_at
  ? new Date(database.value.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  : null)
const databaseLabel = computed(() => ({
  connected: 'Connected', not_configured: 'Setup needed', error: 'Connection failed', timeout: 'Timed out',
})[database.value?.status] || 'Not checked')

async function loadApp() {
  backend.value = 'checking'
  configError.value = false
  const [health, settings] = await Promise.allSettled([
    getJson('/api/health'), getJson('/api/config'),
  ])
  backend.value = health.status === 'fulfilled' && health.value.status === 'ok' ? 'online' : 'offline'
  if (settings.status === 'fulfilled') {
    config.value = settings.value
    document.title = `${settings.value.name} · ${isStudentPage.value ? 'Student timetable' : 'Main menu'}`
  } else {
    configError.value = true
  }
}

async function testDatabase() {
  checkingDatabase.value = true
  try {
    database.value = await getJson('/api/health/database')
  } catch {
    database.value = { status: 'error', message: 'Could not complete the check. Make sure the backend is running, then try again.' }
  } finally {
    checkingDatabase.value = false
  }
}

onMounted(loadApp)
</script>

<template>
  <StudentPage v-if="isStudentPage" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="SClass home"><span class="brand-icon">S<span>•</span></span>{{ config?.name || 'SClass' }}</a>
      <p class="nav-label">WORKSPACE</p>
      <a class="nav-item active" href="#main" aria-current="page"><span aria-hidden="true">▦</span> Main menu</a>
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
  </div>
</template>
