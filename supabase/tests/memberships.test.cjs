// Checks sample-data reruns and preservation of existing data during upgrade.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { PGlite } = require('@electric-sql/pglite');
const { bootstrap } = require('./support.cjs');
const read = name => fs.readFileSync(path.resolve(__dirname, '..', name), 'utf8');
let passed = 0;
const check = (value, label) => { assert.ok(value, label); passed++; };
async function seedChecks() {
 const db = new PGlite();
 const q = async(s,p=[]) => (await db.query(s,p)).rows;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  for (const file of ['seed_rooms.sql','seed_lecturers.sql','seed_students.sql']) await db.exec(read(file));
  check((await q('select count(*)::int n from rooms'))[0].n === 71,'71 sample classrooms, labs and auditorium');
  check((await q('select count(*)::int n from rooms where not is_active'))[0].n === 7,'seven disabled classrooms and labs');
  check((await q('select count(*)::int n from lecturers'))[0].n === 20,'20 sample lecturers');
  check((await q('select count(*)::int n from students'))[0].n === 1000,'1000 distinct identities');
  check((await q('select count(distinct full_name)::int n from students'))[0].n === 1000,'1000 distinct names');
  check((await q('select count(*)::int n from student_intakes'))[0].n === 1000,'1000 initial memberships');
  const expected = {
   'APD1F2407CS(CYB)':[34,33,33], 'APD1F2407CS':[34,34,33,33,33,33], 'APD1F2407CS(SE)':[40],
   'APD2F2506CS(CYB)':[34,33,33], 'APD2F2506CS':[34,34,33,33,33,33], 'APD2F2506CS(SE)':[40],
   'APD3F2609CS(CYB)':[40,40], 'APD3F2609CS':[34,34,33,33,33,33], 'APD3F2609CS(SE)':[40]
  };
  for (const [code,sizes] of Object.entries(expected)) {
   const groups = await q(`select m.group_number, count(*)::int n from student_intakes m
     join intakes i on i.id=m.intake_id where i.intake_code=$1
     group by m.group_number order by m.group_number`,[code]);
   check(JSON.stringify(groups.map(g=>g.n))===JSON.stringify(sizes),'correct groups for '+code);
  }
  const identities=await q('select id, student_code from students order by student_code');
  const first=identities[0].id;
  const account=(await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id;
  await q('update students set auth_user_id=$1 where id=$2',[account,first]);
  const extraIntake=(await q("select id from intakes where intake_code='APD2F2506CS(SE)'"))[0].id;
  await q('insert into student_intakes values ($1,$2,1)',[first,extraIntake]);
  const outputs = await db.exec(read('seed_students.sql'));
  const summary = outputs.find(r=>r.rows.length===9 && r.rows[0].sample_students!==undefined);
  check(!!summary && summary.rows.reduce((n,r)=>n+r.sample_students,0)===1000,'summary counts only initial planned memberships');
  check((await q('select count(*)::int n from student_intakes'))[0].n===1001,'seed rerun preserves extra membership');
  check((await q('select count(*)::int n from students'))[0].n===1000,'seed rerun creates no duplicate identities');
  check(JSON.stringify(await q('select id, student_code from students order by student_code'))===JSON.stringify(identities),'seed rerun preserves all UUIDs');
  check((await q('select auth_user_id from students where id=$1',[first]))[0].auth_user_id===account,'seed rerun preserves linked login');
  await db.exec(read('seed_rooms.sql'));
  await db.exec(read('seed_lecturers.sql'));
  check((await q('select count(*)::int n from rooms'))[0].n===71,'rooms rerun without duplicates');
  check((await q('select count(*)::int n from lecturers'))[0].n===20,'lecturers rerun without duplicates');
 } finally { await db.close(); }
}
async function migrationChecks() {
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const upgrade=read('migrations/202611080001_student_intake_memberships.sql');
 try {
  await db.exec(bootstrap);
  await db.exec(read('tests/fixtures/legacy_schema.sql'));
  const account=(await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id;
  const intake=(await q("insert into intakes(intake_code,max_group) values ('OLD',3) returning id"))[0].id;
  const student=(await q("insert into students(student_code,full_name,auth_user_id,intake_id,group_number) values ('S1','Existing Student',$1,$2,3) returning id",[account,intake]))[0].id;
  const lecturer=(await q("insert into lecturers(lecturer_code,full_name) values ('L1','Existing Lecturer') returning id"))[0].id;
  const course=(await q("insert into courses(course_code,name,course_type,duration_minutes) values ('C1','Existing Course','lecture',60) returning id"))[0].id;
  const offering=(await q('insert into course_offerings(course_id,intake_id,lecturer_id) values ($1,$2,$3) returning id',[course,intake,lecturer]))[0].id;
  const section=(await q("insert into class_sections(offering_id,group_number,required_room_type) values ($1,3,'classroom') returning id",[offering]))[0].id;
  const room=(await q("insert into rooms(name,building,capacity,room_type) values ('A1','A',50,'classroom') returning id"))[0].id;
  const session=(await q("insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,now()) returning id",[section,room]))[0].id;
  const meeting=(await q('insert into meeting_sessions(lecturer_id,starts_at,ends_at) values ($1,now(),now()+interval \'1 hour\') returning id',[lecturer]))[0].id;
  await q('insert into meeting_students values ($1,$2)',[meeting,student]);
  await q("insert into schedule_changes(class_session_id,changed_by,action,old_values,new_values) values ($1,$2,'reschedule','{}','{}')",[session,account]);
  // Unknown dependencies must cause a full rollback, not a destructive CASCADE.
  await db.exec('create view public.external_dependency as select intake_id from students');
  await assert.rejects(()=>db.exec(upgrade),/depend/i); passed++;
  await db.exec('rollback');
  check((await q('select intake_id from students'))[0].intake_id===intake,'failed migration preserves old membership columns');
  check((await q("select to_regclass('public.student_intakes') as t"))[0].t===null,'failed migration rolls back the new table');
  await db.exec('drop view public.external_dependency');
  await db.exec(upgrade);
  check((await q('select count(*)::int n from student_intakes'))[0].n===1,'upgrade backfills membership');
  const membership=(await q('select * from student_intakes'))[0];
  check(membership.student_id===student && membership.intake_id===intake && membership.group_number===3,'upgrade preserves previous group and intake');
  check((await q('select auth_user_id from students where id=$1',[student]))[0].auth_user_id===account,'upgrade preserves student login');
  check((await q('select * from meeting_students'))[0].student_id===student,'upgrade preserves meeting attendance');
  check((await q('select * from schedule_changes'))[0].class_session_id===session,'upgrade preserves change history');
  check((await q('select id from class_session_details'))[0].id===session,'upgrade preserves class timetable view');
  check((await q("select column_name from information_schema.columns where table_name='students' and column_name in ('intake_id','group_number')")).length===0,'upgrade removes old identity columns');
  check((await q("select count(*)::int n from pg_tables where schemaname='public' and rowsecurity"))[0].n===13,'upgraded schema has RLS on 13 tables');
  await assert.rejects(()=>q('update intakes set max_group=2 where id=$1',[intake]),/Cannot reduce max_group/); passed++;
  const extra=(await q("insert into intakes(intake_code) values ('EXTRA') returning id"))[0].id;
  await q('insert into student_intakes values ($1,$2,1)',[student,extra]);
  await q("select set_config('request.jwt.claim.sub',$1,false)",[account]);
  await db.exec('set role authenticated');
  check((await q('select * from student_intakes')).length===2,'upgraded RLS allows own multiple memberships');
  check((await q('select * from class_session_details')).length===1,'upgraded RLS allows previous intake timetable');
  await assert.rejects(()=>q('insert into student_intakes values ($1,$2,1)',[student,intake]),/permission denied/); passed++;
  await db.exec('reset role');
  await assert.rejects(()=>db.exec(upgrade),/already exists/); passed++;
  await db.exec('rollback');
  check((await q('select count(*)::int n from student_intakes'))[0].n===2,'repeat upgrade fails without losing memberships');
 } finally { await db.close(); }
}
(async()=>{
 await seedChecks();
 await migrationChecks();
 console.log(`PASS: ${passed} seed/membership/upgrade checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
})().catch(e=>{console.error(e);process.exitCode=1;});
