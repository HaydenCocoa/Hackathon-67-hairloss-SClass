<script setup>
Admin
import { ref, computed } from 'vue'

const token = ref('')
const demo = ref(false)
const section = ref('courses')
const rows = ref([])
const form = ref({})
const editing = ref(null)
const message = ref('')
const demoStart = new Date()
demoStart.setHours(9, 0, 0, 0)
const demoEnd = new Date(demoStart.getTime() + 60 * 60 * 1000)
const demoRooms = [{ id: 'demo-room', name: 'A101', building: 'A', room_type: 'classroom', capacity: 40 }]
const memory = { courses: [{ id: '1', course_code: 'CS101', name: 'Introduction to Computing', course_type: 'lecture', duration_minutes: 60 }], students: [], lecturers: [], intakes: [], timetable: [
  { id: 'demo-class', course_code: 'CS101', course_name: 'Introduction to Computing', starts_at: demoStart.toISOString(), ends_at: demoEnd.toISOString(), room_id: 'demo-room', room: demoRooms[0], lecturer: { full_name: 'Demo Lecturer' }, intake: { intake_code: 'DEMO' }, group_number: 1, status: 'scheduled' },
  { id: 'demo-cancelled', course_code: 'CS102', course_name: 'Cancelled class', starts_at: demoStart.toISOString(), ends_at: demoEnd.toISOString(), room_id: 'demo-room', room: demoRooms[0], lecturer: { full_name: 'Demo Lecturer' }, intake: { intake_code: 'DEMO' }, group_number: 1, status: 'cancelled' },
] }
const fields = computed(() => ({ courses: ['course_code', 'name', 'course_type'], students: ['student_code', 'full_name', 'age'], lecturers: ['lecturer_code', 'full_name'], intakes: ['intake_code', 'max_group'], timetable: [] })[section.value])
const startDate = ref(new Date().toISOString().slice(0, 10))
const endDate = ref(new Date().toISOString().slice(0, 10))
const rooms = ref([])
const editingSession = ref(null)
const sessionForm = ref({})
const savingSession = ref(false)
function intakeCodes(row) {
  return [...new Set((row.course_offerings || []).map(offering => offering.intakes?.intake_code).filter(Boolean))].sort().join(' · ') || 'No intake linked'
}
function reset() { form.value = section.value === 'courses' ? { course_type: 'lecture', duration_minutes: 60 } : section.value === 'intakes' ? { max_group: 1 } : {}; editing.value = null }
async function request(method, id, body) {
  const response = await fetch(`/api/admin/${section.value}${id ? '/' + id : ''}`, { method, headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
  const result = await response.json()
  if (!response.ok) throw new Error(result.detail || 'Request failed.')
  return result
}
async function load() {
  message.value = ''
  try {
    if (demo.value) {
      rows.value = [...memory[section.value]]
      if (section.value === 'timetable') rooms.value = demoRooms
    }
    else if (section.value === 'timetable') {
      const start = new Date(`${startDate.value}T00:00:00`)
      const end = new Date(`${endDate.value}T00:00:00`)
      end.setDate(end.getDate() + 1)
      if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start) throw new Error('Choose a valid date range.')
      const params = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() })
      const headers = { Authorization: `Bearer ${token.value}` }
      const [response, roomResponse] = await Promise.all([
        fetch(`/api/admin/timetable?${params}`, { headers }),
        fetch('/api/admin/timetable/rooms', { headers }),
      ])
      const [result, roomResult] = await Promise.all([response.json(), roomResponse.json()])
      if (!response.ok) throw new Error(result.detail || 'Request failed.')
      if (!roomResponse.ok) throw new Error(roomResult.detail || 'Could not load rooms.')
      rows.value = result
      rooms.value = roomResult
    } else rows.value = await request('GET')
  } catch (e) { rows.value = []; message.value = e.message }
}
function select(value) { section.value = value; editingSession.value = null; reset(); load() }
function editSession(row) {
  editingSession.value = row
  const date = new Date(row.starts_at)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  sessionForm.value = { starts_at: local.toISOString().slice(0, 16), room_id: row.room_id, reason: '' }
  message.value = ''
}
async function saveSession() {
  const row = editingSession.value
  const start = new Date(sessionForm.value.starts_at)
  if (!row || !Number.isFinite(start.getTime()) || !sessionForm.value.room_id || !sessionForm.value.reason.trim()) {
    message.value = 'Choose a start time and room, and enter a reason.'
    return
  }
  savingSession.value = true
  try {
    if (demo.value) {
      const duration = new Date(row.ends_at) - new Date(row.starts_at)
      Object.assign(row, { starts_at: start.toISOString(), ends_at: new Date(start.getTime() + duration).toISOString(), room_id: sessionForm.value.room_id, room: demoRooms.find(room => room.id === sessionForm.value.room_id) })
    } else {
      const response = await fetch(`/api/admin/timetable/${row.id}`, {
        method: 'PUT', headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_start: row.starts_at, expected_room: row.room_id, new_start: start.toISOString(), new_room: sessionForm.value.room_id, reason: sessionForm.value.reason.trim() }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not update the class.')
    }
    editingSession.value = null
    await load()
    message.value = 'Class updated successfully.'
  } catch (e) { message.value = e.message }
  finally { savingSession.value = false }
}
async function removeCancelled(row) {
  if (!window.confirm('Remove this cancelled class from the timetable? Its history will be retained.')) return
  try {
    if (demo.value) memory.timetable = memory.timetable.filter(item => item.id !== row.id)
    else {
      const response = await fetch(`/api/admin/timetable/${row.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token.value}` } })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not remove the class.')
    }
    await load()
    message.value = 'Cancelled class removed from the timetable.'
  } catch (e) { message.value = e.message }
}
async function save() {
  message.value = ''
  const payload = Object.fromEntries(fields.value.map(key => [key, form.value[key] ?? '']))
  if (fields.value.some(key => key !== 'age' && String(payload[key]).trim() === '')) { message.value = 'Complete all required fields.'; return }
  if (section.value === 'courses') payload.duration_minutes = form.value.duration_minutes
  if ('duration_minutes' in payload) payload.duration_minutes = Number(payload.duration_minutes)
  if ('age' in payload) payload.age = payload.age === '' ? null : Number(payload.age)
  if ('max_group' in payload) payload.max_group = Number(payload.max_group)
  if ('max_group' in payload && (!Number.isInteger(payload.max_group) || payload.max_group < 1)) { message.value = 'Enter a valid maximum group.'; return }
  if (('duration_minutes' in payload && (!Number.isInteger(payload.duration_minutes) || payload.duration_minutes < 1)) || (payload.age != null && (!Number.isInteger(payload.age) || payload.age < 0))) { message.value = 'Enter a valid whole number.'; return }
  try {
    if (demo.value) {
      if (editing.value) Object.assign(memory[section.value].find(row => row.id === editing.value), payload)
      else memory[section.value].push({ ...payload, id: crypto.randomUUID() })
    } else await request(editing.value ? 'PUT' : 'POST', editing.value, payload)
    reset(); await load(); message.value = 'Saved successfully.'
  } catch (e) { message.value = e.message }
}
function edit(row) {
  editing.value = row.id
  form.value = Object.fromEntries(fields.value.map(key => [key, row[key] ?? '']))
  if (section.value === 'courses') form.value.duration_minutes = row.duration_minutes
}
async function remove(row) {
  if (!window.confirm('Delete this record?')) return
  try {
    if (demo.value) memory[section.value] = memory[section.value].filter(item => item.id !== row.id)
    else await request('DELETE', row.id)
    if (editing.value === row.id) reset()
    await load(); message.value = 'Deleted successfully.'
  } catch (e) { message.value = e.message }
}
reset()
</script>
<template>
  <main class="admin-page">
    <a href="#/">← Main menu</a><p class="eyebrow">SCLASS / ADMIN</p><h1>Manage your workspace<span>.</span></h1>
    <p>Courses and user profiles</p>
    <div class="access"><label>Admin access token <input v-model="token" type="password" autocomplete="off" placeholder="Supabase access token" /></label><button @click="demo = false; load()">Connect</button><button @click="demo = true; load()">Try local demo</button><small>{{ demo ? 'Demo data stays in this browser session.' : 'Use a signed-in administrator access token.' }}</small></div>
    <nav><button v-for="item in ['courses', 'students', 'lecturers', 'intakes', 'timetable']" :key="item" :class="{ active: section === item }" @click="select(item)">{{ item }}</button></nav>
    <p role="status" class="notice">{{ message }}</p>
    <section v-if="section === 'timetable'" class="panel">
      <h2>University timetable</h2>
      <div class="access"><label>Start date<input v-model="startDate" type="date" /></label><label>End date<input v-model="endDate" type="date" /></label><button @click="load">Load classes</button></div>
      <form v-if="editingSession" class="access" @submit.prevent="saveSession">
        <strong>Reschedule {{ editingSession.course_name }}</strong>
        <label>Start time<input v-model="sessionForm.starts_at" type="datetime-local" required /></label>
        <label>Room<select v-model="sessionForm.room_id" required><option v-for="room in rooms" :key="room.id" :value="room.id">{{ room.name }} · {{ room.building }} · {{ room.room_type }} · {{ room.capacity }} seats</option></select></label>
        <label>Reason<input v-model="sessionForm.reason" maxlength="500" required /></label>
        <button type="submit" :disabled="savingSession">Save changes</button><button type="button" @click="editingSession = null">Cancel</button>
      </form>
      <p v-if="!rows.length">No scheduled classes in this period.</p>
      <div v-for="row in rows" :key="row.id" class="record"><div><strong>{{ row.course_name }} · {{ row.course_code }}</strong><p>{{ new Date(row.starts_at).toLocaleString() }} – {{ new Date(row.ends_at).toLocaleString() }}</p><p>{{ row.intake?.intake_code }} · Group {{ row.group_number }} · {{ row.lecturer?.full_name || '—' }} · {{ row.room?.name || '—' }} · {{ row.status }}</p></div><div><button v-if="row.status === 'scheduled'" @click="editSession(row)">Edit</button><button v-if="row.status === 'cancelled'" @click="removeCancelled(row)">Remove</button></div></div>
    </section>
    <div v-else class="admin-grid"><section class="panel"><h2>{{ editing ? 'Edit' : 'Add' }} {{ section.slice(0, -1) }}</h2><form @submit.prevent="save">
      <label v-for="field in fields" :key="field">{{ field.replaceAll('_', ' ') }}<select v-if="field === 'course_type'" v-model="form[field]"><option v-for="type in ['lecture', 'tutorial', 'lab', 'others']" :key="type">{{ type }}</option></select><input v-else v-model="form[field]" :type="['age', 'max_group'].includes(field) ? 'number' : 'text'" :min="field === 'age' ? 0 : 1" :required="field !== 'age'" /></label>
      <div><button type="submit">{{ editing ? 'Save changes' : 'Add' }}</button> <button v-if="editing" type="button" @click="reset">Cancel</button></div>
    </form></section><section class="panel"><h2>{{ section }}</h2><p v-if="!rows.length">No records to display.</p><div v-for="row in rows" :key="row.id" class="record"><div><strong>{{ row.name || row.full_name || row.intake_code }}</strong><p v-if="section === 'courses'">{{ intakeCodes(row) }}</p><p v-else>{{ fields.filter(f => !['name', 'full_name', 'intake_code'].includes(f)).map(f => row[f]).filter(v => v != null).join(' · ') }}</p></div><div><button @click="edit(row)">Edit</button> <button @click="remove(row)">Delete</button></div></div></section></div>
  </main>
