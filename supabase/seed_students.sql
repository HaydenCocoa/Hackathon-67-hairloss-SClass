-- SMART CAMPUS -- 1,000 fictional sample students across nine intakes
-- Run after schema.sql in Supabase Dashboard > SQL Editor as postgres.
-- This file creates/updates the required intakes before inserting students.
-- Student codes: TP000001 through TP001000, in the intake order listed below.
-- Format: TP plus six digits (TP000001 through TP999999).
-- Groups are assigned round-robin, balancing group sizes to within one student.
-- Creates 1,000 student identities and 1,000 initial intake memberships.
-- Rerunning refreshes names and planned memberships without replacing UUIDs or
-- linked auth_user_id values. Additional memberships are preserved.
-- No login accounts or passwords are created.

begin;

create temporary table campus_student_seed_plan (
  intake_order integer primary key,
  intake_code text not null unique,
  student_count integer not null,
  max_group integer not null
) on commit drop;

insert into campus_student_seed_plan values
  (1, 'APD1F2407CS(CYB)', 100, 3),
  (2, 'APD1F2407CS',      200, 6),
  (3, 'APD1F2407CS(SE)',   40, 1),
  (4, 'APD2F2506CS(CYB)', 100, 3),
  (5, 'APD2F2506CS',      200, 6),
  (6, 'APD2F2506CS(SE)',   40, 1),
  (7, 'APD3F2609CS(CYB)',  80, 2),
  (8, 'APD3F2609CS',      200, 6),
  (9, 'APD3F2609CS(SE)',   40, 1);

insert into public.intakes (intake_code, max_group)
select intake_code, max_group
from campus_student_seed_plan
where true
on conflict (intake_code) do update
set max_group = excluded.max_group;

-- Forty given names x twenty-five surnames create 1,000 distinct sample names.
-- The names are synthetic combinations, not a list of real students.
create temporary table campus_student_seed_rows on commit drop as
with numbered_students as (
  select
    p.intake_code,
    ((n.student_number - 1) % p.max_group) + 1 as group_number,
    row_number() over (order by p.intake_order, n.student_number)::integer as sample_number
  from campus_student_seed_plan p
  cross join lateral generate_series(1, p.student_count) as n(student_number)
), name_parts as (
  select
    array[
      'Adam', 'Alex', 'Amelia', 'Andrew', 'Anna', 'Anthony', 'Benjamin', 'Charlotte',
      'Chloe', 'Daniel', 'David', 'Dylan', 'Ella', 'Emily', 'Emma', 'Ethan',
      'Grace', 'Hannah', 'Henry', 'Isabella', 'Jack', 'Jacob', 'James', 'Jessica',
      'Joshua', 'Julia', 'Leo', 'Liam', 'Lily', 'Lucas', 'Mia', 'Michael',
      'Nathan', 'Noah', 'Olivia', 'Ryan', 'Samuel', 'Sarah', 'Sophia', 'William'
    ]::text[] as given_names,
    array[
      'Anderson', 'Baker', 'Brown', 'Carter', 'Clark', 'Collins', 'Davies', 'Evans',
      'Hall', 'Harris', 'Jackson', 'Johnson', 'Jones', 'King', 'Lewis', 'Martin',
      'Miller', 'Moore', 'Parker', 'Robinson', 'Smith', 'Taylor', 'Thomas', 'Walker', 'Wilson'
    ]::text[] as surnames
)
select
  'TP' || lpad(n.sample_number::text, 6, '0') as student_code,
  names.given_names[((n.sample_number - 1) % 40) + 1]
    || ' ' || names.surnames[((n.sample_number - 1) / 40) + 1] as full_name,
  i.id as intake_id,
  n.group_number
from numbered_students n
join public.intakes i on i.intake_code = n.intake_code
cross join name_parts names;

insert into public.students (student_code, full_name)
select student_code, full_name
from campus_student_seed_rows
where true
on conflict (student_code) do update
set full_name = excluded.full_name;

insert into public.student_intakes (student_id, intake_id, group_number)
select s.id, seed.intake_id, seed.group_number
from campus_student_seed_rows seed
join public.students s on s.student_code = seed.student_code
where true
on conflict (student_id, intake_id) do update
set
  group_number = excluded.group_number;

-- Fail and roll back rather than silently committing an incomplete seed.
do $$
begin
  if (select count(*) from campus_student_seed_rows) <> 1000
     or (select count(distinct full_name) from campus_student_seed_rows) <> 1000 then
    raise exception 'Expected exactly 1,000 generated students with distinct names';
  end if;
  if exists (
    select 1
    from campus_student_seed_rows expected
    left join public.students actual on actual.student_code = expected.student_code
    left join public.student_intakes membership
      on membership.student_id = actual.id and membership.intake_id = expected.intake_id
    where actual.id is null
       or actual.full_name is distinct from expected.full_name
       or membership.student_id is null
       or membership.group_number is distinct from expected.group_number
  ) then
    raise exception 'Inserted students or memberships do not match the seed plan';
  end if;
end;
$$;

-- Verification output: only the planned initial memberships, not additional ones.
with group_counts as (
  select i.intake_code, i.max_group, membership.group_number, count(*) as student_count
  from campus_student_seed_rows seed
  join public.students s on s.student_code = seed.student_code
  join public.student_intakes membership
    on membership.student_id = s.id and membership.intake_id = seed.intake_id
  join public.intakes i on i.id = membership.intake_id
  group by i.intake_code, i.max_group, membership.group_number
)
select
  intake_code,
  max_group,
  sum(student_count)::integer as sample_students,
  jsonb_object_agg(group_number::text, student_count order by group_number) as students_per_group
from group_counts 
group by intake_code, max_group
order by intake_code;

commit;
