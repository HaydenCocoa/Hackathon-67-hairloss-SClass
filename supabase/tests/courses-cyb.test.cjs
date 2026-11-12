const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
const seed=read('seed_courses_cyb.sql');
const block=seed.match(/do \$seed_courses_cyb\$[\s\S]*?\$seed_courses_cyb\$;/i)[0];
const verify=seed.slice(seed.indexOf(block)+block.length);
const revert=read('revert_courses_cyb.sql');
const revertBlock=revert.match(/do \$revert_courses_cyb\$[\s\S]*?\$revert_courses_cyb\$;/i)[0];
const revertVerify=revert.slice(revert.indexOf(revertBlock)+revertBlock.length);
const expected={
 'APD1F2407CS(CYB)':{modules:15,components:30,sections:60},
 'APD2F2506CS(CYB)':{modules:14,components:28,sections:56},
 'APD3F2609CS(CYB)':{modules:12,components:24,sections:48},
};

async function scenario(label,{removeRoomColumn,preCreateIntakes}){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  await assert.rejects(()=>db.query(block),/Lecturer LEC0\d\d is missing/);passed++;
  check((await q('select count(*)::int n from courses'))[0].n===0,label+': missing lecturer leaves no partial courses');
  check((await q('select count(*)::int n from intakes'))[0].n===0,label+': missing lecturer leaves no intakes');
  await db.exec(read('seed_lecturers.sql'));
  await assert.rejects(()=>db.query(block),/Course CS101-(IN|PYP) \((lecture|lab)\) is missing: run seed_courses.sql first/);passed++;
  check((await q('select count(*)::int n from courses'))[0].n===0,label+': missing CS101-IN/PYP leaves no partial courses');
  // seed_courses.sql writes the legacy room column, so it runs before the removal patch.
  await db.exec(read('seed_courses.sql'));
  const shared=`select id,course_code,course_type,name,duration_minutes from courses
    where course_code in ('CS101-IN','CS101-PYP') order by course_code,course_type`;
  const sharedBefore=JSON.stringify(await q(shared));
  if(removeRoomColumn){
   await db.exec(read('migrations/202611100001_teaching_requirements.sql'));
   await db.exec(read('migrations/202611100002_remove_required_room_type.sql'));
  }
  if(preCreateIntakes){
   await q(`insert into intakes(intake_code,max_group) values
     ('APD1F2407CS(CYB)',2),('APD2F2506CS(CYB)',2),('APD3F2609CS(CYB)',2)`);
  }
  await db.query(block);
  const summary=await q(verify);
  check(summary.length===3,label+': three intakes summarized');
  for(const row of summary){
   const e=expected[row.intake_code];
   check(e && row.max_group===2,label+': '+row.intake_code+' has two groups');
   check(Number(row.modules)===e.modules && Number(row.components)===e.components && Number(row.sections)===e.sections,
     label+': '+row.intake_code+' counts');
   check(row.min_minutes===120 && row.max_minutes===120,label+': '+row.intake_code+' 120-minute components');
  }
  check((await q("select count(*)::int n from courses where name ilike '%internship%' or course_code like 'IT001%'"))[0].n===0,
    label+': internship excluded');
  const cohort=`join intakes i on i.id=o.intake_id and i.intake_code in ('APD1F2407CS(CYB)','APD2F2506CS(CYB)','APD3F2609CS(CYB)')`;
  const codes=await q(`select i.intake_code, c.course_code from course_offerings o join courses c on c.id=o.course_id ${cohort}`);
  const prefix={'APD1F2407CS(CYB)':'CS101-','APD2F2506CS(CYB)':'CS201-','APD3F2609CS(CYB)':'CS301-'};
  check(codes.length===82 && codes.every(r=>r.course_code.startsWith(prefix[r.intake_code])),label+': CS101/CS201/CS301 codes by year');
  const split=await q(`select i.intake_code, c.course_code from course_offerings o join courses c on c.id=o.course_id ${cohort}
    group by i.intake_code, c.course_code having count(distinct o.lecturer_id)<>1 or count(*)<>2`);
  check(split.length===0,label+': each module has two components with one lecturer');
  check((await q('select count(*)::int n from courses'))[0].n===84,label+': 78 new course rows; CS101-IN/PYP reused, not created');
  check(JSON.stringify(await q(shared))===sharedBefore,label+': existing CS101-IN/PYP rows unchanged');
  const reused=await q(`select c.course_code, l.lecturer_code from course_offerings o join courses c on c.id=o.course_id
    join intakes i on i.id=o.intake_id join lecturers l on l.id=o.lecturer_id
    where i.intake_code='APD1F2407CS(CYB)' and c.course_code in ('CS101-IN','CS101-PYP')`);
  check(reused.length===4 && reused.every(r=>({'CS101-IN':'LEC014','CS101-PYP':'LEC015'})[r.course_code]===r.lecturer_code),
    label+': year 1 offerings link the existing CS101-IN/PYP courses');
  const se=await q(`select c.course_code, l.lecturer_code from course_offerings o join courses c on c.id=o.course_id
    join intakes i on i.id=o.intake_id join lecturers l on l.id=o.lecturer_id where i.intake_code='APU1F2611CS(SE)'`);
  check(se.length===6 && se.every(r=>({'CS101-PYP':'LEC001','CS101-IN':'LEC002','CS101-ISE':'LEC003'})[r.course_code]===r.lecturer_code),
    label+': APU1F2611CS(SE) offerings unchanged');
  const types=await q(`select course_code, string_agg(course_type,'/' order by course_type) t from courses
    where course_code in ('CS301-VAPT','CS301-IOT','CS301-INV') group by course_code order by course_code`);
  check(JSON.stringify(types.map(r=>r.t))===JSON.stringify(['lecture/tutorial','lab/tutorial','lab/lecture']),
    label+': year 3 L/T, T/LAB and L/LAB components');
  check((await q(`select count(*)::int n from course_offerings o ${cohort} join lecturers l on l.id=o.lecturer_id where l.lecturer_code in ('LEC001','LEC002','LEC003')`))[0].n===0,
    label+': LEC001-003 left to APU1F2611CS(SE)');
  if(!removeRoomColumn){
   const rooms=await q(`select c.course_type, s.required_room_type r, count(*)::int n from class_sections s
     join course_offerings o on o.id=s.offering_id join courses c on c.id=o.course_id group by 1,2 order by 1,2`);
   check(rooms.every(r=>r.r===(r.course_type==='lab'?'lab':'classroom')),label+': legacy room type filled');
  }
  check((await q('select count(*)::int n from class_sessions'))[0].n===0,label+': no dated bookings invented');
  const ids=async()=>JSON.stringify(await q(`select (select array_agg(id order by id) from courses) c,
    (select array_agg(id order by id) from course_offerings) o, (select array_agg(id order by id) from class_sections) s`));
  const before=await ids();
  await db.exec(seed);
  check(await ids()===before,label+': rerun keeps all IDs and adds no duplicates');
  // Revert: refuses while timetable data uses a cohort section, deleting nothing.
  const cohortSection=(await q(`select s.id from class_sections s join course_offerings o on o.id=s.offering_id
    ${cohort} join courses c on c.id=o.course_id where c.course_code='CS301-INV' and c.course_type='lecture' and s.group_number=1`))[0].id;
  const room=(await q("insert into rooms(name,building,capacity,room_type) values ('REVERT-TEST','B',50,'classroom') returning id"))[0].id;
  await db.exec('begin');
  await q('insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,now())',[cohortSection,room]);
  await assert.rejects(()=>db.query(revertBlock),/1 class session\(s\) use CS\(CYB\) sections/);passed++;
  await db.exec('rollback');
  check(await ids()===before,label+': revert blocked by a class session deletes nothing');
  if(removeRoomColumn){
   await db.exec('begin');
   await q("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,date '2026-11-09',1)",[cohortSection]);
   await assert.rejects(()=>db.query(revertBlock),/1 teaching plan\(s\) use CS\(CYB\) sections/);passed++;
   await db.exec('rollback');
   check(await ids()===before,label+': revert blocked by a teaching plan deletes nothing');
  }
  const intakesBefore=JSON.stringify(await q('select id,intake_code,max_group from intakes order by intake_code'));
  await db.query(revertBlock);
  const after=(await q(revertVerify))[0];
  check(Number(after.cohort_offerings)===0 && Number(after.cohort_courses)===0 && Number(after.reused_courses)===4,
    label+': revert verification query reports a clean revert');
  check((await q('select count(*)::int n from courses'))[0].n===6,label+': only the seed_courses.sql courses remain');
  check(JSON.stringify(await q(shared))===sharedBefore,label+': CS101-IN/PYP rows untouched by revert');
  const seLeft=await q(`select count(distinct o.id)::int o, count(s.id)::int s from course_offerings o
    join intakes i on i.id=o.intake_id left join class_sections s on s.offering_id=o.id where i.intake_code='APU1F2611CS(SE)'`);
  check(seLeft[0].o===6 && seLeft[0].s===6,label+': APU1F2611CS(SE) offerings and sections kept');
  check((await q('select count(*)::int n from course_offerings'))[0].n===6 && (await q('select count(*)::int n from class_sections'))[0].n===6,
    label+': no cohort offerings or sections left');
  check(JSON.stringify(await q('select id,intake_code,max_group from intakes order by intake_code'))===intakesBefore,label+': intakes kept');
  await db.exec(revert);
  check((await q('select count(*)::int n from courses'))[0].n===6,label+': revert can be rerun');
  // A course another intake still uses is kept.
  await db.query(block);
  await q(`insert into course_offerings(course_id,intake_id,lecturer_id)
    select c.id, i.id, l.id from courses c, intakes i, lecturers l
    where c.course_code='CS201-HCI' and c.course_type='lecture' and i.intake_code='APU1F2611CS(SE)' and l.lecturer_code='LEC001'`);
  await db.query(revertBlock);
  const kept=await q("select course_code,course_type from courses where course_code like 'CS_01-%' and course_code not in ('CS101-IN','CS101-PYP','CS101-ISE')");
  check(kept.length===1 && kept[0].course_code==='CS201-HCI' && kept[0].course_type==='lecture',label+': course used by another intake kept');
 } finally {await db.close();}
}

async function main(){
 await scenario('legacy schema',{removeRoomColumn:false,preCreateIntakes:true});
 await scenario('room column removed',{removeRoomColumn:true,preCreateIntakes:false});
 console.log(`PASS: ${passed} CS(CYB) course seed checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
