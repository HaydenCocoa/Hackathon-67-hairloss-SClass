// Real local PostgreSQL; Supabase Auth is the existing minimal test stand-in.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { PGlite } = require('@electric-sql/pglite');
const { bootstrap } = require('./support.cjs');
const dateText = value => value instanceof Date ? value.toISOString().slice(0, 10) : value;
let passed = 0;

async function main() {
  const db = new PGlite();
  const q = async (sql, params = []) => (await db.query(sql, params)).rows;
  const check = (value, label) => { assert.ok(value, label); passed++; };
  const reject = async (sql, params, pattern) => {
    await assert.rejects(() => db.query(sql, params), pattern); passed++;
  };
  const count = async (sql, params = []) => (await q(sql, params))[0].n;
  try {
    await db.exec(bootstrap);
    await db.exec(fs.readFileSync(path.join(__dirname, '../schema.sql'), 'utf8'));
    const users = await q('insert into auth.users select gen_random_uuid() from generate_series(1,4) returning id');
    const [studentUser, outsiderUser, lecturerUser, adminUser] = users.map(r => r.id);
    const intake = (await q("insert into intakes(intake_code,max_group) values ('TEST',2) returning id"))[0].id;
    const lecturer = (await q("insert into lecturers(auth_user_id,lecturer_code,full_name) values ($1,'L1','Teacher') returning id", [lecturerUser]))[0].id;
    const otherLecturer = (await q("insert into lecturers(lecturer_code,full_name) values ('L2','Other Teacher') returning id"))[0].id;
    await q("insert into admins(auth_user_id,full_name) values ($1,'Admin')", [adminUser]);
    for (const [user, code, group] of [[studentUser, 'S1', 1], [outsiderUser, 'S2', 2]]) {
      const student = (await q('insert into students(auth_user_id,student_code,full_name) values ($1,$2,$2) returning id', [user, code]))[0].id;
      await q('insert into student_intakes values ($1,$2,$3)', [student, intake, group]);
    }
    const course = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ('CS1','Subject','lecture',90) returning id"))[0].id;
    const lab = (await q("insert into courses(course_code,name,course_type,duration_minutes) values ('CS1','Subject','lab',120) returning id"))[0].id;
    const sections = [];
    const offerings = [];
    for (const [courseId, roomType] of [[course, 'classroom'], [lab, 'lab']]) {
      const offering = (await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id', [courseId, intake, lecturer]))[0].id;
      offerings.push(offering);
      sections.push((await q('insert into class_sections(offering_id,required_room_type) values ($1,$2) returning id', [offering, roomType]))[0].id);
    }
    const room = (await q("insert into rooms(name,building,capacity,room_type) values ('R1','B',50,'classroom') returning id"))[0].id;
    const legacy = (await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-02 09:00+08') returning id", [sections[0], room]))[0].id;
    const migration = fs.readFileSync(path.join(__dirname, '../migrations/202611100001_teaching_requirements.sql'), 'utf8');
    await db.exec(migration);
    check((await q('select occurrence_id from class_sessions where id=$1', [legacy]))[0].occurrence_id === null, 'legacy booking preserved without guessed linkage');

    const plan = (await q("insert into teaching_plans(section_id,first_week_start,week_count,occurrences_per_week) values ($1,'2026-11-09',3,2) returning id", [sections[0]]))[0].id;
    await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-09',3)", [sections[1]]);
    check(await count('select count(*)::int n from teaching_occurrences') === 9, 'three weeks of two lectures and one lab yields nine occurrences');
    check(await count("select count(*)::int n from teaching_occurrence_details where target_week_start='2026-11-09' and needs_scheduling") === 3, 'three requirements in first week');
    check(await count("select count(*)::int n from teaching_occurrence_details where target_week_start='2026-11-16'") === 3, 'three requirements in second week');
    check(await count("select count(*)::int n from teaching_occurrence_details where target_week_start='2026-11-30'") === 0, 'recurrence stops after the identified period');
    check(await count("select count(distinct occurrence_id)::int n from teaching_occurrence_details") === 9, 'distinct identities for each required lesson');
    check((await q('select materialize_teaching_plan($1) n', [plan]))[0].n === 0, 'repeated expansion inserts nothing');
    check(await count('select count(*)::int n from teaching_occurrence_details where lecturer_id=$1', [lecturer]) === 9, 'same lecturer throughout period');
    check((await q("select duration_minutes from teaching_occurrence_details where course_type='lab' limit 1"))[0].duration_minutes === 120, 'lab duration comes from course');
    check((await q("select duration_minutes from teaching_occurrence_details where course_type='lecture' limit 1"))[0].duration_minutes === 90, 'lecture duration comes from course');
    check((await q("select teaching_week_number from teaching_occurrence_details where original_week_start='2026-11-23' limit 1"))[0].teaching_week_number === 3, 'teaching week number resolves from period start');
    const unbooked = (await q("select id from teaching_occurrences where plan_id=$1 and original_week_start='2026-11-23' and occurrence_number=2", [plan]))[0].id;
    await q("update teaching_occurrences set requirement_status='cancelled' where id=$1", [unbooked]);
    await q('select materialize_teaching_plan($1)', [plan]);
    check(!(await q('select needs_scheduling from teaching_occurrence_details where occurrence_id=$1', [unbooked]))[0].needs_scheduling, 'unscheduled occurrence cancellation survives recurrence expansion');
    await reject('select materialize_teaching_plan($1)', ['00000000-0000-0000-0000-000000000000'], /does not exist/i);

    await reject("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-12-08',3)", [sections[0]], /check constraint/i);
    await reject("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-12-07',0)", [sections[0]], /check constraint/i);
    await reject("insert into teaching_plans(section_id,first_week_start,week_count,occurrences_per_week) values ($1,'2026-12-07',2,0)", [sections[0]], /check constraint/i);
    await reject("insert into teaching_plans(section_id,first_week_start,week_count,timezone) values ($1,'2026-12-07',2,'Invalid/Zone')", [sections[0]], /Unknown teaching-plan timezone/i);
    await reject("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-16',2)", [sections[0]], /must not overlap/i);
    await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-30',1)", [sections[0]]);
    check(await count('select count(*)::int n from teaching_occurrences') === 10, 'adjacent non-overlapping period is allowed');
    await reject('update teaching_plans set week_count=4 where id=$1', [plan], /fixed after occurrences exist/i);
    await reject('update course_offerings set lecturer_id=$1 where id=$2', [otherLecturer, offerings[1]], /lecturer are fixed/i);
    await reject('update courses set duration_minutes=100 where id=$1', [lab], /duration and type are fixed/i);
    await reject('update class_sections set group_number=2 where id=$1', [sections[1]], /teaching details are fixed/i);

    const occurrence = (await q("select * from teaching_occurrences where plan_id=$1 and original_week_start='2026-11-09' and occurrence_number=1", [plan]))[0];
    await reject('update teaching_occurrences set occurrence_number=2 where id=$1', [occurrence.id], /immutable/i);
    await reject('delete from teaching_occurrences where id=$1', [occurrence.id], /instead of deleting/i);
    await reject("insert into teaching_occurrences(plan_id,section_id,original_week_start,target_week_start,occurrence_number) values ($1,$2,'2027-01-04','2027-01-04',1)", [plan, sections[0]], /does not match/i);
    await reject("insert into teaching_occurrences(plan_id,section_id,original_week_start,target_week_start,occurrence_number) values ($1,$2,'2026-11-09','2026-11-09',3)", [plan, sections[0]], /does not match/i);
    await reject("insert into class_sessions(section_id,occurrence_id,room_id,starts_at) values ($1,$2,$3,'2026-11-09 10:00+08')", [sections[1], occurrence.id, room], /foreign key/i);

    const booking = (await q("insert into class_sessions(section_id,occurrence_id,room_id,starts_at) values ($1,$2,$3,'2026-11-09 10:00+08') returning id", [sections[0], occurrence.id, room]))[0].id;
    check(!(await q('select needs_scheduling from teaching_occurrence_details where occurrence_id=$1', [occurrence.id]))[0].needs_scheduling, 'already booked occurrence is excluded from outstanding demand');
    await reject("insert into class_sessions(section_id,occurrence_id,room_id,starts_at) values ($1,$2,$3,'2026-11-10 10:00+08')", [sections[0], occurrence.id, room], /unique/i);
    await reject('update class_sessions set occurrence_id=null where id=$1', [booking], /Cannot detach/i);
    await reject('delete from class_sessions where id=$1', [booking], /instead of deleting/i);
    await reject("update teaching_occurrences set requirement_status='cancelled' where id=$1", [occurrence.id], /Update the linked booking/i);
    await reject("update teaching_occurrences set target_week_start='2026-12-07' where id=$1", [occurrence.id], /Update the linked booking/i);
    await q("update class_sessions set starts_at='2026-12-06 16:30+00' where id=$1", [booking]);
    let moved = (await q('select * from teaching_occurrence_details where occurrence_id=$1', [occurrence.id]))[0];
    check(dateText(moved.target_week_start) === '2026-12-07', 'booking move uses Kuala Lumpur Monday, not UTC Sunday');
    check(dateText(moved.original_week_start) === '2026-11-09' && moved.teaching_week_number === 1, 'moving beyond original period preserves source week and identity');
    await q("update class_sessions set status='cancelled' where id=$1", [booking]);
    check((await q('select requirement_status,needs_scheduling from teaching_occurrence_details where occurrence_id=$1', [occurrence.id]))[0].requirement_status === 'cancelled', 'cancelling booking cancels its demand');
    await q('select materialize_teaching_plan($1)', [plan]);
    check(!(await q('select needs_scheduling from teaching_occurrence_details where occurrence_id=$1', [occurrence.id]))[0].needs_scheduling, 'regeneration never resurrects cancelled demand');
    await reject("update class_sessions set status='scheduled' where id=$1", [booking], /Explicitly reopen/i);
    await q("update teaching_occurrences set requirement_status='required',target_week_start='2026-12-14' where id=$1", [occurrence.id]);
    moved = (await q('select * from teaching_occurrence_details where occurrence_id=$1', [occurrence.id]))[0];
    check(moved.needs_scheduling && dateText(moved.target_week_start) === '2026-12-14', 'explicit make-up request creates outstanding demand in its selected week');
    await q("update class_sessions set status='scheduled',starts_at='2026-12-14 09:00+08' where id=$1", [booking]);
    check((await q('select occurrence_id from class_sessions where id=$1', [booking]))[0].occurrence_id === occurrence.id, 'replacement reuses original occurrence and booking identity');

    const login = async (user, role = 'authenticated') => {
      await db.exec('reset role');
      await q("select set_config('request.jwt.claim.sub',$1,false)", [user || '']);
      await db.exec(`set role ${role}`);
    };
    await login(studentUser);
    check(await count('select count(*)::int n from teaching_occurrence_details') === 10, 'student reads matching group requirements');
    await reject('select materialize_teaching_plan($1)', [plan], /permission denied/i);
    await reject("update teaching_occurrences set requirement_status='cancelled'", [], /permission denied/i);
    await login(outsiderUser);
    check(await count('select count(*)::int n from teaching_occurrence_details') === 0, 'other group cannot read requirements');
    await login(lecturerUser);
    check(await count('select count(*)::int n from teaching_occurrence_details') === 10, 'assigned lecturer reads requirements');
    await login(adminUser);
    check(await count('select count(*)::int n from teaching_occurrence_details') === 10, 'admin reads requirements');
    await login(null, 'anon');
    await reject('select * from teaching_occurrence_details', [], /permission denied/i);
    await reject('select materialize_teaching_plan($1)', [plan], /permission denied/i);
    await login(null, 'service_role');
    check((await q('select materialize_teaching_plan($1) n', [plan]))[0].n === 0, 'server role can safely repeat materialization');
    await db.exec('reset role');
    await assert.rejects(() => db.exec(migration), /already exists/i);
    await db.exec('rollback');
    check(await count('select count(*)::int n from teaching_occurrences') === 10, 'failed migration rerun preserves existing data');
  } finally { await db.close(); }
  console.log(`PASS: ${passed} teaching-requirement checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
