const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createFixture, uuid } = require('./scheduling-snapshot.fixture.cjs');
let passed = 0;

async function main() {
  const db = await createFixture();
  const q = async (sql, params = []) => (await db.query(sql, params)).rows;
  const check = (value, label) => { assert.ok(value, label); passed++; };
  const reject = async (sql, params, pattern) => { await assert.rejects(() => db.query(sql, params), pattern); passed++; };
  const load = async (week = '2026-11-09', zone = 'Asia/Kuala_Lumpur') =>
    (await q('select load_scheduling_data($1::date,$2) data', [week, zone]))[0].data;
  try {
    let data = await load();
    check(data.schema_version === 1, 'versioned snapshot contract');
    check(data.week_start === '2026-11-09' && data.timezone === 'Asia/Kuala_Lumpur', 'selected local week');
    check(new Date(data.horizon_starts_at).toISOString() === '2026-11-08T16:00:00.000Z', 'local Monday horizon converts to UTC');
    check(new Date(data.horizon_ends_at).toISOString() === '2026-11-15T16:00:00.000Z', 'exclusive local next-Monday boundary');
    check(Boolean(data.database_snapshot) && Boolean(data.captured_at), 'MVCC and capture metadata supplied');
    check(data.requirements.length === 2 && data.requirements.filter(r => r.needs_scheduling).length === 1, 'pending and already-booked demand stay distinguishable');
    check(data.rosters.length === 2, 'rosters for relevant sections');
    const a = data.rosters.find(r => r.section_id === uuid(40));
    const b = data.rosters.find(r => r.section_id === uuid(41));
    check(a.student_ids.length === 2 && a.student_ids.includes(uuid(10)) && a.student_ids.includes(uuid(11)), 'exact group roster excludes other groups');
    check(b.student_ids.length === 2 && b.student_ids.includes(uuid(10)) && b.student_ids.includes(uuid(12)), 'shared student is retained across different intakes');
    check(data.rooms.length === 3 && data.rooms.some(r => !r.is_active), 'room inventory preserves active flags');
    check(data.lecturers.length === 2, 'assigned lecturer identities resolved');
    check(data.class_bookings.length === 2, 'only scheduled overlapping class bookings included');
    check(data.class_bookings.some(c => c.id === uuid(71)), 'booking starting before the horizon is included');
    check(!data.class_bookings.some(c => [uuid(70), uuid(73), uuid(74)].includes(c.id)), 'cancelled and exact non-overlapping boundaries excluded');
    check(data.class_bookings.every(c => new Date(c.ends_at) - new Date(c.starts_at) === c.duration_minutes * 60000), 'class end times derive from course duration');
    check(data.meeting_bookings.length === 0, 'empty meetings are valid for initial dataset');
    check(!JSON.stringify(data).includes('TEST-10') && !JSON.stringify(data).includes('TEACHER-20'), 'personal names and student codes are omitted');
    const counts = (await q('select (select count(*) from class_sessions)::int classes, (select count(*) from teaching_occurrences)::int occurrences'))[0];
    await load();
    check(JSON.stringify(counts) === JSON.stringify((await q('select (select count(*) from class_sessions)::int classes, (select count(*) from teaching_occurrences)::int occurrences'))[0]), 'snapshot call does not create bookings or demand');
    const functionRow = (await q("select provolatile,prosecdef from pg_proc where oid='public.load_scheduling_data(date,text)'::regprocedure"))[0];
    check(functionRow.provolatile === 's' && !functionRow.prosecdef, 'STABLE and security-invoker function uses a single read snapshot');
    await reject('select load_scheduling_data($1::date,$2)', ['2026-11-10', 'Asia/Kuala_Lumpur'], /must be a Monday/i);
    await reject('select load_scheduling_data($1::date,$2)', [null, 'Asia/Kuala_Lumpur'], /must be a Monday/i);
    await reject('select load_scheduling_data($1::date,$2)', ['2026-11-09', 'Invalid/Zone'], /Unknown scheduling timezone/i);
    data = await load('2026-12-07');
    check(data.requirements.length === 0 && data.class_bookings.length === 0 && data.rosters.length === 0, 'week outside plan returns explicit empty demand without fabricated lessons');

    // Optional meeting support: no hosted meeting fixtures are required.
    await q("insert into meeting_sessions(id,lecturer_id,starts_at,ends_at) values ($1,$2,'2026-11-09 09:00+08','2026-11-09 09:30+08')", [uuid(80), uuid(20)]);
    await q('insert into meeting_students values ($1,$2)', [uuid(80), uuid(10)]);
    data = await load();
    check(data.meeting_bookings.length === 1 && data.meeting_bookings[0].room_id === null, 'online meeting retains no room');
    check(data.meeting_bookings[0].student_ids.includes(uuid(10)), 'meeting attendance resolves by student identity');
    await q("update meeting_sessions set status='cancelled' where id=$1", [uuid(80)]);
    check((await load()).meeting_bookings.length === 0, 'cancelled meeting does not occupy time');
    const pending = (await q("select id from teaching_occurrences where section_id=$1 and original_week_start='2026-11-09'", [uuid(40)]))[0].id;
    await q("update teaching_occurrences set target_week_start='2026-12-07' where id=$1", [pending]);
    data = await load('2026-12-07');
    check(data.requirements.length === 1 && data.requirements[0].occurrence_id === pending && data.requirements[0].original_week_start === '2026-11-09', 'make-up demand loads by target week with stable source identity');
    for (const role of ['anon', 'authenticated']) {
      await db.exec('set role ' + role);
      await reject('select load_scheduling_data($1::date,$2)', ['2026-11-09', 'Asia/Kuala_Lumpur'], /permission denied/i);
      await db.exec('reset role');
    }
    await db.exec('set role service_role');
    check((await load()).rooms.length === 3, 'trusted server can read complete snapshot');
    await db.exec('reset role');
    await db.exec(fs.readFileSync(path.join(__dirname, '../migrations/202611100002_remove_required_room_type.sql'), 'utf8'));
    data = await load();
    check(data.requirements.every(row => !('required_room_type' in row)), 'snapshot survives legacy room-requirement removal after prior reads');
    check(data.class_bookings.length === 2 && data.rooms.length === 3, 'bookings and actual room inventory survive view recreation');
  } finally { await db.close(); }
  console.log(`PASS: ${passed} scheduling-snapshot checks (PostgreSQL via PGlite; mocked Supabase Auth).`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
