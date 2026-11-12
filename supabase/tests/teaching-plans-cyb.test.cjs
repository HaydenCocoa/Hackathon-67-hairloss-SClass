const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
const doBlock=(sql,tag)=>sql.match(new RegExp(`do \\$${tag}\\$[\\s\\S]*?\\$${tag}\\$;`,'i'))[0];
const plans=read('seed_teaching_plans_cyb.sql');
const plansBlock=doBlock(plans,'seed_teaching_plans_cyb');
const plansVerify=plans.slice(plans.indexOf(plansBlock)+plansBlock.length);
const remove=read('remove_teaching_plans_cyb.sql');
const removeBlock=doBlock(remove,'remove_teaching_plans_cyb');
const removeVerify=remove.slice(remove.indexOf(removeBlock)+removeBlock.length);
const expected={'APD1F2407CS(CYB)':[60,840],'APD2F2506CS(CYB)':[56,784],'APD3F2609CS(CYB)':[48,672]};
const cohortPlans=`select count(*)::int n from teaching_plans p join class_sections s on s.id=p.section_id
  join course_offerings o on o.id=s.offering_id join intakes i on i.id=o.intake_id
  where i.intake_code in ('APD1F2407CS(CYB)','APD2F2506CS(CYB)','APD3F2609CS(CYB)')`;

async function main(){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const count=async s=>(await q(s))[0].n;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  await assert.rejects(()=>db.query(plansBlock),/teaching_plans is missing/);passed++;
  await db.exec(read('seed_lecturers.sql'));
  await db.exec(read('seed_courses.sql'));
  // The hosted run order: teaching plans, room-column removal, rescheduled status, save audit.
  await db.exec(read('migrations/202611100001_teaching_requirements.sql'));
  await db.exec(read('migrations/202611100002_remove_required_room_type.sql'));
  await db.exec(read('migrations/202611120001_class_session_rescheduled_status.sql'));
  await db.exec(read('migrations/202611120002_save_audit.sql'));
  await q(`insert into intakes(intake_code,max_group) values
    ('APD1F2407CS(CYB)',2),('APD2F2506CS(CYB)',2),('APD3F2609CS(CYB)',2)`);
  await assert.rejects(()=>db.query(plansBlock),/Expected 82 CS\(CYB\) offerings, found 0/);passed++;
  await db.exec(read('seed_courses_cyb.sql'));

  // Add plans.
  await db.query(plansBlock);
  const summary=await q(plansVerify);
  check(summary.length===3,'three intakes have plans');
  for(const r of summary){
   const [p,l]=expected[r.intake_code];
   check(Number(r.plans)===p && Number(r.lessons)===l && Number(r.required_lessons)===l,r.intake_code+' plans and lessons');
  }
  const weeks=await q(`select min(first_week_start)::text a, max(first_week_start)::text b, min(week_count) w1, max(week_count) w2,
    min(occurrences_per_week) o1, max(occurrences_per_week) o2 from teaching_plans`);
  check(weeks[0].a==='2026-11-16' && weeks[0].b==='2026-11-16','every plan starts Monday 16 Nov 2026');
  check(weeks[0].w1===14 && weeks[0].w2===14 && weeks[0].o1===1 && weeks[0].o2===1,'14 weeks, 1 lesson a week');
  check((await q("select max(original_week_start)::text d from teaching_occurrences"))[0].d==='2027-02-15','last lesson week is 15 Feb 2027');
  check(await count('select count(*)::int n from teaching_plans')===164,'164 plans in total; APU1F2611CS(SE) has none');
  check(await count('select count(*)::int n from teaching_occurrences')===2296,'2,296 lessons created');
  check(await count("select count(*)::int n from teaching_occurrence_details where target_week_start=date '2026-11-16' and needs_scheduling")===164,
    'first week has 164 lessons waiting to be scheduled');
  check(await count('select count(*)::int n from class_sessions')===0,'no class times or rooms assigned');
  const ids=async()=>JSON.stringify(await q('select (select array_agg(id order by id) from teaching_plans) p, (select array_agg(id order by id) from teaching_occurrences) o'));
  const before=await ids();
  await db.exec(plans);
  check(await ids()===before,'rerunning the plan script adds nothing');

  // Removal is refused while a class session is linked to a lesson.
  const room=(await q("insert into rooms(name,building,capacity,room_type) values ('PLAN-TEST','B',100,'classroom') returning id"))[0].id;
  const lesson=(await q(`select t.id, t.section_id from teaching_occurrences t order by t.original_week_start, t.id limit 1`))[0];
  await db.exec('begin');
  await q("insert into class_sessions(section_id,room_id,starts_at,occurrence_id) values ($1,$2,timestamptz '2026-11-16 09:00+08',$3)",
    [lesson.section_id,room,lesson.id]);
  await assert.rejects(()=>db.query(removeBlock),/1 class session\(s\) are linked to CS\(CYB\) lessons/);passed++;
  await db.exec('rollback');
  check(await ids()===before,'blocked removal deletes nothing');

  // Remove.
  const sePlan=(await q(`insert into teaching_plans(section_id,first_week_start,week_count)
    select s.id, date '2026-11-16', 2 from class_sections s join course_offerings o on o.id=s.offering_id
    join intakes i on i.id=o.intake_id join courses c on c.id=o.course_id
    where i.intake_code='APU1F2611CS(SE)' and c.course_code='CS101-ISE' and c.course_type='lecture' returning id`))[0].id;
  await db.query(removeBlock);
  const after=(await q(removeVerify))[0];
  check(Number(after.cohort_plans)===0 && Number(after.cohort_lessons)===0 && after.occurrence_delete_check==='O',
    'removal verification: no cohort plans or lessons, protection back on');
  check(await count(`select count(*)::int n from teaching_plans where id='${sePlan}'`)===1 &&
    await count(`select count(*)::int n from teaching_occurrences where plan_id='${sePlan}'`)===2,'other intakes\' plans kept');
  check(await count(cohortPlans)===0,'no CS(CYB) plans left');
  check(await count('select count(*)::int n from class_sections')===170 && await count('select count(*)::int n from courses')===84,
    'courses and sections kept');
  await assert.rejects(()=>q(`delete from teaching_occurrences where plan_id='${sePlan}'`),/Cancel a teaching occurrence instead of deleting/);passed++;
  await db.exec(remove);
  check(await count(cohortPlans)===0,'removal can be rerun');

  // A different plan on a cohort section makes the plan script stop.
  const section=(await q(`select s.id from class_sections s join course_offerings o on o.id=s.offering_id
    join courses c on c.id=o.course_id where c.course_code='CS301-INV' and c.course_type='lecture' and s.group_number=1`))[0].id;
  await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,date '2026-11-16',10)",[section]);
  await assert.rejects(()=>db.query(plansBlock),/1 CS\(CYB\) section\(s\) already have a plan other than 14 weeks from 2026-11-16/);passed++;
  check(await count(cohortPlans)===1,'stopped plan script adds nothing');
  await db.query(removeBlock);

  // Plans again, then the full undo order: remove plans, then revert courses.
  await db.query(plansBlock);
  check(await count(cohortPlans)===164,'plans can be added again after removal');
  await assert.rejects(()=>db.exec(read('revert_courses_cyb.sql')),/teaching plan\(s\) use CS\(CYB\) sections/);passed++;
  await db.exec(remove);
  await db.exec(read('revert_courses_cyb.sql'));
  check(await count('select count(*)::int n from courses')===6,'remove plans then revert courses leaves only seed_courses.sql');
 } finally {await db.close();}
 console.log(`PASS: ${passed} CS(CYB) teaching-plan checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
