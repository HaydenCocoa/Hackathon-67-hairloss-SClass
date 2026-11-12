<script setup>
// Admin > Intakes > (one intake) > Students: students per group chart, and add/edit/remove
// students in this intake. Reached only from the Intakes page.
import { computed, ref } from 'vue'
import { adminRequest } from './adminApi'
import { looksLikeEmail } from './search'
import BarList from './BarList.vue'
import NewLogin from './NewLogin.vue'

const props = defineProps({ intake: { type: Object, required: true } })
defineEmits(['back'])

const base = computed(() => `/api/admin/intakes/${props.intake.id}/students`)
const groups = computed(() => Array.from({ length: Math.max(1, props.intake.max_group || 1) }, (_, i) => i + 1))
const students = ref([])
const loading = ref(false)
const message = ref('')
const filter = ref(0) // 0 = all groups
const search = ref('')
const editing = ref(null)
const form = ref({})
const login = ref(null) // { name, email, temporary_password } of the student just created; shown once

const perGroup = computed(() => groups.value.map(group => students.value.filter(s => s.group_number === group).length))
const chart = computed(() => groups.value.map((group, i) => ({ key: group, label: `Group ${group}`, value: perGroup.value[i] })))
const shown = computed(() => {
  const term = search.value.trim().toLowerCase()
  return students.value.filter(s => (!filter.value || s.group_number === filter.value)
    && (!term || `${s.student_code} ${s.full_name}`.toLowerCase().includes(term)))
})
const stats = computed(() => {
  const counts = perGroup.value
  return { students: students.value.length, groups: groups.value.length, largest: Math.max(0, ...counts), smallest: Math.min(...counts) }
})

function reset() { form.value = { student_code: '', full_name: '', email: '', age: '', group_number: filter.value || 1 }; editing.value = null }

async function load() {
  loading.value = true
  try { students.value = await adminRequest('GET', base.value) } catch (e) { students.value = []; message.value = e.message } finally { loading.value = false }
}

async function save() {
  message.value = ''
  login.value = null
  const payload = {
    student_code: String(form.value.student_code ?? '').trim(),
    full_name: String(form.value.full_name ?? '').trim(),
    age: form.value.age === '' || form.value.age == null ? null : Number(form.value.age),
    group_number: Number(form.value.group_number),
  }
  const email = String(form.value.email ?? '').trim()
  if (!payload.student_code || !payload.full_name) { message.value = 'Complete all required fields.'; return }
  if (payload.age != null && (!Number.isInteger(payload.age) || payload.age < 0)) { message.value = 'Enter a valid age.'; return }
  if (!editing.value && email && !looksLikeEmail(email)) { message.value = 'Enter a valid email address.'; return }
  try {
    if (editing.value) {
      await adminRequest('PUT', `${base.value}/${editing.value}`, payload)
      message.value = 'Saved successfully.'
    } else {
      // The email is only used when the student code is new (the backend then creates the login).
      const result = await adminRequest('POST', base.value, email ? { ...payload, email } : payload)
      if (result.existing) {
        message.value = `Student ${payload.student_code} already existed (${result.full_name}), so that record was added to this intake. No new login was created.`
      } else {
        message.value = 'Student added.'
        login.value = { name: result.full_name, email: result.email, temporary_password: result.temporary_password }
      }
    }
    reset(); await load()
  } catch (e) { message.value = e.message }
}

function edit(row) {
  login.value = null
  editing.value = row.id
  form.value = { student_code: row.student_code, full_name: row.full_name, age: row.age ?? '', group_number: row.group_number }
}

async function remove(row) {
  if (!window.confirm(`Remove ${row.full_name} from ${props.intake.intake_code}?`)) return
  message.value = ''
  try {
    const result = await adminRequest('DELETE', `${base.value}/${row.id}`)
    if (editing.value === row.id) reset()
    await load()
    message.value = result.student_deleted ? 'Student removed and deleted.' : 'Student removed from this intake.'
  } catch (e) { message.value = e.message }
}

reset()
load()
</script>

<template>
  <button type="button" class="back" @click="$emit('back')">← Intakes</button>
  <h2 class="title">{{ intake.intake_code }} <span>students</span></h2>
  <p role="status" class="notice">{{ message }}</p>
  <section class="stats" aria-label="Intake summary">
    <div><span>Students</span><strong>{{ stats.students }}</strong></div>
    <div><span>Groups</span><strong>{{ stats.groups }}</strong></div>
    <div><span>Largest group</span><strong>{{ stats.largest }}</strong></div>
    <div><span>Smallest group</span><strong>{{ stats.smallest }}</strong></div>
  </section>
  <section class="panel chart">
    <h2>Students per group</h2>
    <BarList :items="chart" unit="students" :empty="loading ? 'Loading…' : 'No groups.'" />
  </section>
  <div class="admin-grid">
    <section class="panel">
      <h2>{{ editing ? 'Edit' : 'Add' }} student</h2>
      <form @submit.prevent="save">
        <label>Student code<input v-model="form.student_code" required /></label>
        <label>Full name<input v-model="form.full_name" required /></label>
        <label v-if="!editing">Email<input v-model="form.email" type="email" autocomplete="off" placeholder="Needed for a new student" /></label>
        <label>Age<input v-model="form.age" type="number" min="0" /></label>
        <label>Group<select v-model.number="form.group_number"><option v-for="group in groups" :key="group" :value="group">Group {{ group }}</option></select></label>
        <div><button type="submit">{{ editing ? 'Save changes' : 'Add' }}</button> <button v-if="editing" type="button" @click="reset">Cancel</button></div>
        <p v-if="!editing" class="hint">A new student code creates a login with this email and a temporary password (student code + 4 random digits). An existing student code is added to this intake without changing that student's name, age or login.</p>
      </form>
      <NewLogin v-if="login" :login="login" @close="login = null" />
    </section>
    <section class="panel">
      <h2>Students</h2>
      <div class="filters">
        <button v-for="group in [0, ...groups]" :key="group" type="button" :class="{ active: filter === group }" @click="filter = group">{{ group ? `Group ${group}` : 'All' }}</button>
        <input v-model="search" type="search" placeholder="Search code or name" aria-label="Search students" />
      </div>
      <p v-if="!shown.length">{{ loading ? 'Loading…' : 'No students to display.' }}</p>
      <div class="scroll"><div v-for="row in shown" :key="row.id" class="record">
        <div><strong>{{ row.full_name }}</strong><p>{{ row.student_code }} · Group {{ row.group_number }}<template v-if="row.age != null"> · Age {{ row.age }}</template></p></div>
        <div class="actions"><button @click="edit(row)">Edit</button> <button @click="remove(row)">Remove</button></div>
      </div></div>
    </section>
  </div>
</template>
