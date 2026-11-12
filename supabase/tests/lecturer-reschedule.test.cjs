// Checks 202611120004_lecturer_reschedule.sql on real local PostgreSQL (PGlite).
// Run with NODE_PATH pointing to a local @electric-sql/pglite installation (.sql-tools/node_modules).
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { PGlite } = require('@electric-sql/pglite')
const { bootstrap } = require('./support.cjs')
const read = file => fs.readFileSync(path.join(__dirname, '../migrations', file), 'utf8')
let passed = 0

;(async () => {
  const db = new PGlite()
  const q = async (sql, params = []) => (await db.query(sql, params)).rows
  const check = (value, text) => { assert.ok(value, text); passed++ }
  // Run as the logged-in Supabase user (role authenticated, auth.uid() = user).
  const as = async (user, sql, params) => {
    await q("select set_config('request.jwt.claim.sub',$1,false)", [user])
    await db.exec('set role authenticated')
    try { return await q(sql, params) } finally { await db.exec('reset role') }
  }
  const rejectAs = async (user, sql, params, pattern, text) => {
    await assert.rejects(() => as(user, sql, params), pattern, text); passed++
  }
  try {
    await db.exec(bootstrap)
    await db.exec(fs.readFileSync(path.join(__dirname, '../schema.sql'), 'utf8'))
    await db.exec(read('202611100001_teaching_requirements.sql'))
    await db.exec(read('202611100002_remove_required_room_type.sql'))
    await db.exec(read('202611110001_admin_timetable.sql'))
    await db.exec(read('202611120001_class_session_rescheduled_status.sql'))

    const migration = read('202611120004_lecturer_reschedule.sql')
    await assert.rejects(() => db.exec(migration), /Apply 202611120003/, 'refuses to run before 202611120003'); passed++
    await db.exec('rollback') // the failed migration's transaction
    await db.exec(read('202611120003_admin_reschedule_fixes.sql'))
    await db.exec(migration)
    await db.exec(migration) // rerun is harmless

    const user = async () => (await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id
    const adminUser = await user(), teacherUser = await user(), otherUser = await user()
    await q("insert into admins(auth_user_id, full_name) values ($1, 'Admin')", [adminUser])
    const intake = (await q("insert into intakes(intake_code,max_group) values ('T',2) returning id"))[0].id
    const lecturer = (await q("insert into lecturers(lecturer_code,full_name,auth_user_id) values ('L1','Teacher',$1) returning id", [teacherUser]))[0].id
    const other = (await q("insert into lecturers(lecturer_code,full_name,auth_user_id) values ('L2','Other',$1) returning id", [otherUser]))[0].id
    const section = async (code, group, teacher) => {
      const course = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ($1,'Subject','lecture',60) returning id", [code]))[0].id
      const offering = (await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [course, intake, teacher]))[0].id
      return (await q('insert into class_sections(offering_id,group_number) values ($1,$2) returning id', [offering, group]))[0].id
    }
    const room = async (name) => (await q("insert into rooms(name,building,capacity,room_type) values ($1,'B',40,'classroom') returning id", [name]))[0].id
    const r1 = await room('R1'), r2 = await room('R2')
    const book = async (sec, roomId, start) => (await q('insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,$3) returning id', [sec, roomId, start]))[0].id
    const mine = await book(await section('C1', 1, lecturer), r1, '2026-11-16 01:00Z')
    const theirs = await book(await section('C2', 2, other), r2, '2026-11-17 01:00Z')

    const lecturerMove = 'select public.lecturer_reschedule_class($1,$2,$3,$4,$5,$6)'
    const adminMove = 'select public.admin_reschedule_class($1,$2,$3,$4,$5,$6)'

    await as(teacherUser, lecturerMove, [mine, '2026-11-16 01:00Z', r1, '2026-11-18 02:00Z', r2, 'Conference'])
    const row = (await q('select status, starts_at, room_id from class_sessions where id=$1', [mine]))[0]
    check(row.status === 'rescheduled' && row.room_id === r2 && new Date(row.starts_at).toISOString() === '2026-11-18T02:00:00.000Z',
      'the teaching lecturer can move their own class; it becomes rescheduled')
    const log = await q("select changed_by, reason, old_values, new_values from schedule_changes where class_session_id=$1 and action='reschedule'", [mine])
    check(log.length === 1 && log[0].changed_by === teacherUser && log[0].reason === 'Conference', 'the move and its history row are written together, by the lecturer')

    await rejectAs(otherUser, lecturerMove, [mine, '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, 'x'], /Only the lecturer who teaches this class/, "another lecturer cannot move someone else's class")
    await rejectAs(adminUser, lecturerMove, [mine, '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, 'x'], /Only the lecturer who teaches this class/, 'the lecturer function is only for the class lecturer')
    await rejectAs(teacherUser, adminMove, [mine, '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, 'x'], /Administrator access required/, 'a lecturer cannot use the admin function')
    await rejectAs(teacherUser, lecturerMove, ['00000000-0000-0000-0000-000000000001', '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, 'x'], /Class not found/, 'an unknown class is reported as not found')

    // Stale data and clashes are refused inside the lock; nothing changes.
    await rejectAs(teacherUser, lecturerMove, [mine, '2026-11-16 01:00Z', r1, '2026-11-19 02:00Z', r2, 'x'], /Class changed since it was loaded/, 'an outdated expected start is refused')
    await rejectAs(teacherUser, lecturerMove, [mine, '2026-11-18 02:00Z', r2, '2026-11-17 01:30Z', r2, 'x'], /another booking/, 'a room clash is refused')
    await rejectAs(teacherUser, lecturerMove, [mine, '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, ' '], /reason are required/, 'a blank reason is refused (the backend sends "No reason given")')
    check((await q("select count(*)::int as n from schedule_changes where class_session_id=$1", [mine]))[0].n === 1, 'refused moves write no history')

    // The admin path still works through the shared routine.
    await as(adminUser, adminMove, [theirs, '2026-11-17 01:00Z', r2, '2026-11-20 03:00Z', r1, 'Admin move'])
    check((await q('select room_id from class_sessions where id=$1', [theirs]))[0].room_id === r1, 'admins still move any class')

    // The shared routine cannot be called directly.
    await rejectAs(teacherUser, 'select campus_private.move_class_session($1,$2,$3,$4,$5,$6)', [mine, '2026-11-18 02:00Z', r2, '2026-11-19 02:00Z', r2, 'x'], /permission denied/, 'the internal routine is not callable by users')
    await assert.rejects(() => db.exec(`set role anon; select public.lecturer_reschedule_class(null,null,null,null,null,null)`), /permission denied/, 'anon cannot call it'); passed++
    await db.exec('reset role')
  } finally {
    await db.close()
  }
  console.log(`PASS: ${passed} lecturer reschedule checks (PostgreSQL via PGlite; mocked Auth).`)
})().catch(error => { console.error(error); process.exitCode = 1 })
