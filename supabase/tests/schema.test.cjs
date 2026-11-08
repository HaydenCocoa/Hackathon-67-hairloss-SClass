// PostgreSQL smoke/integrity tests using @electric-sql/pglite.
// Run: NODE_PATH=<temporary install>/node_modules node supabase/tests/schema.test.cjs
// Auth is minimally mocked; these tests do not replace hosted Supabase checks.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { PGlite } = require('@electric-sql/pglite');
const schema = fs.readFileSync(path.resolve(__dirname, '../schema.sql'), 'utf8');
const { bootstrap } = require('./support.cjs');
let passed = 0;
async function main() {
 const db = new PGlite();
 const q = async(sql, params=[]) => (await db.query(sql, params)).rows;
 const check = (value, label) => { assert.ok(value,label); passed++; };
 const reject = async(sql, params, pattern) => {
   await assert.rejects(()=>db.query(sql,params),pattern); passed++;
 };
 try {
  await db.exec(bootstrap);
  await db.exec(schema);
  check((await q("select count(*)::int n from pg_tables where schemaname='public'"))[0].n===13,'13 application tables');
  check((await q("select count(*)::int n from pg_tables where schemaname='public' and rowsecurity"))[0].n===13,'RLS on all tables');
  check((await q("select column_name from information_schema.columns where table_schema='public' and table_name='students' and column_name in ('intake_id','group_number')")).length===0,'identity has no intake/group fields');
  check((await q("select data_type from information_schema.columns where table_schema='public' and table_name='students' and column_name='age'"))[0].data_type==='integer','student age is an integer');
  const users = await q('insert into auth.users select gen_random_uuid() from generate_series(1,4) returning id');
  const [studentUser, otherUser, lecturerUser, adminUser] = users.map(r=>r.id);
  const intake=(await q("insert into intakes(intake_code,max_group) values ('CS-2026',3) returning id"))[0].id;
  const small=(await q("insert into intakes(intake_code) values ('CS-2027') returning id"))[0].id;
  const student=(await q("insert into students(auth_user_id,student_code,full_name) values ($1,'S1','Student 1') returning id",[studentUser]))[0].id;
  const other=(await q("insert into students(auth_user_id,student_code,full_name) values ($1,'S2','Student 2') returning id",[otherUser]))[0].id;
  await reject('update students set age=-1 where id=$1',[student],/students_age_nonnegative/i);
  await q('insert into student_intakes(student_id,intake_id,group_number) values ($1,$2,3),($3,$4,1)',[student,intake,other,small]);
  const lecturer=(await q("insert into lecturers(auth_user_id,lecturer_code,full_name) values ($1,'L1','Lecturer 1') returning id",[lecturerUser]))[0].id;
  await q("insert into admins(auth_user_id,full_name) values ($1,'Admin 1')",[adminUser]);
  const course=(await q("insert into courses(course_code,name,course_type,duration_minutes) values ('CS101','Databases','lecture',90) returning id"))[0].id;
  const lab=(await q("insert into courses(course_code,name,course_type,duration_minutes) values ('CS101','Databases','lab',120) returning id"))[0].id;
  check(lab!==course,'same subject can have lecture and lab');
  await reject("insert into courses(course_code,name,course_type,duration_minutes) values ('CS101','Duplicate','lecture',90)",[],/unique/i);
  await reject("insert into courses(course_code,name,course_type,duration_minutes) values ('BAD','Invalid','lecture',0)",[],/check constraint/i);
  await reject("insert into courses(course_code,name,course_type,duration_minutes) values ('BAD','Invalid','seminar',60)",[],/check constraint/i);
  await reject('insert into student_intakes(student_id,intake_id,group_number) values ($1,$2,4)',[other,intake],/exceeds intake maximum/i);
  await reject('update student_intakes set intake_id=$1 where student_id=$2',[small,student],/exceeds intake maximum/i);
  await reject('insert into student_intakes values ($1,$2,1)',[student,intake],/unique/i);
  await reject('insert into student_intakes values ($1,$2,0)',[student,small],/check constraint/i);
  await reject('update intakes set max_group=2 where id=$1',[intake],/Cannot reduce max_group/i);
  const offering=(await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id',[course,intake,lecturer]))[0].id;
  const section=(await q("insert into class_sections(offering_id,group_number,required_room_type) values ($1,3,'classroom') returning id",[offering]))[0].id;
  await reject("insert into class_sections(offering_id,group_number,required_room_type) values ($1,4,'classroom')",[offering],/exceeds intake maximum/i);
  await reject('update course_offerings set intake_id=$1 where id=$2',[small,offering],/does not support/i);
  // Remove the student from group 3: sections must independently prevent shrinking.
  await q('update student_intakes set group_number=1 where student_id=$1',[student]);
  await reject('update intakes set max_group=2 where id=$1',[intake],/Cannot reduce max_group/i);
  await q('update student_intakes set group_number=3 where student_id=$1',[student]);
  const room=(await q("insert into rooms(name,building,capacity,room_type) values ('A101','A',40,'classroom') returning id"))[0].id;
  await reject("insert into class_sessions(section_id,starts_at) values ($1,'2026-11-09 10:00+08')",[section],/scheduled_class_requires_room/i);
  const session=(await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-09 10:00+08') returning id",[section,room]))[0].id;
  check((await q("select extract(epoch from (ends_at-starts_at))::int seconds from class_session_details where id=$1",[session]))[0].seconds===5400,'90-minute derived end');
  await reject('update courses set duration_minutes=120 where id=$1',[course],/Duration is locked/i);
  await reject('update course_offerings set course_id=$1 where id=$2',[lab,offering],/Cannot change offering/i);
  const otherOffering=(await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id',[lab,intake,lecturer]))[0].id;
  await reject('update class_sections set offering_id=$1 where id=$2',[otherOffering,section],/Cannot change a section offering/i);
  await reject("insert into meeting_sessions(lecturer_id,starts_at,ends_at) values ($1,now(),now())",[lecturer],/meeting_positive_duration/i);
  const meeting=(await q("insert into meeting_sessions(lecturer_id,starts_at,ends_at) values ($1,'2026-11-10 10:00+08','2026-11-10 11:00+08') returning id",[lecturer]))[0].id;
  await q('insert into meeting_students values ($1,$2),($1,$3)',[meeting,student,other]);
  await reject('insert into meeting_students values ($1,$2)',[meeting,student],/unique/i);
  await reject("insert into schedule_changes(changed_by,action,old_values,new_values) values ($1,'cancel','{}','{}')",[adminUser],/schedule_changes_one_session/i);
  await reject("insert into schedule_changes(changed_by,class_session_id,meeting_session_id,action,old_values,new_values) values ($1,$2,$3,'cancel','{}','{}')",[adminUser,session,meeting],/schedule_changes_one_session/i);
  await q("insert into schedule_changes(changed_by,class_session_id,action,old_values,new_values) values ($1,$2,'reschedule','{}','{}')",[adminUser,session]);
  const login=async(id,role='authenticated')=>{
    await db.exec('reset role');
    await q("select set_config('request.jwt.claim.sub',$1,false)",[id||'']);
    await db.exec('set role '+role);
  };
  await login(studentUser);
  check((await q('select * from students')).length===1,'student sees only self');
  check((await q('select * from student_intakes')).length===1,'student sees only own membership');
  check((await q('select * from class_session_details')).length===1,'student sees own class through RLS view');
  check((await q('select * from schedule_changes')).length===1,'student sees relevant history');
  check((await q('select * from meeting_sessions')).length===1,'student sees own meeting');
  check((await q('select * from meeting_students')).length===1,'student cannot see fellow attendees');
  check((await q('select * from admins')).length===0,'student cannot read admin identities');
  await reject("insert into admins(full_name) values ('Self promotion')",[],/permission denied/i);
  await reject('insert into student_intakes values ($1,$2,1)',[student,small],/permission denied/i);
  await reject('update class_sessions set starts_at=now() where id=$1',[session],/permission denied/i);
  await login(otherUser);
  check((await q('select * from class_session_details')).length===0,'other intake cannot see class');
  check((await q('select * from schedule_changes')).length===0,'other intake cannot see history');
  await db.exec('reset role');
  const secondOffering=(await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id',[course,small,lecturer]))[0].id;
  const secondSection=(await q("insert into class_sections(offering_id,required_room_type) values ($1,'classroom') returning id",[secondOffering]))[0].id;
  await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,'2026-11-11 10:00+08')",[secondSection,room]);
  await q('insert into student_intakes values ($1,$2,1)',[student,small]);
  await login(studentUser);
  check((await q('select * from students')).length===1,'multiple intakes do not duplicate identity');
  check((await q('select * from student_intakes')).length===2,'student sees both intake memberships');
  check((await q('select * from class_session_details')).length===2,'student sees classes across both intakes');
  await db.exec('reset role');
  await q('delete from student_intakes where student_id=$1 and intake_id=$2',[student,small]);
  await login(studentUser);
  check((await q('select * from class_session_details')).length===1,'removed membership revokes the second intake timetable');
  await login(lecturerUser);
  check((await q('select * from class_session_details')).length===2,'lecturer sees teaching schedule');
  check((await q('select * from meeting_students')).length===2,'hosting lecturer sees meeting attendees');
  await login(adminUser);
  check((await q('select * from students')).length===2,'admin sees both students');
  check((await q('select * from class_session_details')).length===2,'admin sees class view');
  check((await q('select * from student_intakes')).length===2,'admin sees all memberships');
  await login(null,'anon');
  await reject('select * from students',[],/permission denied/i);
  await reject('select * from student_intakes',[],/permission denied/i);
  await reject('select * from class_session_details',[],/permission denied/i);
  await db.exec('reset role');
  // A failed rerun must not modify existing data.
  await assert.rejects(()=>db.exec(schema),/already exists/i);
  await db.exec('rollback');
  check((await q('select * from students')).length===2,'failed rerun preserves data');
 } finally { await db.close(); }

 const existing = new PGlite();
 try {
  await existing.exec(bootstrap);
  await existing.exec(`create table public.rooms (
    id uuid primary key default gen_random_uuid(),name text not null unique,
    building text not null,capacity integer not null check(capacity>0),
    room_type text not null check(room_type in ('classroom','lab','auditorium')),
    is_active boolean not null default true);
    insert into rooms(name,building,capacity,room_type) values ('Existing','A',20,'classroom');
    alter table rooms enable row level security;
    create policy "Logged-in users can view rooms" on rooms for select to authenticated using(true);`);
  await existing.exec(schema);
  check((await existing.query('select name from rooms')).rows[0].name==='Existing','earlier tutorial rooms and data preserved');
 } finally { await existing.close(); }
 console.log(`PASS: ${passed} schema/integrity/access checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
