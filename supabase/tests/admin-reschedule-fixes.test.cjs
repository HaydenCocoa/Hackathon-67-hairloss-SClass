// Checks 202611120003_admin_reschedule_fixes.sql on real local PostgreSQL (PGlite).
// Runs the room-type removal patch before and after the admin timetable migration.
// Run with NODE_PATH pointing to a local @electric-sql/pglite installation.
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { PGlite } = require('@electric-sql/pglite')
const { bootstrap } = require('./support.cjs')
const read = file => fs.readFileSync(path.join(__dirname, '../migrations', file), 'utf8')
let passed = 0

async function run(removalFirst) {
  const label = removalFirst ? 'removal before admin migration' : 'removal after admin migration'
  const db = new PGlite()
  const q = async (sql, params = []) => (await db.query(sql, params)).rows
  const check = (value, text) => { assert.ok(value, `${label}: ${text}`); passed++ }
  const reject = async (sql, params, pattern, text) => {
    await assert.rejects(() => db.query(sql, params), pattern, `${label}: ${text}`); passed++
  }
  const asAdmin = async (sql, params) => {
    await db.exec('set role authenticated')
    try { return await q(sql, params) } finally { await db.exec('reset role') }
  }
  try {
    await db.exec(bootstrap)
    await db.exec(fs.readFileSync(path.join(__dirname, '../schema.sql'), 'utf8'))
    await db.exec(read('202611100001_teaching_requirements.sql'))
    if (removalFirst) {
      await db.exec(read('202611100002_remove_required_room_type.sql'))
      await db.exec(read('202611110001_admin_timetable.sql')) // failed here before the fix
      check(true, 'admin timetable migration applies after the column was removed')
    } else {
      await db.exec(read('202611110001_admin_timetable.sql'))
      await db.exec(read('202611100002_remove_required_room_type.sql'))
    }
    await db.exec(read('202611120001_class_session_rescheduled_status.sql'))
    const view = (await q("select column_name from information_schema.columns where table_schema='public' and table_name='class_session_details'")).map(r => r.column_name)
    check(!view.includes('required_room_type') && view.includes('group_number'), 'timetable view has no legacy room column')

    const admin = (await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id
    await q("insert into admins(auth_user_id, full_name) values ($1, 'Admin')", [admin])
    await q("select set_config('request.jwt.claim.sub',$1,false)", [admin])
    const intake = (await q("insert into intakes(intake_code,max_group) values ('T',2) returning id"))[0].id
    const lecturer = (await q("insert into lecturers(lecturer_code,full_name) values ('L1','Teacher') returning id"))[0].id
    const other = (await q("insert into lecturers(lecturer_code,full_name) values ('L2','Other') returning id"))[0].id
    const section = async (type, group, teacher) => {
      const course = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ($1,'Subject',$2,60) returning id", [`C-${type}-${group}`, type]))[0].id
      const offering = (await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [course, intake, teacher]))[0].id
      return (await q('insert into class_sections(offering_id,group_number) values ($1,$2) returning id', [offering, group]))[0].id
    }
    const room = async (name, type, seats) => (await q('insert into rooms(name,building,capacity,room_type) values ($1,$2,$3,$4) returning id', [name, 'B', seats, type]))[0].id
    const classroom = await room('CR', 'classroom', 40)
    const lab = await room('LB', 'lab', 40)
    const hall = await room('AU', 'auditorium', 300)
    const book = async (sec, roomId, start) => (await q('insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,$3) returning id', [sec, roomId, start]))[0].id
    const lecture = await section('lecture', 1, lecturer)
    const labSection = await section('lab', 1, lecturer)
    const otherClass = await section('tutorial', 2, other)
    const extra = await section('others', 2, other)

    const move = 'select public.admin_reschedule_class($1,$2,$3,$4,$5,$6)'
    const moving = await book(lecture, classroom, '2026-11-16 01:00Z')
    if (!removalFirst) {
      // Before the fix: the old function still reads the removed column.
      await reject(move, [moving, '2026-11-16 01:00Z', classroom, '2026-11-16 02:00Z', classroom, 'r'], /required_room_type/, 'old function breaks after the column removal')
    }

    const migration = read('202611120003_admin_reschedule_fixes.sql')
    await db.exec(migration)
    await db.exec(migration) // rerun is harmless

    await asAdmin(move, [moving, '2026-11-16 01:00Z', classroom, '2026-11-16 02:00Z', classroom, 'First move'])
    let row = (await q('select status, starts_at from class_sessions where id=$1', [moving]))[0]
    check(row.status === 'rescheduled', 'a moved class becomes rescheduled')
    const log = (await q("select old_values, new_values from schedule_changes where class_session_id=$1 and action='reschedule'", [moving]))[0]
    check(log.old_values.status === 'scheduled' && log.new_values.status === 'rescheduled', 'audit records the status change')

    await asAdmin(move, [moving, '2026-11-16 02:00Z', classroom, '2026-11-16 03:00Z', classroom, 'Second move'])
    row = (await q('select starts_at from class_sessions where id=$1', [moving]))[0]
    check(new Date(row.starts_at).toISOString() === '2026-11-16T03:00:00.000Z', 'a rescheduled class can be moved again')

    // Another class (different lecturer and group) in the same room, already rescheduled, still blocks the room.
    const blocker = await book(otherClass, lab, '2026-11-17 01:00Z')
    await q("update class_sessions set status='rescheduled' where id=$1", [blocker])
    const labClass = await book(labSection, classroom, '2026-11-18 01:00Z')
    await reject(move, [labClass, '2026-11-18 01:00Z', classroom, '2026-11-17 01:30Z', lab, 'Clash'], /another booking/, 'a rescheduled class blocks its room')

    await reject(move, [labClass, '2026-11-18 01:00Z', classroom, '2026-11-19 01:00Z', hall, 'Hall'], /unsuitable/, 'labs cannot use auditoriums')
    await asAdmin(move, [labClass, '2026-11-18 01:00Z', classroom, '2026-11-19 01:00Z', lab, 'Lab room'])
    check((await q('select room_id from class_sessions where id=$1', [labClass]))[0].room_id === lab, 'labs can use labs')

    await reject(move, [moving, '2026-11-16 03:00Z', classroom, '2026-11-20 01:00Z', hall, 'Hall'], /Auditoriums are kept/, 'auditorium refused while a classroom seats the class')
    await q('update rooms set capacity=1 where id=$1', [classroom])
    for (let i = 0; i < 5; i++) {
      const student = (await q("insert into students(student_code,full_name) values ($1,'S') returning id", [`S${i}`]))[0].id
      await q('insert into student_intakes values ($1,$2,1)', [student, intake])
    }
    await asAdmin(move, [moving, '2026-11-16 03:00Z', classroom, '2026-11-20 01:00Z', hall, 'Too big'])
    check((await q('select room_id from class_sessions where id=$1', [moving]))[0].room_id === hall, 'auditorium allowed when no other permitted room seats the class')

    const otherKind = await book(extra, lab, '2026-11-18 05:00Z')
    await reject(move, [otherKind, '2026-11-18 05:00Z', lab, '2026-11-18 07:00Z', lab, 'Other'], /unsuitable/, "'others' courses have no permitted rooms")

    await q("update class_sessions set status='cancelled' where id=$1", [blocker])
    await reject(move, [blocker, '2026-11-17 01:00Z', lab, '2026-11-17 05:00Z', lab, 'Cancelled'], /Only scheduled classes/, 'cancelled classes cannot be moved')
  } finally {
    await db.close()
  }
}

;(async () => {
  await run(true)
  await run(false)
  console.log(`PASS: ${passed} admin reschedule fix checks (PostgreSQL via PGlite; mocked Auth).`)
})().catch(error => { console.error(error); process.exitCode = 1 })
