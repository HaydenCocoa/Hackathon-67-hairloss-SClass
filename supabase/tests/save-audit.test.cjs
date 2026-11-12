// Checks 202611120002_save_audit.sql on real local PostgreSQL (PGlite).
// Upgrades the legacy schema and a fresh schema.sql, after the teaching and status migrations.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { PGlite } = require('@electric-sql/pglite');
const { bootstrap } = require('./support.cjs');
const read = file => fs.readFileSync(path.join(__dirname, file), 'utf8');
let passed = 0;

async function run(baseSchema) {
  const db = new PGlite();
  const q = async (sql, params = []) => (await db.query(sql, params)).rows;
  const check = (value, label) => { assert.ok(value, `${baseSchema}: ${label}`); passed++; };
  const reject = async (sql, params, pattern) => {
    await assert.rejects(() => db.query(sql, params), pattern); passed++;
  };
  try {
    await db.exec(bootstrap);
    await db.exec(read(baseSchema));
    const admin = (await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id;
    const intake = (await q("insert into intakes(intake_code,max_group) values ('T',1) returning id"))[0].id;
    const lecturer = (await q("insert into lecturers(lecturer_code,full_name) values ('L1','Teacher') returning id"))[0].id;
    const course = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ('C1','Subject','lecture',90) returning id"))[0].id;
    const offering = (await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [course, intake, lecturer]))[0].id;
    const section = (await q("insert into class_sections(offering_id,required_room_type) values ($1,'classroom') returning id", [offering]))[0].id;
    const room = (await q("insert into rooms(name,building,capacity,room_type) values ('R1','B',50,'classroom') returning id"))[0].id;
    const before = (await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-02 09:00+08') returning id", [section, room]))[0].id;

    // Before the patch, 'create' is not an allowed action.
    await reject("insert into schedule_changes(class_session_id,changed_by,action,old_values,new_values) values ($1,$2,'create','{}','{}')", [before, admin], /check constraint/i);

    await db.exec(read('../migrations/202611100001_teaching_requirements.sql'));
    await db.exec(read('../migrations/202611120001_class_session_rescheduled_status.sql'));
    const migration = read('../migrations/202611120002_save_audit.sql');
    await db.exec(migration);
    await db.exec(migration); // rerun is harmless

    const checks = (await q("select conname from pg_constraint where conrelid='public.schedule_changes'::regclass and contype='c' order by conname")).map(r => r.conname);
    check(JSON.stringify(checks) === JSON.stringify(['schedule_changes_action_check', 'schedule_changes_new_values_check', 'schedule_changes_old_values_check', 'schedule_changes_one_session']), `only the action check was replaced (${checks})`);
    check((await q("select created_by from class_sessions where id=$1", [before]))[0].created_by === null, 'existing classes keep created_by NULL');
    check((await q('select count(*)::int n from schedule_changes'))[0].n === 0, 'the migration writes no audit rows');
    check((await q("select count(*)::int n from pg_trigger where tgname='audit_class_session_create'"))[0].n === 1, 'rerun leaves exactly one trigger');

    // A save: several occurrence-linked classes in ONE statement, each with created_by.
    const plan = (await q("insert into teaching_plans(section_id,first_week_start,week_count,occurrences_per_week) values ($1,'2026-11-09',1,2) returning id", [section]))[0].id;
    const occurrences = (await q('select id from teaching_occurrences where plan_id=$1 order by occurrence_number', [plan])).map(r => r.id);
    const saved = await q(`insert into class_sessions(section_id,occurrence_id,room_id,starts_at,status,created_by)
      values ($1,$2,$3,'2026-11-09 10:00+08','scheduled',$5), ($1,$4,$3,'2026-11-10 10:00+08','scheduled',$5) returning id, occurrence_id`,
      [section, occurrences[0], room, occurrences[1], admin]);
    const audit = await q("select * from schedule_changes where action='create' order by new_values->>'starts_at'");
    check(audit.length === 2, 'one create row per saved class');
    check(audit.every(r => r.changed_by === admin && r.meeting_session_id === null), 'changed_by is the saving user');
    check(audit.map(r => r.class_session_id).sort().join() === saved.map(r => r.id).sort().join(), 'each audit row points at its class');
    check(JSON.stringify(audit[0].old_values) === '{}', 'old values are empty for a create');
    const values = audit[0].new_values;
    check(values.occurrence_id === occurrences[0] && values.section_id === section && values.room_id === room && values.status === 'scheduled', 'new values describe the booking');
    check(new Date(values.starts_at).toISOString() === '2026-11-09T02:00:00.000Z', 'new values keep the exact start time');
    check(audit[0].created_at.getTime() === audit[1].created_at.getTime(), 'one save shares one audit timestamp');

    // A failed save writes neither classes nor audit rows (the duplicate occurrence fails the whole statement).
    const plan2 = (await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-16',1) returning id", [section]))[0].id;
    const fresh = (await q('select id from teaching_occurrences where plan_id=$1', [plan2]))[0].id;
    await reject(`insert into class_sessions(section_id,occurrence_id,room_id,starts_at,created_by)
      values ($1,$2,$3,'2026-11-16 10:00+08',$5), ($1,$4,$3,'2026-11-11 10:00+08',$5)`, [section, fresh, room, occurrences[0], admin], /unique|duplicate/i);
    check((await q('select count(*)::int n from class_sessions where occurrence_id=$1', [fresh]))[0].n === 0, 'failed save leaves no class');
    check((await q('select count(*)::int n from schedule_changes'))[0].n === 2, 'failed save leaves no audit row');

    // An unknown user is refused, so a save can never be attributed to nobody.
    await reject("insert into class_sessions(section_id,occurrence_id,room_id,starts_at,created_by) values ($1,$2,$3,'2026-11-16 10:00+08',gen_random_uuid())", [section, fresh, room], /foreign key/i);
    check((await q('select count(*)::int n from schedule_changes'))[0].n === 2, 'refused insert leaves no audit row');

    // Inserts without created_by (dashboard, seeds) still work and are not audited.
    await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-20 09:00+08')", [section, room]);
    check((await q('select count(*)::int n from schedule_changes'))[0].n === 2, 'no audit row without created_by');

    // Existing actions still work; unknown ones are still rejected.
    for (const action of ['cancel', 'reschedule']) {
      await q("insert into schedule_changes(class_session_id,changed_by,action,old_values,new_values) values ($1,$2,$3,'{}','{}')", [before, admin, action]);
    }
    check(true, 'cancel and reschedule are still accepted');
    await reject("insert into schedule_changes(class_session_id,changed_by,action,old_values,new_values) values ($1,$2,'delete','{}','{}')", [before, admin], /check constraint/i);

    // Audited classes cannot be deleted; history stays (cancel instead).
    await reject('delete from class_sessions where id=$1', [before], /foreign key|violates/i);
    await reject('delete from class_sessions where id=$1', [saved[0].id], /foreign key|violates|Cancel a linked booking/i);

    // Only the database owner may run the trigger function directly.
    const grants = await q("select has_function_privilege('authenticated','campus_private.audit_class_session_create()','execute') ok");
    check(grants[0].ok === false, 'logged-in users cannot execute the audit function');
  } finally {
    await db.close();
  }
}

(async () => {
  await run('fixtures/legacy_schema.sql');
  await run('../schema.sql');
  console.log(`save audit migration: ${passed} checks passed`);
})().catch(error => { console.error(error); process.exit(1); });
