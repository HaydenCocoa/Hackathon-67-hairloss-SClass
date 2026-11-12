-- SMART CAMPUS -- remove the CS(CYB) teaching plans
-- Undoes seed_teaching_plans_cyb.sql: deletes its 36 teaching plans and 504
-- teaching occurrences (required lessons) on the 9 planned modules
-- (CS301-INV/ALG/VAPT, CS201-ENTINV/OODJ/SDM, CS101-IDB/IN/PYP).
-- It checks all 41 CS(CYB) modules of APD1F2407CS(CYB), APD2F2506CS(CYB) and
-- APD3F2609CS(CYB), every group, so it also removes the 164 plans of the
-- earlier all-modules version if that was run.
-- Courses, offerings, sections, intakes and other intakes' plans are kept,
-- including APU1F2611CS(SE)'s own CS101-IN/PYP sections.
--
-- Occurrences are normally protected from deletion ("cancel instead of
-- deleting"). This script switches off only that check
-- (trigger validate_teaching_occurrence) for its own transaction and switches
-- it back on before finishing; other sessions never see it off.
--
-- Stops, deleting nothing, if a class session is linked to one of these
-- lessons (a saved timetable keeps its lesson history).
-- Run the whole file as postgres in Supabase Dashboard > SQL Editor.
-- Atomic; rerunning deletes nothing. Run it before revert_courses_cyb.sql.

do $remove_teaching_plans_cyb$
declare
  cohort_intakes constant text[] := array[
    'APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)'];
  -- All 41 CS(CYB) module codes, a superset of the 9 planned ones.
  linked_codes constant text[] := array[
    'CS301-INV', 'CS301-ALG', 'CS301-VAPT', 'CS301-CIS', 'CS301-PM', 'CS301-DLID',
    'CS301-VB', 'CS301-IOT', 'CS301-PRJ', 'CS301-ADS', 'CS301-ASS', 'CS301-ACS',
    'CS201-ENTINV', 'CS201-OODJ', 'CS201-SDM', 'CS201-SNA', 'CS201-CTF', 'CS201-SRE',
    'CS201-FIS', 'CS201-HCI', 'CS201-WAPP', 'CS201-DSTR', 'CS201-RMCT', 'CS201-COMT',
    'CS201-ISC', 'CS201-WPS',
    'CS101-IDB', 'CS101-IN', 'CS101-PYP', 'CS101-DGTIN', 'CS101-SSCC', 'CS101-PEP',
    'CS101-BM(A)', 'CS101-CC2', 'CS101-MCFC', 'CS101-ENTDNA', 'CS101-SAAD',
    'CS101-IOOP', 'CS101-ISFT', 'CS101-ICS', 'CS101-KIAR'];
  plan_ids uuid[];
  linked integer;
  removed_lessons integer;
  removed_plans integer;
begin
  if to_regclass('public.teaching_plans') is null then
    raise notice 'No teaching_plans table: nothing to remove.';
    return;
  end if;

  perform pg_advisory_xact_lock(7280001008::bigint);

  select coalesce(array_agg(p.id), '{}') into plan_ids
  from public.teaching_plans p
  join public.class_sections s on s.id = p.section_id
  join public.course_offerings o on o.id = s.offering_id
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code = any(linked_codes);

  if cardinality(plan_ids) = 0 then
    raise notice 'No CS(CYB) teaching plans: nothing to remove.';
    return;
  end if;

  select count(*) into linked
  from public.class_sessions cs
  join public.teaching_occurrences t on t.id = cs.occurrence_id
  where t.plan_id = any(plan_ids);

  if linked > 0 then
    raise exception 'Removal stopped: % class session(s) are linked to CS(CYB) lessons; nothing was deleted.',
      linked;
  end if;

  alter table public.teaching_occurrences disable trigger validate_teaching_occurrence;
  delete from public.teaching_occurrences where plan_id = any(plan_ids);
  get diagnostics removed_lessons = row_count;
  alter table public.teaching_occurrences enable trigger validate_teaching_occurrence;

  delete from public.teaching_plans where id = any(plan_ids);
  get diagnostics removed_plans = row_count;

  raise notice 'Removed % teaching plans and % lessons.', removed_plans, removed_lessons;
end;
$remove_teaching_plans_cyb$;

-- Independent verification. Expected after removal: cohort_plans 0,
-- cohort_lessons 0, occurrence_delete_check 'O' (the protection is back on).
select
  (select count(*)
   from public.teaching_plans p
   join public.class_sections s on s.id = p.section_id
   join public.course_offerings o on o.id = s.offering_id
   join public.intakes i on i.id = o.intake_id
   join public.courses c on c.id = o.course_id
   where i.intake_code in ('APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)')
     and c.course_code ~ '^CS[123]01-') as cohort_plans,
  (select count(*)
   from public.teaching_occurrences t
   join public.class_sections s on s.id = t.section_id
   join public.course_offerings o on o.id = s.offering_id
   join public.intakes i on i.id = o.intake_id
   join public.courses c on c.id = o.course_id
   where i.intake_code in ('APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)')
     and c.course_code ~ '^CS[123]01-') as cohort_lessons,
  (select tgenabled
   from pg_trigger
   where tgrelid = 'public.teaching_occurrences'::regclass
     and tgname = 'validate_teaching_occurrence') as occurrence_delete_check;
