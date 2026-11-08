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
  for (const file of ['seed_rooms.sql','seed_lecturers.sql']) await db.exec(read(file));
  // Reproduce the SQL Editor workflow: execute the seed as ONE statement, then
  // execute verification separately, without shared temporary-table state.
  const studentSeed = read('seed_students.sql');
  const seedBlock = studentSeed.match(/do \$seed_students\$[\s\S]*?\$seed_students\$;/i)[0];
  await db.query(seedBlock);
  const separateSummary = await q(studentSeed.slice(studentSeed.indexOf(seedBlock) + seedBlock.length));
  check(separateSummary.length===18 && separateSummary.reduce((n,r)=>n+r.sample_students,0)===1480,
    'standalone seed block and independent verification work without temporary tables');
  check((await q('select count(*)::int n from rooms'))[0].n === 71,'71 sample classrooms, labs and auditorium');
  check((await q('select count(*)::int n from rooms where not is_active'))[0].n === 7,'seven disabled classrooms and labs');
  check((await q('select count(*)::int n from lecturers'))[0].n === 20,'20 sample lecturers');
  check((await q('select count(*)::int n from students'))[0].n === 1000,'1000 distinct identities');
  check((await q('select count(distinct full_name)::int n from students'))[0].n === 1000,'1000 distinct names');
  const ages=await q('select age, count(*)::int n from students group by age order by age');
  check(ages.length===8 && ages.every((r,i)=>r.age===18+i && r.n===125),'1000 students have integer sample ages 18 through 25');
  check((await q('select count(*)::int n from student_intakes'))[0].n === 1480,'1480 planned memberships');
  const expected = {
   'APU1F2611CS(CYB)':[34,33,33], 'APU1F2611CS':[34,33,33],
   'APU1F2611CS(DF)':[34,33,33], 'APU1F2611CS(SE)':[40],
   'APD1F2611CS(CYB)':[34,33,33], 'APD1F2611CS':[34,33,33],
   'APD1F2611CS(DF)':[34,33,33], 'APD1F2611CS(SE)':[40],
   'APD1F2407CS(CYB)':[40,40], 'APD2F2506CS(CYB)':[40,40], 'APD3F2609CS(CYB)':[40,40],
   'APD1F2407CS':[40,40], 'APD2F2506CS':[40,40], 'APD3F2609CS':[40,40],
   'APD1F2507CS(CYB)':[40,40], 'APD2F2606CS(CYB)':[40,40],
   'APD1F2507CS':[40,40], 'APD2F2606CS':[40,40]
  };
  for (const [code,sizes] of Object.entries(expected)) {
   const groups = await q(`select m.group_number, count(*)::int n from student_intakes m
     join intakes i on i.id=m.intake_id where i.intake_code=$1
     group by m.group_number order by m.group_number`,[code]);
   check(JSON.stringify(groups.map(g=>g.n))===JSON.stringify(sizes),'correct groups for '+code);
  }
  const sharedCohorts = [
   [681,['APD1F2407CS(CYB)','APD2F2506CS(CYB)','APD3F2609CS(CYB)']],
   [761,['APD1F2407CS','APD2F2506CS','APD3F2609CS']],
   [841,['APD1F2507CS(CYB)','APD2F2606CS(CYB)']],
   [921,['APD1F2507CS','APD2F2606CS']]
  ];
  for(const [start,codes] of sharedCohorts) {
   const expectedCodes=Array.from({length:80},(_,i)=>'TP'+String(start+i).padStart(6,'0'));
   for(const code of codes) {
    const actual=await q(`select s.student_code from students s
      join student_intakes m on m.student_id=s.id join intakes i on i.id=m.intake_id
      where i.intake_code=$1 order by s.student_code`,[code]);
    check(JSON.stringify(actual.map(r=>r.student_code))===JSON.stringify(expectedCodes),
      'same 80 student identities reused for '+code);
   }
  }
  const identities=await q('select id, student_code from students order by student_code');
  const first=identities[0].id;
  const account=(await q('insert into auth.users values (gen_random_uuid()) returning id'))[0].id;
  await q('update students set auth_user_id=$1 where id=$2',[account,first]);
  const extraIntake=(await q("insert into intakes(intake_code) values ('EXTRA-OUTSIDE-PLAN') returning id"))[0].id;
  await q('insert into student_intakes values ($1,$2,1)',[first,extraIntake]);
  const outsideStudent=(await q("insert into students(student_code,full_name,age) values ('OUTSIDE','Outside Student',23) returning id"))[0].id;
  await q('insert into student_intakes values ($1,$2,1)',[outsideStudent,extraIntake]);
  const outputs = await db.exec(read('seed_students.sql'));
  const summary = outputs.find(r=>r.rows.length===18 && r.rows[0].sample_students!==undefined);
  check(!!summary && summary.rows.reduce((n,r)=>n+r.sample_students,0)===1480,'summary counts 1480 sample memberships');
  check((await q('select count(*)::int n from student_intakes'))[0].n===1481,'seed rerun replaces sample memberships but preserves outside membership');
  check((await q('select count(*)::int n from students'))[0].n===1001,'seed rerun preserves outside student and creates no duplicates');
  check(JSON.stringify(await q("select id, student_code from students where student_code<>'OUTSIDE' order by student_code"))===JSON.stringify(identities),'seed rerun preserves all UUIDs');
  check((await q('select * from student_intakes where student_id=$1 and intake_id=$2',[first,extraIntake])).length===0,'outdated sample membership removed');
  check((await q('select auth_user_id from students where id=$1',[first]))[0].auth_user_id===account,'seed rerun preserves linked login');
  await db.exec(read('seed_rooms.sql'));
  await db.exec(read('seed_lecturers.sql'));
  check((await q('select count(*)::int n from rooms'))[0].n===71,'rooms rerun without duplicates');
  check((await q('select count(*)::int n from lecturers'))[0].n===20,'lecturers rerun without duplicates');
 } finally { await db.close(); }
}
async function atomicSeedChecks() {
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  const intake=(await q("insert into intakes(intake_code,max_group) values ('APD2F2606CS',3) returning id"))[0].id;
  const student=(await q("insert into students(student_code,full_name) values ('EXISTING','Existing Student') returning id"))[0].id;
  await q('insert into student_intakes values ($1,$2,3)',[student,intake]);
  const sample=(await q("insert into students(student_code,full_name,age) values ('TP000001','Previous Sample',42) returning id"))[0].id;
  await q('insert into student_intakes values ($1,$2,1)',[sample,intake]);
  const seedBlock=read('seed_students.sql').match(/do \$seed_students\$[\s\S]*?\$seed_students\$;/i)[0];
  // This conflict occurs late, after earlier planned rows have been processed.
  await assert.rejects(()=>db.query(seedBlock),/Cannot reduce max_group/); passed++;
  check((await q('select count(*)::int n from students'))[0].n===2,'failed seed rolls back partially inserted students');
  check((await q('select count(*)::int n from intakes'))[0].n===1,'failed seed rolls back partially inserted intakes');
  check((await q('select group_number from student_intakes where student_id=$1',[student]))[0].group_number===3,'failed seed preserves existing membership');
  check((await q('select group_number from student_intakes where student_id=$1',[sample]))[0].group_number===1,'failed seed restores deleted sample membership');
  check((await q('select age from students where id=$1',[sample]))[0].age===42,'failed seed restores previous sample age');
 } finally { await db.close(); }
}
async function previousSeedRefreshChecks() {
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  const oldPlan=[
   ['APD1F2407CS(CYB)',100,3],['APD1F2407CS',200,6],['APD1F2407CS(SE)',40,1],
   ['APD2F2506CS(CYB)',100,3],['APD2F2506CS',200,6],['APD2F2506CS(SE)',40,1],
   ['APD3F2609CS(CYB)',80,2],['APD3F2609CS',200,6],['APD3F2609CS(SE)',40,1]
  ];
  const rows=[];
  for(const [code,count,groups] of oldPlan) {
   await q('insert into intakes(intake_code,max_group) values ($1,$2)',[code,groups]);
   for(let n=0;n<count;n++)rows.push({student_code:'TP'+String(rows.length+1).padStart(6,'0'),
     full_name:'Legacy Student '+(rows.length+1),intake_code:code,group_number:n%groups+1});
  }
  await q(`insert into students(student_code,full_name,age)
    select student_code,full_name,30 from jsonb_to_recordset($1::jsonb)
    as r(student_code text,full_name text)`,[JSON.stringify(rows)]);
  await q(`insert into student_intakes(student_id,intake_id,group_number)
    select s.id,i.id,r.group_number from jsonb_to_recordset($1::jsonb)
    as r(student_code text,intake_code text,group_number integer)
    join students s on s.student_code=r.student_code join intakes i on i.intake_code=r.intake_code`,[JSON.stringify(rows)]);
  const identities=await q('select id,student_code from students order by student_code');
  const account=(await q('insert into auth.users values(gen_random_uuid()) returning id'))[0].id;
  await q('update students set auth_user_id=$1 where id=$2',[account,identities[0].id]);
  await db.exec(read('seed_students.sql'));
  check((await q('select count(*)::int n from students'))[0].n===1000,'refresh prior dataset keeps 1000 students');
  check(JSON.stringify(await q('select id,student_code from students order by student_code'))===JSON.stringify(identities),'refresh prior dataset preserves all student UUIDs');
  check((await q('select auth_user_id from students where id=$1',[identities[0].id]))[0].auth_user_id===account,'refresh prior dataset preserves login link');
  check((await q('select count(*)::int n from student_intakes'))[0].n===1480,'refresh prior dataset replaces 1000 old memberships with 1480 new memberships');
  check((await q("select count(*)::int n from student_intakes m join intakes i on i.id=m.intake_id where i.intake_code in ('APD1F2407CS(SE)','APD2F2506CS(SE)','APD3F2609CS(SE)')"))[0].n===0,'obsolete seed memberships removed');
  check((await q("select count(*)::int n from intakes where intake_code in ('APD1F2407CS(SE)','APD2F2506CS(SE)','APD3F2609CS(SE)')"))[0].n===3,'unused older intake records retained');
  check((await q("select max_group from intakes where intake_code='APD2F2506CS'"))[0].max_group===2,'old six-group intake safely reduced after old memberships removed');
  check((await q('select i.intake_code from student_intakes m join intakes i on i.id=m.intake_id where m.student_id=$1',[identities[0].id]))[0].intake_code==='APU1F2611CS(CYB)','first sample student reassigned to new cohort');
 } finally { await db.close(); }
}
async function migrationChecks() {
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const upgrade=read('migrations/202611080001_student_intake_memberships.sql');
 const ageUpgrade=read('migrations/202611080002_student_age.sql');
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
  await db.exec(ageUpgrade);
  check((await q('select age from students where id=$1',[student]))[0].age===null,'age upgrade preserves existing student with unknown age');
  await q('update students set age=22 where id=$1',[student]);
  await db.exec(ageUpgrade);
  check((await q('select age from students where id=$1',[student]))[0].age===22,'repeated age upgrade preserves known ages');
  await assert.rejects(()=>q('update students set age=-1 where id=$1',[student]),/students_age_nonnegative/); passed++;
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
 await atomicSeedChecks();
 await previousSeedRefreshChecks();
 await migrationChecks();
 console.log(`PASS: ${passed} seed/membership/upgrade checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
})().catch(e=>{console.error(e);process.exitCode=1;});
