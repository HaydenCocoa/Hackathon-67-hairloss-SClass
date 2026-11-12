-- SMART CAMPUS -- 14-week teaching plans for a small CS(CYB) sample
-- Gives teaching plans to 3 Semester 1 modules of each CS(CYB) intake
-- (sample data kept small and schedulable, user decision 13 November 2026):
--   APD3F2609CS(CYB) year 3: CS301-INV, CS301-ALG, CS301-VAPT
--   APD2F2506CS(CYB) year 2: CS201-ENTINV, CS201-OODJ, CS201-SDM
--   APD1F2407CS(CYB) year 1: CS101-IDB, CS101-IN, CS101-PYP
-- Each module has 2 teaching parts and each intake 2 groups, so 9 modules give
-- 36 plans. Every plan:
--   * starts Monday 16 Nov 2026 (change first_monday below; it must be a Monday);
--   * runs 14 consecutive weeks (breaks are not skipped);
--   * has 1 lesson per week.
-- The database creates the 504 required lessons (teaching occurrences)
-- automatically; no times, rooms or class_sessions are assigned. Use Generate
-- Preview on /admin/schedule to place them. The other 32 CS(CYB) modules keep
-- their courses and sections but get no plan.
--
-- seed_students.sql puts the same 80 students in all three intakes, so each of
-- them has 18 two-hour classes a week (36 h) in the 47.5 h teaching week. The
-- nine modules have nine different lecturers.
--
-- Needs: schema.sql, migrations/202611100001_teaching_requirements.sql,
-- seed_courses.sql and seed_courses_cyb.sql. Stops if other CS(CYB) modules
-- still have plans (for example from the earlier all-modules version): run
-- remove_teaching_plans_cyb.sql first. Run the whole file as postgres in
-- Supabase Dashboard > SQL Editor. Atomic; rerunning adds nothing.
-- Undo with remove_teaching_plans_cyb.sql.

do $seed_teaching_plans_cyb$
declare
  first_monday constant date := date '2026-11-16';
  week_total constant integer := 14;
  lessons_per_week constant integer := 1;
  cohort_intakes constant text[] := array[
    'APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)'];
  -- The 9 planned modules (3 per intake; codes are unique to their year).
  planned_codes constant text[] := array[
    'CS301-INV', 'CS301-ALG', 'CS301-VAPT',
    'CS201-ENTINV', 'CS201-OODJ', 'CS201-SDM',
    'CS101-IDB', 'CS101-IN', 'CS101-PYP'];
  offering_total integer;
  section_ids uuid[];
  added integer;
  mismatched integer;
  other_plans integer;
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
    and c.course_code = any(planned_codes);

  if offering_total <> 18 then
    raise exception 'Expected 18 offerings for the 9 planned CS(CYB) modules, found %: run seed_courses_cyb.sql first',
      offering_total;
  end if;

  -- Plans on any other CS(CYB) module would bring back the unschedulable load.
  select count(*) into other_plans
  from public.teaching_plans p
  join public.class_sections s on s.id = p.section_id
  join public.course_offerings o on o.id = s.offering_id
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code ~ '^CS[123]01-'
    and not (c.course_code = any(planned_codes));

  if other_plans > 0 then
    raise exception '% teaching plan(s) exist on other CS(CYB) modules: run remove_teaching_plans_cyb.sql first',
      other_plans;
  end if;

  select array_agg(s.id order by s.id) into section_ids
  from public.class_sections s
  join public.course_offerings o on o.id = s.offering_id
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code = any(planned_codes);

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
-- 3 modules, 12 plans and 168 lessons per intake (36 plans, 504 lessons in
-- total); first week 2026-11-16, last week 2027-02-15.
select
  i.intake_code,
  count(distinct c.course_code) as modules,
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