</template>
<style scoped>
.admin-page{max-width:1100px;margin:auto;padding:36px;color:#253047} h1 span{color:#ea4335} h2,nav button{text-transform:capitalize} .access,.panel{background:white;border:1px solid #e2e7ef;border-radius:16px;padding:22px;margin:20px 0} .access{display:flex;align-items:end;gap:10px;flex-wrap:wrap;border-top:4px solid #fbbc04} label{display:block;text-transform:capitalize;font-size:14px;font-weight:600;margin-bottom:14px} input,select{display:block;width:100%;padding:10px;border:1px solid #cdd5e0;border-radius:8px;margin-top:6px} button{border:0;border-radius:8px;padding:10px 14px;cursor:pointer;background:#e8f0fe;color:#185abc} button.active,button[type=submit]{background:#4285f4;color:white} nav{display:flex;gap:8px;flex-wrap:wrap}.admin-grid{display:grid;grid-template-columns:1fr 2fr;gap:20px}.panel{margin:0}.panel:first-child{border-top:4px solid #a8dab5}.record{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #e2e7ef;padding:15px 0}.record p{margin:4px 0}.notice{min-height:24px;color:#b3261e}@media(max-width:700px){.admin-grid{grid-template-columns:1fr}}

// Admin Page: intentionally empty placeholder. The admin area is being built by
// another team member; only the route, the admin-only access and the login exist.
</script>

<template>
  <main class="admin-page">
    <h1>Admin</h1>
    <p>The admin area is under development.</p>
    <p><a href="/admin/development/scheduling-test-hayden">Scheduling test page (development) ↗</a></p>
  </main>
</template>

<style scoped>
.admin-page { max-width: 960px; margin: 0 auto; padding: 48px 24px; }
.admin-page p { color: #6d7968; }
.admin-page a { color: #214f40; text-decoration: underline; }
 main
</style>
