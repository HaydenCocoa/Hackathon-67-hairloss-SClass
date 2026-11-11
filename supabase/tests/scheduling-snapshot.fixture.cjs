// Synthetic local data only. Also exports the real RPC result for HTTP tests.
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require('@electric-sql/pglite');
const { bootstrap } = require('./support.cjs');
const uuid = n => '00000000-0000-0000-0000-' + n.toString(16).padStart(12, '0');

async function createFixture({ removeRoomRequirement = false } = {}) {
  const db = new PGlite();
  try {
    await db.exec(bootstrap);
    await db.exec(fs.readFileSync(path.join(__dirname, '../schema.sql'), 'utf8'));
    for (const file of ['202611100001_teaching_requirements.sql']) {
      await db.exec(fs.readFileSync(path.join(__dirname, '../migrations', file), 'utf8'));
    }
    await db.query("insert into intakes(id,intake_code,max_group) values ($1,'A',2),($2,'B',1)", [uuid(1), uuid(2)]);
    for (const n of [10, 11, 12, 13]) {
      await db.query('insert into students(id,student_code,full_name) values ($1,$2,$2)', [uuid(n), 'TEST-' + n]);
    }
    await db.query('insert into student_intakes values ($1,$2,1),($1,$3,1),($4,$2,1),($5,$3,1),($6,$2,2)',
      [uuid(10), uuid(1), uuid(2), uuid(11), uuid(12), uuid(13)]);
    for (const n of [20, 21]) {
      await db.query('insert into lecturers(id,lecturer_code,full_name) values ($1,$2,$2)', [uuid(n), 'TEACHER-' + n]);
    }
    await db.query("insert into courses(id,course_code,name,course_type,duration_minutes) values ($1,'CS1','Subject','lecture',90),($2,'CS1','Subject','lab',120)", [uuid(30), uuid(31)]);
    await db.query('insert into course_offerings(id,course_id,intake_id,lecturer_id) values ($1,$2,$3,$4),($5,$6,$7,$8)',
      [uuid(50), uuid(30), uuid(1), uuid(20), uuid(51), uuid(31), uuid(2), uuid(21)]);
    await db.query("insert into class_sections(id,offering_id,required_room_type) values ($1,$2,'classroom'),($3,$4,'lab')",
      [uuid(40), uuid(50), uuid(41), uuid(51)]);
    await db.query("insert into rooms(id,name,building,capacity,room_type,is_active) values ($1,'CLASS','B',40,'classroom',true),($2,'LAB','S',50,'lab',true),($3,'CLOSED','B',1,'classroom',false)",
      [uuid(60), uuid(61), uuid(62)]);
    await db.query("insert into teaching_plans(section_id,first_week_start,week_count) values ($1,'2026-11-09',2),($2,'2026-11-09',2)", [uuid(40), uuid(41)]);
    // One ends exactly at the boundary, one overlaps it, one is cancelled,
    // and one starts exactly at the next boundary. No impossible dataset needed.
    for (const [n, time, status] of [
      [70, '2026-11-08 22:30+08', 'scheduled'],
      [71, '2026-11-08 23:30+08', 'scheduled'],
      [73, '2026-11-09 12:00+08', 'cancelled'],
      [74, '2026-11-16 00:00+08', 'scheduled'],
    ]) {
      await db.query('insert into class_sessions(id,section_id,room_id,starts_at,status) values ($1,$2,$3,$4,$5)',
        [uuid(n), uuid(40), uuid(60), time, status]);
    }
    const occurrence = (await db.query("select id from teaching_occurrences where section_id=$1 and original_week_start='2026-11-09'", [uuid(41)])).rows[0].id;
    await db.query("insert into class_sessions(id,section_id,occurrence_id,room_id,starts_at) values ($1,$2,$3,$4,'2026-11-09 14:43+08')",
      [uuid(72), uuid(41), occurrence, uuid(61)]);
    if (removeRoomRequirement) {
      await db.exec(fs.readFileSync(path.join(__dirname, '../migrations/202611100002_remove_required_room_type.sql'), 'utf8'));
    }
    await db.exec(fs.readFileSync(path.join(__dirname, '../migrations/202611100003_scheduling_snapshot.sql'), 'utf8'));
    return db;
  } catch (error) {
    await db.close();
    throw error;
  }
}

module.exports = { createFixture, uuid };
if (require.main === module) {
  (async () => {
    const db = await createFixture({ removeRoomRequirement: process.argv.includes('--without-room-requirement') });
    try {
      const payload = (await db.query('select load_scheduling_data($1::date,$2) data', ['2026-11-09', 'Asia/Kuala_Lumpur'])).rows[0].data;
      process.stdout.write(JSON.stringify(payload));
    } finally { await db.close(); }
  })().catch(error => { console.error(error); process.exitCode = 1; });
}
