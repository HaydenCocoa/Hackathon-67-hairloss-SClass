-- SMART CAMPUS -- 14-week teaching plans for the CS(CYB) cohort
-- Gives every class section created by seed_courses_cyb.sql one teaching plan:
-- intakes APD1F2407CS(CYB), APD2F2506CS(CYB) and APD3F2609CS(CYB), all 41 modules
-- (both semesters of each year), every group.
--   * start: Monday 16 Nov 2026 (change first_monday below; it must be a Monday);
--   * 14 consecutive weeks (breaks are not skipped);
--   * 1 lesson per week for each lecture, tutorial or lab of each group.
-- With 2 groups per intake that is 164 plans and 2,296 required lessons
-- (teaching occurrences). The database creates the occurrences automatically;
-- no times, rooms or class_sessions are assigned. Use Generate Preview on
-- /admin/schedule to place them.
--
-- Warning: seed_students.sql puts the same 80 students in all three intakes,
-- so these plans give each of them 82 two-hour classes a week (164 h) in a
-- 47.5 h teaching week. The scheduler cannot place them all; it will report
-- that the week cannot be scheduled. This was accepted (12 November 2026).
--
-- Needs: schema.sql, migrations/202611100001_teaching_requirements.sql,
-- seed_courses.sql and seed_courses_cyb.sql. Run the whole file as postgres in
-- Supabase Dashboard > SQL Editor. Atomic; rerunning adds nothing.
-- Undo with remove_teaching_plans_cyb.sql.

do $seed_teaching_plans_cyb$
declare
  first_monday constant date := date '2026-11-16';
  week_total constant integer := 14;
  lessons_per_week constant integer := 1;
  cohort_intakes constant text[] := array[
    'APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)'];
  -- The 41 module codes linked by seed_courses_cyb.sql.
  linked_codes constant text[] := array[
    'CS301-INV', 'CS301-ALG', 'CS301-VAPT', 'CS301-CIS', 'CS301-PM', 'CS301-DLID',
    'CS301-VB', 'CS301-IOT', 'CS301-PRJ', 'CS301-ADS', 'CS301-ASS', 'CS301-ACS',
    'CS201-ENTINV', 'CS201-OODJ', 'CS201-SDM', 'CS201-SNA', 'CS201-CTF', 'CS201-SRE',
    'CS201-FIS', 'CS201-HCI', 'CS201-WAPP', 'CS201-DSTR', 'CS201-RMCT', 'CS201-COMT',
    'CS201-ISC', 'CS201-WPS',
    'CS101-IDB', 'CS101-IN', 'CS101-PYP', 'CS101-DGTIN', 'CS101-SSCC', 'CS101-PEP',
    'CS101-BM(A)', 'CS101-CC2', 'CS101-MCFC', 'CS101-ENTDNA', 'CS101-SAAD',
    'CS101-IOOP', 'CS101-ISFT', 'CS101-ICS', 'CS101-KIAR'];
  offering_total integer;
  section_ids uuid[];
  added integer;
  mismatched integer;
begin
  if to_regclass('public.teaching_plans') is null then
    raise exception 'teaching_plans is missing: apply migrations/202611100001_teaching_requirements.sql first';
  end if;
  if extract(isodow from first_monday) <> 1 then
    raise exception 'first_monday (%) must be a Monday', first_monday;
  end if;

  perform pg_advisory_xact_lock(7280001008::bigint);

  select count(*) into offering_total
  from public.course_offerings o
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code = any(linked_codes);

  if offering_total <> 82 then
    raise exception 'Expected 82 CS(CYB) offerings, found %: run seed_courses_cyb.sql first', offering_total;
  end if;

  select array_agg(s.id order by s.id) into section_ids
  from public.class_sections s
  join public.course_offerings o on o.id = s.offering_id
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code = any(linked_codes);

  -- One plan per section, only for sections without any plan yet (the
  -- database's overlap check runs before ON CONFLICT, so existing plans must be
  -- skipped explicitly). Sections whose existing plan differs are reported below.
  insert into public.teaching_plans(section_id, first_week_start, week_count, occurrences_per_week)
  select sid, first_monday, week_total, lessons_per_week
  from unnest(section_ids) as sid
  where not exists (select 1 from public.teaching_plans p where p.section_id = sid);
  get diagnostics added = row_count;

  select count(*) into mismatched
  from unnest(section_ids) as sid
  where not exists (
    select 1 from public.teaching_plans p
    where p.section_id = sid
      and p.first_week_start = first_monday
      and p.week_count = week_total
      and p.occurrences_per_week = lessons_per_week);

  if mismatched > 0 then
    raise exception '% CS(CYB) section(s) already have a plan other than 14 weeks from %: run remove_teaching_plans_cyb.sql first',
      mismatched, first_monday;
  end if;

  raise notice 'Added % teaching plans (% sections in total) from % for % weeks.',
    added, cardinality(section_ids), first_monday, week_total;
end;
$seed_teaching_plans_cyb$;

-- Independent verification: one row per intake. Expected with 2 groups each:
-- APD1F2407CS(CYB) 60 plans / 840 lessons, APD2F2506CS(CYB) 56 / 784,
-- APD3F2609CS(CYB) 48 / 672; first week 2026-11-16, last week 2027-02-15.
select
  i.intake_code,
  count(distinct p.id) as plans,
  count(t.id) as lessons,
  min(t.original_week_start) as first_week,
  max(t.original_week_start) as last_week,
  count(t.id) filter (where t.requirement_status = 'required') as required_lessons
from public.teaching_plans p
join public.class_sections s on s.id = p.section_id
join public.course_offerings o on o.id = s.offering_id
join public.intakes i on i.id = o.intake_id
join public.courses c on c.id = o.course_id
left join public.teaching_occurrences t on t.plan_id = p.id
where i.intake_code in ('APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)')
  and c.course_code ~ '^CS[123]01-'
group by i.intake_code
order by i.intake_code;
