const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {PGlite}=require('@electric-sql/pglite');
const {bootstrap}=require('./support.cjs');
const read=name=>fs.readFileSync(path.resolve(__dirname,'..',name),'utf8');
let passed=0;
const check=(value,label)=>{assert.ok(value,label);passed++;};
const script=read('split_cyb_students.sql');
const block=script.match(/do \$split_cyb_students\$[\s\S]*?\$split_cyb_students\$;/i)[0];
const verify=script.slice(script.indexOf(block)+block.length);
const [Y1,Y2,Y3]=['APD1F2611CS(CYB)','APD2F2611CS(CYB)','APD3F2611CS(CYB)'];

async function main(){
 const db=new PGlite();
 const q=async(s,p=[]) => (await db.query(s,p)).rows;
 const count=async(s,p=[])=>(await q(s,p))[0].n;
 try {
  await db.exec(bootstrap);
  await db.exec(read('schema.sql'));
  await assert.rejects(()=>db.query(block),/Intake APD2F2611CS\(CYB\) is missing/);passed++;

  // The hosted state on 13 November 2026: the same 80 sample students in all three
  // renamed CYB intakes, Year 1-only extras (one with a login), and the SE intake.
  await q(`insert into intakes(intake_code,max_group) values ($1,2),($2,2),($3,2),('APU1F2611CS(SE)',1)`,[Y1,Y2,Y3]);
  await q(`insert into students(student_code,full_name,age)
    select 'TP'||lpad((640+g)::text,6,'0'), 'Shared Student '||g, 18+(g%8) from generate_series(1,80) g`);
  await q(`insert into student_intakes(student_id,intake_id,group_number)
    select s.id, i.id, ((right(s.student_code,3)::int-641)%2)+1 from students s cross join intakes i
    where i.intake_code like '%CS(CYB)'`);
  await q(`insert into students(student_code,full_name,age)
    select 'TP'||lpad((560+g)::text,6,'0'), 'SE Student '||g, 20 from generate_series(1,40) g`);
  await q(`insert into student_intakes(student_id,intake_id,group_number)
    select s.id, i.id, 1 from students s, intakes i where s.full_name like 'SE Student %' and i.intake_code='APU1F2611CS(SE)'`);
  const account='00000000-0000-0000-0000-00000000b001';
  await q('insert into auth.users(id) values ($1)',[account]);
  await q("insert into students(student_code,full_name,auth_user_id) values ('X-LINKED','Year One Login',$1)",[account]);
  await q("insert into student_intakes(student_id,intake_id,group_number) select s.id,i.id,2 from students s, intakes i where s.student_code='X-LINKED' and i.intake_code=$1",[Y1]);
  // An extra member only in Year 3 (to check it is removed from the intake, not deleted).
  await q("insert into students(student_code,full_name) values ('X-ONLY3','Only Year Three')");
  await q("insert into student_intakes(student_id,intake_id,group_number) select s.id,i.id,1 from students s, intakes i where s.student_code='X-ONLY3' and i.intake_code=$1",[Y3]);
  const y1Before=JSON.stringify(await q(`select m.student_id,m.group_number from student_intakes m join intakes i on i.id=m.intake_id where i.intake_code=$1 order by 1`,[Y1]));
  const seBefore=JSON.stringify(await q(`select m.student_id from student_intakes m join intakes i on i.id=m.intake_id where i.intake_code='APU1F2611CS(SE)' order by 1`));

  // A new code already used by someone else stops the script.
  await q("insert into students(student_code,full_name) values ('TP001081','Somebody Else')");
  await assert.rejects(()=>db.query(block),/Student code TP001081 already belongs to another student/);passed++;
  check(await count("select count(*)::int n from students where student_code between 'TP001001' and 'TP001080'")===0,'stopped script adds nothing');
  await q("delete from students where student_code='TP001081'");

  await db.query(block);
  const rows=await q(verify);
  const by=Object.fromEntries(rows.map(r=>[r.intake_code,r]));
  for(const code of [Y2,Y3]){
   const r=by[code];
   check(Number(r.students)===80 && Number(r.group_1)===40 && Number(r.group_2)===40,code+': 80 students, 40 / 40');
   check(Number(r.shared_with_other_cyb)===0 && Number(r.distinct_names)===80,code+': own students with distinct names');
  }
  check(Number(by[Y1].students)===81 && Number(by[Y1].shared_with_other_cyb)===0,'Year 1 keeps its 81 students, now shared with no other year');
  check(JSON.stringify(await q(`select m.student_id,m.group_number from student_intakes m join intakes i on i.id=m.intake_id where i.intake_code=$1 order by 1`,[Y1]))===y1Before,
    'Year 1 memberships unchanged');
  check(JSON.stringify(await q(`select m.student_id from student_intakes m join intakes i on i.id=m.intake_id where i.intake_code='APU1F2611CS(SE)' order by 1`))===seBefore,
    'SE memberships unchanged');
  const codes=await q(`select i.intake_code, min(s.student_code) lo, max(s.student_code) hi, min(s.age) a1, max(s.age) a2,
    string_agg(distinct split_part(s.full_name,' ',2),'/' order by split_part(s.full_name,' ',2)) sur
    from student_intakes m join intakes i on i.id=m.intake_id join students s on s.id=m.student_id
    where i.intake_code in ($1,$2) group by 1 order by 1`,[Y2,Y3]);
  check(JSON.stringify(codes.map(r=>[r.lo,r.hi,r.a1,r.a2,r.sur]))===JSON.stringify([['TP001001','TP001080',19,22,'Adams/Bell'],['TP001081','TP001160',20,23,'Cook/Edwards']]),
    'codes, ages and surnames per intake');
  check(await count(`select count(*)::int n from students s where s.student_code between 'TP001001' and 'TP001160'
    and (select count(*) from student_intakes m where m.student_id=s.id)<>1`)===0,'every new student is in exactly one intake');
  check(await count(`select count(*)::int n from students s where s.full_name like 'Shared Student %'
    and (select count(*) from student_intakes m where m.student_id=s.id)<>1`)===0,'the old shared 80 are now only in Year 1');
  check(await count("select count(*)::int n from students where student_code='X-ONLY3'")===1 &&
    await count("select count(*)::int n from student_intakes m join students s on s.id=m.student_id where s.student_code='X-ONLY3'")===0,
    'a member only in Year 3 is removed from the intake but not deleted');
  check(await count("select count(*)::int n from students where student_code='X-LINKED' and auth_user_id is not null")===1,'Year 1 login link kept');
  check(await count('select count(*)::int n from (select full_name from students group by full_name having count(*)>1) d')===0,'no duplicate names');
  check(await count('select count(*)::int n from students')===80+40+2+160,'80 shared + 40 SE + 2 extras + 160 new');

  // Rerun changes nothing.
  const snap=async()=>JSON.stringify(await q('select s.id,s.student_code,s.full_name,s.age,m.intake_id,m.group_number from students s left join student_intakes m on m.student_id=s.id order by 2,5'));
  const before=await snap();
  await db.exec(script);
  check(await snap()===before,'rerun changes nothing');

  // A new student wrongly added to another intake is put back to one intake by a rerun.
  await q(`insert into student_intakes(student_id,intake_id,group_number) select s.id,i.id,1 from students s, intakes i
    where s.student_code='TP001001' and i.intake_code=$1`,[Y1]);
  await db.query(block);
  check(await snap()===before,'rerun restores single-intake membership');
 } finally {await db.close();}
 console.log(`PASS: ${passed} CYB student split checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
