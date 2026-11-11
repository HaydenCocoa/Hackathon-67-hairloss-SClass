const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
async function main(){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  const seed=read('seed_courses.sql');
  const block=seed.match(/do \$seed_courses\$[\s\S]*?\$seed_courses\$;/i)[0];
  await assert.rejects(()=>db.query(block),/Lecturer LEC001 is missing/);passed++;
  check((await q('select count(*)::int n from intakes'))[0].n===0,'missing lecturer rolls back intake creation');
  check((await q('select count(*)::int n from courses'))[0].n===0,'missing lecturer creates no partial courses');
  await db.exec(read('seed_lecturers.sql'));
  await db.query(block);
  const summary=await q(seed.slice(seed.indexOf(block)+block.length));
  check(summary.length===6,'six course components and sections');
  check(summary.every(r=>r.duration_minutes===120),'every component lasts 120 minutes');
  check(summary.every(r=>r.intake_code==='APU1F2611CS(SE)' && r.group_number===1),'correct intake and group');
  const pairs=[['CS101-PYP','lab','LEC001'],['CS101-IN','lab','LEC002'],['CS101-ISE','tutorial','LEC003']];
  for(const [code,secondType,lecturer]of pairs){
   const rows=summary.filter(r=>r.course_code===code);
   check(rows.length===2 && rows[0].course_type==='lecture' && rows[1].course_type===secondType,'correct teaching types for '+code);
   check(rows.every(r=>r.lecturer_code===lecturer),'same lecturer for both components of '+code);
  }
  check(summary.filter(r=>r.required_room_type==='lab').length===2,'lab room needed for programming and networking labs');
  check(summary.filter(r=>r.required_room_type==='classroom').length===4,'lectures and tutorial use classrooms');
  check((await q('select count(*)::int n from class_sessions'))[0].n===0,'no dated bookings invented');
  const before=await q('select id,course_code,course_type from courses order by course_code,course_type');
  const offeringIds=await q('select id from course_offerings order by id');
  const sectionIds=await q('select id from class_sections order by id');
  await db.exec(seed);
  check(JSON.stringify(await q('select id,course_code,course_type from courses order by course_code,course_type'))===JSON.stringify(before),'rerun preserves course IDs');
  check(JSON.stringify(await q('select id from course_offerings order by id'))===JSON.stringify(offeringIds),'rerun preserves offering IDs');
  check(JSON.stringify(await q('select id from class_sections order by id'))===JSON.stringify(sectionIds),'rerun preserves section IDs');
  const room=(await q("insert into rooms(name,building,capacity,room_type) values ('COURSE-TEST','B',50,'classroom') returning id"))[0].id;
  const section=(await q(`select s.id from class_sections s join course_offerings o on o.id=s.offering_id
    join courses c on c.id=o.course_id where c.course_code='CS101-PYP' and c.course_type='lecture'`))[0].id;
  await q('insert into class_sessions(section_id,room_id,starts_at) values ($1,$2,now())',[section,room]);
  await db.exec(seed);
  check((await q('select count(*)::int n from class_sessions'))[0].n===1,'rerun preserves scheduled sessions');
  check((await q('select extract(epoch from ends_at-starts_at)::int seconds from class_session_details'))[0].seconds===7200,'derived class duration is two hours');
 } finally {await db.close();}
 console.log(`PASS: ${passed} course seed checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
