<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api'
import './admin.css'

// Reuse the Supabase session created by the application's existing login flow.
// Supabase JS stores its session under a key ending in "-auth-token" by default.
const token = ref(findExistingAccessToken())
const devBypass = ref(false) // true when the backend reports the local dev bypass is on
const admin = ref({ full_name: 'Administrator' })
const sessionReady = ref(false)
const page = ref('intakes')
const loading = ref(false)
const error = ref('')
const notice = ref('')
const intakes = ref([])
const search = ref('')
const modalOpen = ref(false)
const editing = ref(null)
const form = ref({ intake_code: '', max_group: 1 })
const saving = ref(false)
const deleting = ref(null)
const schedule = ref([])
const scheduleLoading = ref(false)
const intakeFilter = ref('')
const startDate = ref('')
const endDate = ref('')

function findExistingAccessToken() {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i)
      if (!key || !key.endsWith('-auth-token')) continue
      try {
        const session = JSON.parse(storage.getItem(key) || '{}')
        if (session.access_token) return session.access_token
      } catch { /* Ignore unrelated or malformed storage entries. */ }
    }
  }
  // Also support an app-level session token if the existing login flow exposes one.
  return window.localStorage.getItem('sclass.accessToken') || ''
}

const filteredIntakes = computed(() => {
  const q = search.value.trim().toLowerCase()
  return intakes.value.filter(x => !q || x.intake_code.toLowerCase().includes(q))
})
const dateRangeLabel = computed(() => startDate.value && endDate.value
  ? `${new Date(`${startDate.value}T00:00:00`).toLocaleDateString()} – ${new Date(`${endDate.value}T00:00:00`).toLocaleDateString()}`
  : 'Select a date range')

function localDate(d) {
  const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
  return x.toISOString().slice(0, 10)
}
function setDefaultDates() {
  const now = new Date()
  const monday = new Date(now)
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7))
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  startDate.value = localDate(monday)
  endDate.value = localDate(sunday)
}
function clearMessages() { error.value = ''; notice.value = '' }

async function loadIntakes() {
  loading.value = true
  clearMessages()
  try { intakes.value = await apiRequest('/api/admin/intakes', { token: token.value }) }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}
function openCreate() {
  editing.value = null
  form.value = { intake_code: '', max_group: 1 }
  clearMessages()
  modalOpen.value = true
}
function openEdit(item) {
  editing.value = item
  form.value = { intake_code: item.intake_code, max_group: item.max_group }
  clearMessages()
  modalOpen.value = true
}
async function saveIntake() {
  saving.value = true
  clearMessages()
  try {
    const body = { intake_code: form.value.intake_code.trim().toUpperCase(), max_group: Number(form.value.max_group) }
    if (!body.intake_code || !Number.isInteger(body.max_group) || body.max_group < 1) throw new Error('Enter an intake code and a valid maximum group.')
    if (editing.value) {
      await apiRequest(`/api/admin/intakes/${editing.value.id}`, { method: 'PATCH', body, token: token.value })
      notice.value = 'Intake updated successfully.'
    } else {
      await apiRequest('/api/admin/intakes', { method: 'POST', body, token: token.value })
      notice.value = 'Intake created successfully.'
    }
    modalOpen.value = false
    await loadIntakes()
  } catch (e) { error.value = e.message }
  finally { saving.value = false }
}
async function deleteIntake(item) {
  if (!window.confirm(`Delete intake ${item.intake_code}? This cannot be undone.`)) return
  deleting.value = item.id
  clearMessages()
  try {
    await apiRequest(`/api/admin/intakes/${item.id}`, { method: 'DELETE', token: token.value })
    notice.value = `${item.intake_code} was deleted.`
    await loadIntakes()
  } catch (e) { error.value = e.message }
  finally { deleting.value = null }
}
async function loadSchedule() {
  if (!startDate.value || !endDate.value) return
  if (endDate.value < startDate.value) { error.value = 'End date must be on or after start date.'; return }
  scheduleLoading.value = true
  clearMessages()
  try {
    const start = new Date(`${startDate.value}T00:00:00`).toISOString()
    const end = new Date(`${endDate.value}T23:59:59.999`).toISOString()
    const params = new URLSearchParams({ start, end })
    if (intakeFilter.value) params.set('intake_id', intakeFilter.value)
    schedule.value = await apiRequest(`/api/admin/timetable?${params}`, { token: token.value })
  } catch (e) { error.value = e.message }
  finally { scheduleLoading.value = false }
}
function fmtDate(value) {
  return new Date(value).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}
