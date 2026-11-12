// SQL patch only: backend contracts and room-selection policy are separate work.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
async function run(withTeaching){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const patch=read('migrations/202611100002_remove_required_room_type.sql');
 try{
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  const user=(await q('insert into auth.users values(gen_random_uuid()) returning id'))[0].id;
  const intake=(await q("insert into intakes(intake_code) values('TEST') returning id"))[0].id;
  const student=(await q("insert into students(auth_user_id,student_code,full_name) values($1,'S1','Student') returning id",[user]))[0].id;
  await q('insert into student_intakes values($1,$2,1)',[student,intake]);
  const lecturer=(await q("insert into lecturers(lecturer_code,full_name) values('L1','Teacher') returning id"))[0].id;
  const course=(await q("insert into courses(course_code,name,course_type,duration_minutes) values('C1','Subject','lecture',120) returning id"))[0].id;
  const offering=(await q('insert into course_offerings(course_id,intake_id,lecturer_id) values($1,$2,$3) returning id',[course,intake,lecturer]))[0].id;
  const section=(await q("insert into class_sections(offering_id,required_room_type) values($1,'classroom') returning id",[offering]))[0].id;
  const room=(await q("insert into rooms(name,building,capacity,room_type) values('R1','B',50,'classroom') returning id"))[0].id;
  const session=(await q("insert into class_sessions(section_id,room_id,starts_at) values($1,$2,'2026-11-10 10:00+08') returning id",[section,room]))[0].id;
  if(withTeaching){
   await db.exec(read('migrations/202611100001_teaching_requirements.sql'));
   await q("insert into teaching_plans(section_id,first_week_start,week_count) values($1,'2026-11-09',3)",[section]);
  }
  await db.exec('create view public.unexpected_dependency as select required_room_type from public.class_session_details');
  await assert.rejects(()=>db.exec(patch),/depend/i);passed++;
  await db.exec('rollback');
  check((await q("select column_name from information_schema.columns where table_schema='public' and table_name='class_sections' and column_name='required_room_type'")).length===1,'unexpected dependency rolls back column removal');
  await db.exec('drop view public.unexpected_dependency');
  await db.exec(patch);
  check((await q("select column_name from information_schema.columns where table_schema='public' and table_name='class_sections' and column_name='required_room_type'")).length===0,'column removed');
  check((await q('select id from class_sessions'))[0].id===session,'booking retained');
  check((await q('select room_type from rooms'))[0].room_type==='classroom','actual room classification retained');
  const details=(await q('select * from class_session_details'))[0];
  check(details.id===session && !('required_room_type' in details),'timetable view retained without obsolete field');
  check(new Date(details.ends_at)-new Date(details.starts_at)===7200000,'derived end time retained');
  await q('update class_sections set group_number=1 where id=$1',[section]);
  check((await q('select id from class_sections'))[0].id===section,'section update has no broken trigger-field reference');
  if(withTeaching){
   const occurrences=await q('select * from teaching_occurrence_details');
   check(occurrences.length===3 && occurrences.every(r=>!('required_room_type' in r)),'teaching occurrences/view retained without obsolete field');
   await assert.rejects(()=>q('update courses set duration_minutes=90 where id=$1',[course]),/fixed|locked/i);passed++;
  }
  await q("select set_config('request.jwt.claim.sub',$1,false)",[user]);
  await db.exec('set role authenticated');
  check((await q('select * from class_session_details')).length===1,'authenticated timetable access retained');
  if(withTeaching)check((await q('select * from teaching_occurrence_details')).length===3,'authenticated teaching-demand access retained');
  await db.exec('reset role; set role anon');
  await assert.rejects(()=>q('select * from class_session_details'),/permission denied/);passed++;
  await db.exec('reset role');
  await db.exec(patch);
  check((await q('select * from class_session_details')).length===1,'patch can be rerun');
 }finally{await db.close();}
}
(async()=>{await run(false);await run(true);console.log(`PASS: ${passed} room-type removal SQL checks (PostgreSQL via PGlite; mocked Auth).`);})()
 .catch(e=>{console.error(e);process.exitCode=1;});
