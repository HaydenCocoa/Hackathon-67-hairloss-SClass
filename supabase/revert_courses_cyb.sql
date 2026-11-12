-- SMART CAMPUS -- revert seed_courses_cyb.sql
-- Deletes the rows that seed_courses_cyb.sql adds for the CS(CYB) cohort:
--   * the class sections and intake offerings of its 41 modules in
--     APD1F2407CS(CYB), APD2F2506CS(CYB) and APD3F2609CS(CYB);
--   * the 78 course rows it creates (CS101-*, CS201-*, CS301-*).
-- Kept:
--   * CS101-IN and CS101-PYP: they belong to seed_courses.sql
--     (APU1F2611CS(SE)); only the year 1 offerings that link them are removed;
--   * the three intakes and their student memberships (from seed_students.sql);
--   * any course row that another intake's offering still uses.
-- Stops, deleting nothing, when a class session or teaching plan already uses
-- one of these sections: cancel/remove that timetable data deliberately first.
-- Run the whole file as postgres in Supabase Dashboard > SQL Editor.
-- It is atomic and can be rerun; a second run deletes nothing.

do $revert_courses_cyb$
declare
  cohort_intakes constant text[] := array[
    'APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)'];
  -- Every module code the seed links (41), including the reused CS101-IN/PYP.
  linked_codes constant text[] := array[
    'CS301-INV', 'CS301-ALG', 'CS301-VAPT', 'CS301-CIS', 'CS301-PM', 'CS301-DLID',
    'CS301-VB', 'CS301-IOT', 'CS301-PRJ', 'CS301-ADS', 'CS301-ASS', 'CS301-ACS',
    'CS201-ENTINV', 'CS201-OODJ', 'CS201-SDM', 'CS201-SNA', 'CS201-CTF', 'CS201-SRE',
    'CS201-FIS', 'CS201-HCI', 'CS201-WAPP', 'CS201-DSTR', 'CS201-RMCT', 'CS201-COMT',
    'CS201-ISC', 'CS201-WPS',
    'CS101-IDB', 'CS101-IN', 'CS101-PYP', 'CS101-DGTIN', 'CS101-SSCC', 'CS101-PEP',
    'CS101-BM(A)', 'CS101-CC2', 'CS101-MCFC', 'CS101-ENTDNA', 'CS101-SAAD',
    'CS101-IOOP', 'CS101-ISFT', 'CS101-ICS', 'CS101-KIAR'];
  -- Course rows owned by seed_courses.sql: never deleted here.
  reused_codes constant text[] := array['CS101-IN', 'CS101-PYP'];
  offering_ids uuid[];
  section_ids uuid[];
  blocking integer;
  removed_sections integer;
  removed_offerings integer;
  removed_courses integer;
  kept_courses integer;
begin
  perform pg_advisory_xact_lock(7280001008::bigint);

  select coalesce(array_agg(o.id), '{}') into offering_ids
  from public.course_offerings o
  join public.intakes i on i.id = o.intake_id
  join public.courses c on c.id = o.course_id
  where i.intake_code = any(cohort_intakes)
    and c.course_code = any(linked_codes);

  select coalesce(array_agg(s.id), '{}') into section_ids
  from public.class_sections s
  where s.offering_id = any(offering_ids);

  select count(*) into blocking
  from public.class_sessions cs where cs.section_id = any(section_ids);
  if blocking > 0 then
    raise exception 'Revert stopped: % class session(s) use CS(CYB) sections. Remove them deliberately first; nothing was deleted.',
      blocking;
  end if;

  if to_regclass('public.teaching_plans') is not null then
    execute 'select count(*) from public.teaching_plans where section_id = any($1)'
      into blocking using section_ids;
    if blocking > 0 then
      raise exception 'Revert stopped: % teaching plan(s) use CS(CYB) sections. Remove them deliberately first; nothing was deleted.',
        blocking;
    end if;
  end if;

  delete from public.class_sections where id = any(section_ids);
  get diagnostics removed_sections = row_count;

  delete from public.course_offerings where id = any(offering_ids);
  get diagnostics removed_offerings = row_count;

  delete from public.courses c
  where c.course_code = any(linked_codes)
    and not (c.course_code = any(reused_codes))
    and not exists (select 1 from public.course_offerings o where o.course_id = c.id);
  get diagnostics removed_courses = row_count;

  select count(*) into kept_courses
  from public.courses c
  where c.course_code = any(linked_codes)
    and not (c.course_code = any(reused_codes));

  raise notice 'Removed % sections, % offerings and % courses. % seeded course row(s) kept because another intake uses them.',
    removed_sections, removed_offerings, removed_courses, kept_courses;
end;
$revert_courses_cyb$;

-- Independent verification. Expected after a clean revert: cohort_offerings 0,
-- cohort_courses 0, reused_courses 4 (CS101-IN/PYP lecture + lab still present).
select
  (select count(*)
   from public.course_offerings o
   join public.intakes i on i.id = o.intake_id
   join public.courses c on c.id = o.course_id
   where i.intake_code in ('APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)')
     and c.course_code ~ '^CS[123]01-') as cohort_offerings,
  (select count(*)
   from public.courses c
   where c.course_code ~ '^CS[123]01-'
     and c.course_code not in ('CS101-IN', 'CS101-PYP', 'CS101-ISE')) as cohort_courses,
  (select count(*)
   from public.courses c
   where c.course_code in ('CS101-IN', 'CS101-PYP')) as reused_courses;