function fmtTime(value) {
  return new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

onMounted(async () => {
  setDefaultDates()
  try { devBypass.value = !!(await apiRequest('/api/admin/dev-bypass')).enabled } catch { /* backend offline */ }
  sessionReady.value = true
  if (token.value || devBypass.value) {
    await loadIntakes()
  } else {
    error.value = 'Please sign in through the main application before accessing the admin workspace.'
  }
})
</script>

<template>
  <div v-if="!token && !devBypass && sessionReady" class="admin-session-notice">
    <div class="admin-session-card">
      <a href="#/" class="admin-brand"><span class="google-mark"><i></i><i></i><i></i><i></i></span>SClass</a>
      <p class="admin-eyebrow">ADMIN WORKSPACE</p>
      <h1>Sign-in required</h1>
      <p class="muted">Use the existing application login to access administration. This page does not provide a separate login.</p>
      <a href="#/" class="g-btn primary">Return to main application <span>→</span></a>
    </div>
  </div>

  <div v-else-if="token || devBypass" class="admin-shell">
    <aside class="admin-sidebar">
      <a href="#/" class="admin-brand"><span class="google-mark"><i></i><i></i><i></i><i></i></span>SClass</a>
      <div class="admin-side-caption">ADMIN WORKSPACE</div>
      <button :class="['admin-nav', { active: page === 'intakes' }]" @click="page = 'intakes'"><span class="nav-symbol blue">▦</span> Intake management</button>
      <button :class="['admin-nav', { active: page === 'timetable' }]" @click="page = 'timetable'"><span class="nav-symbol green">▤</span> University timetable</button>
      <div class="admin-side-bottom"><div class="admin-user"><span class="avatar">A</span><span><strong>Admin workspace</strong><small>Signed in via main application</small></span></div></div>
    </aside>

    <section class="admin-workspace">
      <header class="admin-topbar">
        <div><a href="#/">SClass</a><span>/</span><strong>{{ page === 'intakes' ? 'Intake management' : 'University timetable' }}</strong></div>
        <span class="secure-label"><span></span> {{ token ? 'AUTHENTICATED SESSION' : 'DEV BYPASS (LOCAL ONLY)' }}</span>
      </header>
      <main class="admin-main">
        <div v-if="error" class="admin-alert error" role="alert">{{ error }} <button @click="error = ''">Dismiss</button></div>
        <div v-if="notice" class="admin-alert success" role="status">{{ notice }} <button @click="notice = ''">Dismiss</button></div>

        <template v-if="page === 'intakes'">
          <div class="admin-heading-row">
            <div><p class="admin-eyebrow">ACADEMIC CONFIGURATION</p><h1>Intake management</h1><p class="muted">Create and manage student intakes across the university.</p></div>
            <button class="g-btn primary" @click="openCreate"><span>＋</span> Add intake</button>
          </div>
          <div class="admin-stats">
            <div class="admin-stat"><span class="stat-dot blue"></span><div><strong>{{ intakes.length }}</strong><small>Total intakes</small></div></div>
            <div class="admin-stat"><span class="stat-dot yellow"></span><div><strong>{{ intakes.reduce((n, x) => n + x.max_group, 0) }}</strong><small>Available groups</small></div></div>
            <div class="admin-stat"><span class="stat-dot green"></span><div><strong>{{ intakes.filter(x => x.max_group > 1).length }}</strong><small>Multi-group intakes</small></div></div>
          </div>
          <section class="admin-panel">
            <div class="panel-head"><div><h2>All intakes</h2><p>Manage intake codes and their maximum group count.</p></div><button class="g-btn subtle" @click="loadIntakes" :disabled="loading">↻ Refresh</button></div>
            <div class="table-toolbar"><label class="search-box"><span>⌕</span><input v-model="search" placeholder="Search intake code…" /></label><span class="record-count">{{ filteredIntakes.length }} records</span></div>
            <div class="table-wrap">
              <table><thead><tr><th>INTAKE CODE</th><th>MAXIMUM GROUPS</th><th>DATABASE ID</th><th class="actions-col">ACTIONS</th></tr></thead>
                <tbody>
                  <tr v-for="item in filteredIntakes" :key="item.id">
                    <td><strong class="intake-code"><span class="code-mark"></span>{{ item.intake_code }}</strong></td>
                    <td><span class="group-pill">{{ item.max_group }} {{ item.max_group === 1 ? 'group' : 'groups' }}</span></td>
                    <td><span class="id-text">{{ item.id }}</span></td>
                    <td class="actions"><button class="icon-action edit" @click="openEdit(item)" title="Edit intake">✎</button><button class="icon-action delete" @click="deleteIntake(item)" :disabled="deleting === item.id" title="Delete intake">⌫</button></td>
                  </tr>
                  <tr v-if="!loading && !filteredIntakes.length"><td colspan="4" class="empty-cell">{{ search ? 'No intakes match your search.' : 'No intakes found. Add your first intake to get started.' }}</td></tr>
                  <tr v-if="loading"><td colspan="4" class="empty-cell">Loading intakes…</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>

        <template v-else>
          <div class="admin-heading-row timetable-heading">
            <div><p class="admin-eyebrow">SCHEDULING OVERVIEW</p><h1>University timetable</h1><p class="muted">View scheduled classes generated by the scheduling system.</p></div>
            <span class="readonly-chip">◉ READ ONLY</span>
          </div>
          <section class="admin-panel filters-panel">
            <div class="filter-control"><label>START DATE</label><input v-model="startDate" type="date" /></div>
            <div class="filter-control"><label>END DATE</label><input v-model="endDate" type="date" /></div>
            <div class="filter-control intake-filter"><label>FILTER BY INTAKE</label><select v-model="intakeFilter"><option value="">All intakes</option><option v-for="i in intakes" :key="i.id" :value="i.id">{{ i.intake_code }}</option></select></div>
            <button class="g-btn primary" @click="loadSchedule" :disabled="scheduleLoading">{{ scheduleLoading ? 'Loading…' : 'Apply filters' }}</button>
          </section>
          <div class="schedule-summary"><div><strong>{{ schedule.length }}</strong><span>scheduled records</span></div><span class="muted">{{ dateRangeLabel }}</span></div>
          <section class="admin-panel">
            <div class="panel-head"><div><h2>All scheduled classes</h2><p>Classes are retrieved from the class_session_details database view.</p></div><button class="g-btn subtle" @click="loadSchedule" :disabled="scheduleLoading">↻ Refresh</button></div>
            <div class="table-wrap">
              <table class="schedule-table"><thead><tr><th>DATE & TIME</th><th>COURSE</th><th>INTAKE / GROUP</th><th>LECTURER</th><th>ROOM</th><th>STATUS</th></tr></thead>
                <tbody>
                  <tr v-for="item in schedule" :key="item.id">
                    <td><strong>{{ fmtDate(item.starts_at) }}</strong><small>{{ fmtTime(item.starts_at) }} – {{ fmtTime(item.ends_at) }}</small></td>
                    <td><strong>{{ item.course_code }}</strong><small>{{ item.course_name }} · {{ item.course_type }}</small></td>
                    <td><strong>{{ item.intake?.intake_code || '—' }}</strong><small>Group {{ item.group_number }}</small></td>
                    <td>{{ item.lecturer?.full_name || '—' }}</td>
                    <td>{{ item.room ? `${item.room.name} · ${item.room.building}` : '—' }}</td>
                    <td><span :class="['status-pill', item.status]">{{ item.status }}</span></td>
                  </tr>
                  <tr v-if="!scheduleLoading && !schedule.length"><td colspan="6" class="empty-cell">No timetable records found for this date range. Generated classes will appear here when available.</td></tr>
                  <tr v-if="scheduleLoading"><td colspan="6" class="empty-cell">Retrieving university timetable…</td></tr>
                </tbody>
              </table>
            </div>
          </section>
          <p class="schedule-note"><span>ⓘ</span> This page is read-only. Timetable creation and scheduling are handled by the scheduling engine and are not implemented in this admin module.</p>
        </template>
        <footer class="admin-footer">SClass · Administration <span>Google-inspired workspace</span></footer>
      </main>
    </section>
  </div>

  <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false">
    <section class="intake-modal" role="dialog" aria-modal="true" :aria-label="editing ? 'Edit intake' : 'Create intake'">
      <div class="modal-head"><div><p class="admin-eyebrow">{{ editing ? 'UPDATE RECORD' : 'NEW RECORD' }}</p><h2>{{ editing ? 'Edit intake' : 'Add intake' }}</h2></div><button class="modal-close" @click="modalOpen = false">×</button></div>
      <form @submit.prevent="saveIntake">
        <label>Intake code<input v-model="form.intake_code" maxlength="40" required placeholder="e.g. APR-2027" /></label>
        <p class="field-hint">Use a unique code to identify this university intake.</p>
        <label>Maximum groups<input v-model.number="form.max_group" type="number" min="1" max="100" required /></label>
        <p class="field-hint">Groups are numbered consecutively, starting from 1.</p>
        <div v-if="error" class="admin-alert error">{{ error }}</div>
        <div class="modal-actions"><button type="button" class="g-btn subtle" @click="modalOpen = false">Cancel</button><button class="g-btn primary" :disabled="saving">{{ saving ? 'Saving…' : editing ? 'Save changes' : 'Create intake' }}</button></div>
      </form>
    </section>
  </div>
</template>
