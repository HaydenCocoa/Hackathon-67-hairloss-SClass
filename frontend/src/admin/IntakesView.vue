<script setup>
// Admin > Intakes: infographics (students and groups per intake), add/edit/delete intakes,
// and the only way into an intake's students (IntakeStudents.vue).
import { computed, ref } from 'vue'
import { adminRequest } from './adminApi'
import { intakeFacts, intakeTotals } from './intakeStats'
import { matchesSearch } from './search'
import BarList from './BarList.vue'
import IntakeStudents from './IntakeStudents.vue'

const rows = ref([])
const loading = ref(false)
const message = ref('')
const form = ref({ intake_code: '', max_group: 1 })
const editing = ref(null)
const opened = ref(null) // intake whose students are shown
const search = ref('')

const totals = computed(() => intakeTotals(rows.value))
const sorted = computed(() => [...rows.value].sort((a, b) => a.intake_code.localeCompare(b.intake_code)))
const shown = computed(() => sorted.value.filter(row => matchesSearch(search.value, row.intake_code)))
const chart = computed(() => sorted.value.map((intake) => {
  const facts = intakeFacts(intake)
  return {
    key: intake.id, label: intake.intake_code, value: facts.students,
    note: plural(facts.groups, 'group'),
    tip: facts.perGroup.map((count, i) => `G${i + 1}: ${count}`).join(' · '),
  }
}))

async function load() {
  loading.value = true
  try { rows.value = await adminRequest('GET', '/api/admin/intakes') } catch (e) { rows.value = []; message.value = e.message } finally { loading.value = false }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
function reset() { form.value = { intake_code: '', max_group: 1 }; editing.value = null }

async function save() {
  message.value = ''
  const payload = { intake_code: String(form.value.intake_code).trim(), max_group: Number(form.value.max_group) }
  if (!payload.intake_code) { message.value = 'Enter an intake code.'; return }
  if (!Number.isInteger(payload.max_group) || payload.max_group < 1) { message.value = 'Enter a valid number of groups.'; return }
  try {
    await adminRequest(editing.value ? 'PUT' : 'POST', `/api/admin/intakes${editing.value ? '/' + editing.value : ''}`, payload)
    reset(); await load(); message.value = 'Saved successfully.'
  } catch (e) { message.value = e.message }
}

function edit(row) { editing.value = row.id; form.value = { intake_code: row.intake_code, max_group: row.max_group } }

async function remove(row) {
  if (!window.confirm(`Delete intake ${row.intake_code}?`)) return
  message.value = ''
  try {
    await adminRequest('DELETE', `/api/admin/intakes/${row.id}`)
    if (editing.value === row.id) reset()
    await load(); message.value = 'Deleted successfully.'
  } catch (e) { message.value = e.message }
}

async function close() { opened.value = null; message.value = ''; await load() }

load()
</script>

<template>
  <IntakeStudents v-if="opened" :intake="opened" @back="close" />
  <template v-else>
    <p role="status" class="notice">{{ message }}</p>
    <section class="stats" aria-label="Intake summary">
      <div><span>Intakes</span><strong>{{ totals.intakes }}</strong></div>
      <div><span>Students</span><strong>{{ totals.students }}</strong></div>
      <div><span>Groups</span><strong>{{ totals.groups }}</strong></div>
      <div><span>Students per group</span><strong>{{ totals.perGroup }}</strong><small>average, groups with students</small></div>
    </section>
    <section class="panel chart">
      <h2>Students per intake</h2>
      <p class="hint">Hover a bar to see the split by group.</p>
      <BarList :items="chart" unit="students" :empty="loading ? 'Loading…' : 'No intakes yet.'" />
    </section>
    <div class="admin-grid">
      <section class="panel">
        <h2>{{ editing ? 'Edit' : 'Add' }} intake</h2>
        <form @submit.prevent="save">
          <label>Intake code<input v-model="form.intake_code" required /></label>
          <label>Number of groups<input v-model="form.max_group" type="number" min="1" required /></label>
          <div><button type="submit">{{ editing ? 'Save changes' : 'Add' }}</button> <button v-if="editing" type="button" @click="reset">Cancel</button></div>
        </form>
      </section>
      <section class="panel">
        <h2>Intakes</h2>
        <div class="filters">
          <input v-model="search" type="search" placeholder="Search intake code" aria-label="Search intakes" />
        </div>
        <p v-if="!shown.length">{{ loading ? 'Loading…' : sorted.length ? 'No intakes match your search.' : 'No records to display.' }}</p>
        <div v-for="row in shown" :key="row.id" class="record">
          <div>
            <strong>{{ row.intake_code }}</strong>
            <p>{{ plural(intakeFacts(row).students, 'student') }} · {{ plural(row.max_group, 'group') }} · {{ plural(intakeFacts(row).courses, 'course') }}</p>
          </div>
          <div class="actions"><button class="primary" @click="opened = row">Students</button> <button @click="edit(row)">Edit</button> <button @click="remove(row)">Delete</button></div>
        </div>
      </section>
    </div>
  </template>
</template>
