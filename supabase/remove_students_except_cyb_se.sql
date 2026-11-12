-- SMART CAMPUS -- keep only the students of four intakes
-- Removes every student who belongs only to intakes other than:
--   APD1F2407CS(CYB), APD2F2506CS(CYB), APD3F2609CS(CYB)  (the CS(CYB) cohort)
--   APU1F2611CS(SE)                                       (has seed_courses.sql classes)
-- (user decision 13 November 2026). With the seed_students.sql sample data this
-- removes 880 of the 1,000 students and 1,200 of the 1,480 memberships, and
-- keeps 80 + 40 = 120 students with 280 memberships.
--
-- For each removed student it deletes their intake memberships, their meeting
-- attendance and the student record (including its login link). A student who
-- also belongs to a kept intake is kept, but loses memberships in other intakes,
-- so the other intakes end up with no students. Students with no membership at
-- all are not touched.
-- Kept: intakes themselves, courses, offerings, sections, class sessions,
-- meetings, teaching plans, and Supabase Auth accounts.
--
-- Stops, deleting nothing, if a kept intake code is missing (to catch typos), or
-- if a student to be removed is linked to a login account; set
-- remove_linked_accounts to true below to remove those too.
-- Undo: rerun seed_students.sql. It recreates the sample students and
-- memberships (removed students get new UUIDs and no login link).
-- Run the whole file as postgres in Supabase Dashboard > SQL Editor.
-- Atomic; rerunning deletes nothing.

do $remove_students_except_cyb_se$
declare
  kept_intakes constant text[] := array[
    'APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)', 'APU1F2611CS(SE)'];
  remove_linked_accounts constant boolean := false;
  kept_ids uuid[];
  target_ids uuid[];
  linked integer;
  removed_attendance integer;
  removed_memberships integer;
  removed_students integer;
begin
  perform pg_advisory_xact_lock(7280001008::bigint);

  select coalesce(array_agg(id), '{}') into kept_ids
  from public.intakes where intake_code = any(kept_intakes);

  if cardinality(kept_ids) <> cardinality(kept_intakes) then
    raise exception 'Only % of the % kept intakes exist (%); check the codes. Nothing was deleted.',
      cardinality(kept_ids), cardinality(kept_intakes), array_to_string(kept_intakes, ', ');
  end if;

  -- Students with a membership outside the kept intakes and none inside them.
  select coalesce(array_agg(s.id), '{}') into target_ids
  from public.students s
  where exists (select 1 from public.student_intakes m
                where m.student_id = s.id and not (m.intake_id = any(kept_ids)))
    and not exists (select 1 from public.student_intakes m
                    where m.student_id = s.id and m.intake_id = any(kept_ids));

  select count(*) into linked
  from public.students where id = any(target_ids) and auth_user_id is not null;

  if linked > 0 and not remove_linked_accounts then
    raise exception '% student(s) to be removed are linked to login accounts. Nothing was deleted; set remove_linked_accounts to true to remove them as well.',
      linked;
  end if;

  delete from public.meeting_students where student_id = any(target_ids);
  get diagnostics removed_attendance = row_count;

  -- All memberships outside the kept intakes, including those of kept students.
  delete from public.student_intakes where not (intake_id = any(kept_ids));
  get diagnostics removed_memberships = row_count;

  delete from public.students where id = any(target_ids);
  get diagnostics removed_students = row_count;

  raise notice 'Removed % students, % memberships and % meeting attendances (% linked login(s) unlinked).',
    removed_students, removed_memberships, removed_attendance, linked;
end;
$remove_students_except_cyb_se$;

-- Independent verification: students per intake that still has members.
-- Expected with the sample data: APD1F2407CS(CYB), APD2F2506CS(CYB) and
-- APD3F2609CS(CYB) 80 each, APU1F2611CS(SE) 40; 120 students in total.
select
  i.intake_code,
  count(*) as students,
  count(*) filter (where m.group_number = 1) as group_1,
  count(*) filter (where m.group_number = 2) as group_2,
  (select count(*) from public.students) as all_students
from public.student_intakes m
join public.intakes i on i.id = m.intake_id
group by i.intake_code
order by i.intake_code;
