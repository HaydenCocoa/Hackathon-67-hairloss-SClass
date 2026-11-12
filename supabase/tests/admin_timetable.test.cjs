// Run with NODE_PATH pointing to a local @electric-sql/pglite installation.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { PGlite } = require('@electric-sql/pglite')
const { bootstrap } = require('./support.cjs')

async function main() {
  const db = new PGlite()
  const query = async (sql, params = []) => (await db.query(sql, params)).rows
  try {
    await db.exec(bootstrap)
    await db.exec(fs.readFileSync(path.join(__dirname, '../schema.sql'), 'utf8'))
    await db.exec(fs.readFileSync(path.join(__dirname, '../migrations/202611110001_admin_timetable.sql'), 'utf8'))
    const admin = (await query('insert into auth.users values (gen_random_uuid()) returning id'))[0].id
    await query("insert into admins(auth_user_id, full_name) values ($1, 'Admin')", [admin])
    const intake = (await query("insert into intakes(intake_code) values ('TEST') returning id"))[0].id
    const lecturer = (await query("insert into lecturers(lecturer_code,full_name) values ('L1','Lecturer') returning id"))[0].id
    const course = (await query("insert into courses(course_code,name,course_type,duration_minutes) values ('C1','Course','lecture',60) returning id"))[0].id
    const offering = (await query('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [course, intake, lecturer]))[0].id
    const section = (await query("insert into class_sections(offering_id,required_room_type) values ($1,'classroom') returning id", [offering]))[0].id
    const room = (await query("insert into rooms(name,building,capacity,room_type) values ('R1','A',50,'classroom') returning id"))[0].id
    const session = (await query("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-10 09:00Z') returning id", [section, room]))[0].id
    const cancelled = (await query("insert into class_sessions(section_id,room_id,starts_at,status) values ($1,$2,'2026-11-10 11:00Z','cancelled') returning id", [section, room]))[0].id
    const reschedule = 'select public.admin_reschedule_class($1,$2,$3,$4,$5,$6)'
    const args = [session, '2026-11-10 09:00Z', room, '2026-11-10 10:00Z', room, 'Reason']
    await assert.rejects(() => query(reschedule, args), /Administrator access required/)
    await query("select set_config('request.jwt.claim.sub',$1,false)", [admin])
    await db.exec('set role authenticated')
    await query(reschedule, args)
    await db.exec('reset role')
    assert.equal((await query('select count(*)::int n from schedule_changes where class_session_id=$1', [session]))[0].n, 1)
    await assert.rejects(() => query(reschedule, args), /changed since it was loaded/)
    await query("insert into meeting_sessions(lecturer_id,room_id,starts_at,ends_at) values ($1,$2,'2026-11-10 12:00Z','2026-11-10 13:00Z')", [lecturer, room])
    await assert.rejects(() => query(reschedule, [session, '2026-11-10 10:00Z', room, '2026-11-10 12:00Z', room, 'Conflict']), /another booking/)
    assert.equal((await query('select count(*)::int n from schedule_changes where class_session_id=$1', [session]))[0].n, 1)
    await assert.rejects(() => query('select public.admin_remove_cancelled_class($1)', [session]), /Cancelled class not found/)
    await query('select public.admin_remove_cancelled_class($1)', [cancelled])
    assert.equal((await query('select count(*)::int n from class_session_details where id=$1', [cancelled]))[0].n, 0)
    assert.equal((await query('select removed_by from class_sessions where id=$1', [cancelled]))[0].removed_by, admin)
    console.log('Admin timetable migration checks passed.')
  } finally {
    await db.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
