// Checks 202611120001_class_session_rescheduled_status.sql on real local PostgreSQL (PGlite).
// Upgrades the legacy schema (old two-value constraint) and a fresh schema.sql.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { PGlite } = require('@electric-sql/pglite');
const { bootstrap } = require('./support.cjs');
const read = file => fs.readFileSync(path.join(__dirname, file), 'utf8');
const dateText = value => value instanceof Date ? value.toISOString().slice(0, 10) : value;
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
    const intake = (await q("insert into intakes(intake_code,max_group) values ('T',1) returning id"))[0].id;
    const lecturer = (await q("insert into lecturers(lecturer_code,full_name) values ('L1','Teacher') returning id"))[0].id;
    const course = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ('C1','Subject','lecture',90) returning id"))[0].id;
    const offering = (await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [course, intake, lecturer]))[0].id;
    const section = (await q("insert into class_sections(offering_id,required_room_type) values ($1,'classroom') returning id", [offering]))[0].id;
    const room = (await q("insert into rooms(name,building,capacity,room_type) values ('R1','B',50,'classroom') returning id"))[0].id;
    const existing = (await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-02 09:00+08') returning id", [section, room]))[0].id;

    // Before the patch, the old constraint rejects the new value.
    if (baseSchema.includes('legacy')) {
      await reject("update class_sessions set status='rescheduled' where id=$1", [existing], /check constraint/i);
    }
    await db.exec(read('../migrations/202611100001_teaching_requirements.sql'));
    const migration = read('../migrations/202611120001_class_session_rescheduled_status.sql');
    await db.exec(migration);
    await db.exec(migration); // rerun is harmless

    const definitions = (await q("select conname, pg_get_constraintdef(oid) def from pg_constraint where conrelid='public.class_sessions'::regclass and contype='c' order by conname")).map(r => r.conname);
    check(JSON.stringify(definitions) === JSON.stringify(['class_sessions_status_check', 'scheduled_class_requires_room']), 'exactly the two expected status checks remain');
    check((await q("select status from class_sessions where id=$1", [existing]))[0].status === 'scheduled', 'existing rows are unchanged');
    const index = (await q("select indexdef from pg_indexes where indexname='class_sessions_room_time_idx'"))[0].indexdef;
    check(/rescheduled/.test(index) && /scheduled/.test(index), 'room/time index covers scheduled and rescheduled');

    await q("update class_sessions set status='rescheduled' where id=$1", [existing]);
    check(true, 'rescheduled is accepted');
    await reject("update class_sessions set status='postponed' where id=$1", [existing], /check constraint/i);
    await reject("update class_sessions set status='Rescheduled' where id=$1", [existing], /check constraint/i);
    await reject("update class_sessions set room_id=null where id=$1", [existing], /scheduled_class_requires_room/i);
    await q("update class_sessions set status='cancelled', room_id=null where id=$1", [existing]);
    check(true, 'a cancelled class may still have no room');

    // Occurrence-linked behaviour.
    const plan = (await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-09',2) returning id", [section]))[0].id;
    const occurrence = (await q("select id from teaching_occurrences where plan_id=$1 and original_week_start='2026-11-09'", [plan]))[0].id;
    const booking = (await q("insert into class_sessions(section_id,occurrence_id,room_id,starts_at) values ($1,$2,$3,'2026-11-09 10:00+08') returning id", [section, occurrence, room]))[0].id;
    await q("update class_sessions set status='rescheduled', starts_at='2026-11-18 14:00+08' where id=$1", [booking]);
    let detail = (await q('select * from teaching_occurrence_details where occurrence_id=$1', [occurrence]))[0];
    check(detail.booking_status === 'rescheduled' && detail.requirement_status === 'required', 'a moved class stays required with status rescheduled');
    check(dateText(detail.target_week_start) === '2026-11-16', 'moving to another week updates the target week');
    check(dateText(detail.original_week_start) === '2026-11-09', 'the original week is preserved');
    check(detail.needs_scheduling === false, 'a rescheduled class is not outstanding demand');
    await reject("update teaching_occurrences set requirement_status='cancelled' where id=$1", [occurrence], /Update the linked booking/i);
    await reject("update teaching_occurrences set target_week_start='2026-11-09' where id=$1", [occurrence], /Update the linked booking/i);
    await q("update class_sessions set status='cancelled' where id=$1", [booking]);
    detail = (await q('select * from teaching_occurrence_details where occurrence_id=$1', [occurrence]))[0];
    check(detail.requirement_status === 'cancelled' && detail.needs_scheduling === false, 'cancelling a rescheduled class cancels its demand');
    await reject("update class_sessions set status='rescheduled' where id=$1", [booking], /Explicitly reopen/i);
  } finally {
    await db.close();
  }
}

(async () => {
  await run('fixtures/legacy_schema.sql');
  await run('../schema.sql');
  console.log(`rescheduled status: ${passed} checks passed`);
})().catch(error => { console.error(error); process.exit(1); });
