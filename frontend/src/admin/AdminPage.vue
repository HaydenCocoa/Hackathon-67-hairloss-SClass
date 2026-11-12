<script setup>
// Admin page: courses, lecturers, intakes (with their students) and the room timetable.
// Uses the admin's login cookie; no token or demo mode. Students are managed only from
// Intakes > Students (IntakeStudents.vue), because a student's group belongs to an intake.
import { computed, ref } from 'vue'
import { adminRequest } from './adminApi'
import { looksLikeEmail, matchesSearch } from './search'
import IntakesView from './IntakesView.vue'
import NewLogin from './NewLogin.vue'
import RoomTimetable from './RoomTimetable.vue'

const SECTIONS = ['courses', 'lecturers', 'intakes', 'timetable']
const section = ref('courses')
const rows = ref([])
const form = ref({})
const editing = ref(null)
const message = ref('')
const loading = ref(false)
const timetableRefresh = ref(0)
const search = ref('')
const login = ref(null) // { name, email, temporary_password } of the lecturer just created; shown once
// Course type is no longer edited here: new courses are saved as lectures and edits keep the stored type.
const fields = computed(() => ({ courses: ['course_code', 'name'], lecturers: ['lecturer_code', 'full_name'] })[section.value] || [])
const labels = { course_code: 'Course code', name: 'Name', lecturer_code: 'Lecturer code', full_name: 'Full name' }

function intakeCodes(row) {
  return [...new Set((row.course_offerings || []).map(offering => offering.intakes?.intake_code).filter(Boolean))].sort().join(' · ') || 'No intake linked'
}
// Courses match code, name or linked intake codes; lecturers match code or name.
const shown = computed(() => rows.value.filter(row => section.value === 'courses'
  ? matchesSearch(search.value, row.course_code, row.name, intakeCodes(row))
  : matchesSearch(search.value, row.lecturer_code, row.full_name)))
function reset() { form.value = section.value === 'courses' ? { duration_minutes: 60 } : {}; editing.value = null }
const url = id => `/api/admin/${section.value}${id ? '/' + id : ''}`

async function load() {
  message.value = ''
  rows.value = []
  if (section.value === 'timetable') { timetableRefresh.value++; return }
  if (section.value === 'intakes') return // IntakesView loads its own data
  loading.value = true
  try { rows.value = await adminRequest('GET', url()) } catch (e) { message.value = e.message } finally { loading.value = false }
}
function select(value) { section.value = value; search.value = ''; login.value = null; reset(); load() }
// A new lecturer also gets a login: the backend creates it with this email and a temporary password.
const needsEmail = computed(() => section.value === 'lecturers' && !editing.value)

async function save() {
  message.value = ''
  login.value = null
  const payload = Object.fromEntries(fields.value.map(key => [key, String(form.value[key] ?? '').trim()]))
  if (needsEmail.value) payload.email = String(form.value.email ?? '').trim()
  if (Object.values(payload).some(value => value === '')) { message.value = 'Complete all required fields.'; return }
  if (needsEmail.value && !looksLikeEmail(payload.email)) { message.value = 'Enter a valid email address.'; return }
  if (section.value === 'courses') payload.duration_minutes = Number(form.value.duration_minutes)
  try {
    const result = await adminRequest(editing.value ? 'PUT' : 'POST', url(editing.value), payload)
    reset(); await load(); message.value = 'Saved successfully.'
    if (result?.temporary_password) login.value = { name: result.full_name, email: result.email, temporary_password: result.temporary_password }
  } catch (e) { message.value = e.message }
}
function edit(row) {
  login.value = null
  editing.value = row.id
  form.value = Object.fromEntries(fields.value.map(key => [key, row[key] ?? '']))
  if (section.value === 'courses') form.value.duration_minutes = row.duration_minutes
}
async function remove(row) {
  if (!window.confirm('Delete this record?')) return
  try {
    await adminRequest('DELETE', url(row.id))
    if (editing.value === row.id) reset()
    await load(); message.value = 'Deleted successfully.'
  } catch (e) { message.value = e.message }
}
reset()
load()
</script>

