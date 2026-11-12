-- SMART CAMPUS -- give the Year 2 and Year 3 CS(CYB) intakes their own students
-- Problem (13 November 2026): seed_students.sql put the same 80 students in all
-- three CS(CYB) intakes, so after the rename to APD1F2611CS(CYB),
-- APD2F2611CS(CYB) and APD3F2611CS(CYB) the three years share one student list.
--
-- This script:
--   1. removes every current member from APD2F2611CS(CYB) and APD3F2611CS(CYB);
--      they are not deleted and keep their other memberships (the shared 80 stay
--      in APD1F2611CS(CYB), which is not touched);
--   2. adds 80 new fictional students to each of those two intakes:
--        APD2F2611CS(CYB): TP001001-TP001080, surnames Adams/Bell, ages 19-22
--        APD3F2611CS(CYB): TP001081-TP001160, surnames Cook/Edwards, ages 20-23
--      groups alternate 1, 2, 1, 2 ... so each group has 40 students;
--   3. keeps each new student in that single intake only.
-- New codes are outside the sample range TP000001-TP001000, so rerunning
-- seed_students.sql does not change them. The new names do not repeat any
-- sample name. No login accounts are created.
--
-- Stops, changing nothing, if either intake is missing or has fewer than 2
-- groups, or if one of the new codes already belongs to a different student.
-- Run the whole file as postgres in Supabase Dashboard > SQL Editor.
-- Atomic; rerunning changes nothing.

do $split_cyb_students$
declare
  target record;
  intake_uuid uuid;
  intake_groups integer;
  student_uuid uuid;
  new_ids uuid[];
  n integer;
  code_value text;
  name_value text;
  age_value integer;
  removed integer;
  removed_total integer := 0;
  added_total integer := 0;
  given_names constant text[] := array[
    'Adam', 'Alex', 'Amelia', 'Andrew', 'Anna', 'Anthony', 'Benjamin', 'Charlotte',
    'Chloe', 'Daniel', 'David', 'Dylan', 'Ella', 'Emily', 'Emma', 'Ethan',
    'Grace', 'Hannah', 'Henry', 'Isabella', 'Jack', 'Jacob', 'James', 'Jessica',
    'Joshua', 'Julia', 'Leo', 'Liam', 'Lily', 'Lucas', 'Mia', 'Michael',
    'Nathan', 'Noah', 'Olivia', 'Ryan', 'Samuel', 'Sarah', 'Sophia', 'William'];
begin
  perform pg_advisory_xact_lock(7280001008::bigint);

  for target in
    select * from (values
      ('APD2F2611CS(CYB)', 1001, array['Adams', 'Bell'],   19),
      ('APD3F2611CS(CYB)', 1081, array['Cook', 'Edwards'], 20)
    ) as plan(intake_code, first_number, surnames, first_age)
  loop
    select id, max_group into intake_uuid, intake_groups
    from public.intakes where intake_code = target.intake_code;

    if not found then
      raise exception 'Intake % is missing; nothing was changed', target.intake_code;
    end if;
    if intake_groups < 2 then
      raise exception 'Intake % has % group(s); 2 are needed. Nothing was changed', target.intake_code, intake_groups;
    end if;

    new_ids := '{}';
    for n in 1..80 loop
      code_value := 'TP' || lpad((target.first_number + n - 1)::text, 6, '0');
      name_value := given_names[((n - 1) % 40) + 1] || ' ' || target.surnames[((n - 1) / 40) + 1];
      age_value := target.first_age + ((n - 1) % 4);

      if exists (select 1 from public.students
                 where student_code = code_value and full_name <> name_value) then
        raise exception 'Student code % already belongs to another student; nothing was changed', code_value;
      end if;

      insert into public.students (student_code, full_name, age)
      values (code_value, name_value, age_value)
      on conflict (student_code) do update set age = excluded.age
      returning id into student_uuid;

      -- One intake only.
      delete from public.student_intakes
      where student_id = student_uuid and intake_id <> intake_uuid;

      insert into public.student_intakes (student_id, intake_id, group_number)
      values (student_uuid, intake_uuid, ((n - 1) % 2) + 1)
      on conflict (student_id, intake_id) do update set group_number = excluded.group_number;

      new_ids := array_append(new_ids, student_uuid);
    end loop;

    -- Everyone else leaves this intake (the shared students stay in their other intakes).
    delete from public.student_intakes
    where intake_id = intake_uuid and not (student_id = any(new_ids));
    get diagnostics removed = row_count;

    removed_total := removed_total + removed;
    added_total := added_total + cardinality(new_ids);
  end loop;

  raise notice 'Removed % memberships from APD2F2611CS(CYB)/APD3F2611CS(CYB); % new students now hold their places.',
    removed_total, added_total;
end;
$split_cyb_students$;

-- Independent verification. Expected: APD2F2611CS(CYB) and APD3F2611CS(CYB)
-- 80 students each (40 / 40), shared_with_other_cyb 0 for every row;
-- APD1F2611CS(CYB) keeps its own students.
select
  i.intake_code,
  count(*) as students,
  count(*) filter (where m.group_number = 1) as group_1,
  count(*) filter (where m.group_number = 2) as group_2,
  count(*) filter (where exists (
    select 1 from public.student_intakes m2
    join public.intakes i2 on i2.id = m2.intake_id
    where m2.student_id = m.student_id and m2.intake_id <> m.intake_id
      and i2.intake_code like '%CS(CYB)')) as shared_with_other_cyb,
  count(distinct s.full_name) as distinct_names
from public.student_intakes m
join public.intakes i on i.id = m.intake_id
join public.students s on s.id = m.student_id
where i.intake_code like '%CS(CYB)'
group by i.intake_code
order by i.intake_code;
