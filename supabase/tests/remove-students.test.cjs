const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
const script=read('remove_students_except_cyb_se.sql');
const block=script.match(/do \$remove_students_except_cyb_se\$[\s\S]*?\$remove_students_except_cyb_se\$;/i)[0];
const verify=script.slice(script.indexOf(block)+block.length);
const kept=['APD1F2407CS(CYB)','APD2F2506CS(CYB)','APD3F2609CS(CYB)','APU1F2611CS(SE)'];

async function main(){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const count=async s=>(await q(s))[0].n;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  await db.exec(read('seed_lecturers.sql'));
  await assert.rejects(()=>db.query(block),/Only 0 of the 4 kept intakes exist/);passed++;
  await db.exec(read('seed_students.sql'));
  check(await count('select count(*)::int n from students')===1000,'sample seed has 1,000 students');
  check(await count('select count(*)::int n from student_intakes')===1480,'sample seed has 1,480 memberships');

  // Extra cases: a mixed student, a student with no membership, meeting attendance, a login link.
  const intake=async code=>(await q('select id from intakes where intake_code=$1',[code]))[0].id;
  const student=async code=>(await q('select id from students where student_code=$1',[code]))[0].id;
  const cyb1=(await q(`select s.student_code c from students s join student_intakes m on m.student_id=s.id
    join intakes i on i.id=m.intake_id where i.intake_code='APD1F2407CS(CYB)' order by 1 limit 1`))[0].c;
  const other=(await q(`select s.student_code c from students s join student_intakes m on m.student_id=s.id
    join intakes i on i.id=m.intake_id where i.intake_code='APD1F2611CS' order by 1 limit 1`))[0].c;
  const se=(await q(`select s.student_code c from students s join student_intakes m on m.student_id=s.id
    join intakes i on i.id=m.intake_id where i.intake_code='APU1F2611CS(SE)' order by 1 limit 1`))[0].c;
  await q('insert into student_intakes(student_id,intake_id,group_number) values ($1,$2,1)',[await student(cyb1),await intake('APD1F2611CS(DF)')]);
  await q("insert into students(student_code,full_name) values ('TP900001','No Intake Student')");
  const lecturer=(await q("select id from lecturers where lecturer_code='LEC001'"))[0].id;
  const meeting=(await q("insert into meeting_sessions(lecturer_id,starts_at,ends_at) values ($1,now(),now()+interval '1 hour') returning id",[lecturer]))[0].id;
  for(const code of [cyb1,other,se]) await q('insert into meeting_students(meeting_id,student_id) values ($1,$2)',[meeting,await student(code)]);
  const keptMemberships=JSON.stringify(await q(`select m.student_id,m.intake_id,m.group_number from student_intakes m
    join intakes i on i.id=m.intake_id where i.intake_code=any($1) order by 1,2`,[kept]));

  // A linked login on a student to be removed stops the script.
  const account='00000000-0000-0000-0000-00000000a001';
  await q('insert into auth.users(id) values ($1)',[account]);
  await q('update students set auth_user_id=$1 where student_code=$2',[account,other]);
  await assert.rejects(()=>db.query(block),/1 student\(s\) to be removed are linked to login accounts/);passed++;
  check(await count('select count(*)::int n from students')===1001,'stopped by a linked login, nothing deleted');
  await assert.rejects(()=>db.query(block.replace('remove_linked_accounts constant boolean := false','remove_linked_accounts constant boolean := true').replace(/'APU1F2611CS\(SE\)'\];/,"'APU1F2611CS(SEX)'];")),
    /Only 3 of the 4 kept intakes exist/);passed++;
  check(await count('select count(*)::int n from students')===1001,'a mistyped kept intake deletes nothing');

  // Run with the login link allowed (the default script refuses it, as checked above).
  await db.query(block.replace('remove_linked_accounts constant boolean := false','remove_linked_accounts constant boolean := true'));
  const summary=await q(verify);
  check(JSON.stringify(summary.map(r=>[r.intake_code,Number(r.students),Number(r.group_1),Number(r.group_2)]))===JSON.stringify([
    ['APD1F2407CS(CYB)',80,40,40],['APD2F2506CS(CYB)',80,40,40],['APD3F2609CS(CYB)',80,40,40],['APU1F2611CS(SE)',40,40,0]]),
    'only the four kept intakes have students, with unchanged group sizes');
  check(Number(summary[0].all_students)===121,'120 sample students plus the student with no intake remain');
  check(await count('select count(*)::int n from student_intakes')===280,'280 memberships remain');
  check(JSON.stringify(await q(`select m.student_id,m.intake_id,m.group_number from student_intakes m
    join intakes i on i.id=m.intake_id where i.intake_code=any($1) order by 1,2`,[kept]))===keptMemberships,'kept memberships unchanged');
  check(await count(`select count(*)::int n from students where student_code='${cyb1}'`)===1 &&
    await count(`select count(*)::int n from student_intakes m join students s on s.id=m.student_id where s.student_code='${cyb1}'`)===3,
    'student also in a kept intake is kept, without the other membership');
  check(await count("select count(*)::int n from students where student_code='TP900001'")===1,'student with no membership untouched');
  check(await count(`select count(*)::int n from students where student_code='${other}'`)===0,'student only in other intakes removed');
  check(await count('select count(*)::int n from meeting_students')===2,'meeting attendance kept for kept students only');
  check(await count('select count(*)::int n from meeting_sessions')===1,'meetings kept');
  check(await count(`select count(*)::int n from auth.users where id='${account}'`)===1,'login account itself kept');
  check(await count('select count(*)::int n from intakes')===18,'all 18 intakes kept');
  const before=await count('select count(*)::int n from students');
  await db.exec(script);
  check(await count('select count(*)::int n from students')===before,'rerun deletes nothing');
  await db.exec(read('seed_students.sql'));
  check(await count('select count(*)::int n from student_intakes')===1480 && await count('select count(*)::int n from students')===1001,'rerunning seed_students.sql restores 1,000 sample students and 1,480 memberships');
 } finally {await db.close();}
 console.log(`PASS: ${passed} student removal checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