<template>
  <main class="admin-page">
    <p class="eyebrow">SCLASS / ADMIN</p><h1>Manage your workspace<span>.</span></h1>
    <p>Courses, lecturers, intakes and their students</p>
    <nav><button v-for="item in SECTIONS" :key="item" :class="{ active: section === item }" @click="select(item)">{{ item }}</button></nav>
    <section v-if="section === 'timetable'" class="panel">
      <RoomTimetable :refresh="timetableRefresh" />
    </section>
    <IntakesView v-else-if="section === 'intakes'" />
    <template v-else>
      <p role="status" class="notice">{{ message }}</p>
      <div class="admin-grid">
        <section class="panel"><h2>{{ editing ? 'Edit' : 'Add' }} {{ section.slice(0, -1) }}</h2><form @submit.prevent="save">
          <label v-for="field in fields" :key="field">{{ labels[field] }}<input v-model="form[field]" required /></label>
          <label v-if="needsEmail">Email<input v-model="form.email" type="email" autocomplete="off" required /></label>
          <div><button type="submit">{{ editing ? 'Save changes' : 'Add' }}</button> <button v-if="editing" type="button" @click="reset">Cancel</button></div>
          <p v-if="needsEmail" class="hint">Creates a login with this email and a temporary password (lecturer code + 4 random digits).</p>
        </form>
        <NewLogin v-if="login" :login="login" @close="login = null" /></section>
        <section class="panel"><h2>{{ section }}</h2>
          <div class="filters">
            <input v-model="search" type="search" :placeholder="section === 'courses' ? 'Search code, name or intake' : 'Search code or name'" :aria-label="`Search ${section}`" />
          </div>
          <p v-if="!shown.length">{{ loading ? 'Loading…' : rows.length ? `No ${section} match your search.` : 'No records to display.' }}</p>
          <div v-for="row in shown" :key="row.id" class="record">
            <div><strong>{{ row.name || row.full_name }}</strong>
              <p v-if="section === 'courses'">{{ row.course_code }} · {{ intakeCodes(row) }}</p>
              <p v-else>{{ row.lecturer_code }}</p></div>
            <div class="actions"><button @click="edit(row)">Edit</button> <button @click="remove(row)">Delete</button></div>
          </div>
        </section>
      </div>
    </template>
  </main>
</template>

<style>
/* Not scoped: also styles the Intakes views rendered inside this page. */
.admin-page{max-width:1100px;margin:auto;padding:36px;color:#253047}
.admin-page h1 span{color:#ea4335}
.admin-page h2,.admin-page nav button{text-transform:capitalize}
.admin-page .panel{background:white;border:1px solid #e2e7ef;border-radius:16px;padding:22px;margin:0}
.admin-page label{display:block;font-size:14px;font-weight:600;margin-bottom:14px}
.admin-page input,.admin-page select{display:block;width:100%;padding:10px;border:1px solid #cdd5e0;border-radius:8px;margin-top:6px;box-sizing:border-box}
.admin-page button{border:0;border-radius:8px;padding:10px 14px;cursor:pointer;background:#e8f0fe;color:#185abc}
.admin-page button.active,.admin-page button[type=submit],.admin-page button.primary{background:#4285f4;color:white}
.admin-page nav{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0 8px}
.admin-page .admin-grid{display:grid;grid-template-columns:1fr 2fr;gap:20px;margin-top:20px}
.admin-page .admin-grid>.panel:first-child{border-top:4px solid #a8dab5}
.admin-page .record{display:flex;justify-content:space-between;align-items:center;gap:10px;border-top:1px solid #e2e7ef;padding:15px 0}
.admin-page .record p{margin:4px 0;color:#5b6477}
.admin-page .actions{white-space:nowrap}
.admin-page .notice{min-height:24px;color:#b3261e}
.admin-page .hint{color:#6b7385;font-size:13px;margin:4px 0 12px}
.admin-page .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px}
.admin-page .stats>div{background:white;border:1px solid #e2e7ef;border-radius:16px;padding:16px 18px;display:flex;flex-direction:column;gap:4px}
.admin-page .stats span{font-size:13px;color:#5b6477}
.admin-page .stats strong{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
.admin-page .stats small{font-size:12px;color:#6b7385}
.admin-page .chart h2{margin:0 0 8px;text-transform:none}
.admin-page .scroll{max-height:640px;overflow-y:auto}
.admin-page .back{margin:4px 0 8px}
.admin-page .title span{color:#6b7385;font-weight:400;text-transform:none}
.admin-page .filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.admin-page .filters button{padding:6px 10px;font-size:13px}
.admin-page .filters input{width:auto;flex:1;min-width:160px;margin:0;padding:7px 10px}
@media(max-width:800px){.admin-page .stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.admin-page{padding:20px 16px}.admin-page .admin-grid{grid-template-columns:1fr}.admin-page .record{flex-wrap:wrap}}
</style>
