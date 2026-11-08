-- SMART CAMPUS -- 1,000 fictional students, 12 cohorts, 18 intake codes
-- Run the entire file as postgres after schema.sql or the required upgrades.
-- One atomic DO block; no temporary tables.
-- Codes TP000001 through TP001000; sample ages 18..25 (125 students per age).
-- REPLACES all intake memberships for these 1,000 sample student codes so old
-- assignments do not accumulate. Keeps student UUIDs, linked accounts, meetings,
-- other students' memberships, and shared campus records.
-- The last four cohorts reuse the SAME students across their listed intakes.
-- Expected result: 1,000 student identities and 1,480 sample memberships.

do $seed_students$
declare
  seed_cohort record;
  intake_code_value text;
  intake_uuid uuid;
  intake_uuids uuid[];
  student_uuid uuid;
  local_student_number integer;
  sample_number integer := 0;
  student_code_value text;
  student_name_value text;
  student_age_value integer;
  seeded_count integer;
  distinct_name_count integer;
  membership_count integer;
  given_names text[] := array[
    'Adam', 'Alex', 'Amelia', 'Andrew', 'Anna', 'Anthony', 'Benjamin', 'Charlotte',
    'Chloe', 'Daniel', 'David', 'Dylan', 'Ella', 'Emily', 'Emma', 'Ethan',
    'Grace', 'Hannah', 'Henry', 'Isabella', 'Jack', 'Jacob', 'James', 'Jessica',
    'Joshua', 'Julia', 'Leo', 'Liam', 'Lily', 'Lucas', 'Mia', 'Michael',
    'Nathan', 'Noah', 'Olivia', 'Ryan', 'Samuel', 'Sarah', 'Sophia', 'William'
  ];
  surnames text[] := array[
    'Anderson', 'Baker', 'Brown', 'Carter', 'Clark', 'Collins', 'Davies', 'Evans',
    'Hall', 'Harris', 'Jackson', 'Johnson', 'Jones', 'King', 'Lewis', 'Martin',
    'Miller', 'Moore', 'Parker', 'Robinson', 'Smith', 'Taylor', 'Thomas', 'Walker', 'Wilson'
  ];
begin
  if to_regclass('public.student_intakes') is null then
    raise exception 'student_intakes is missing: run schema.sql or the membership upgrade first';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'students'
      and column_name = 'age' and data_type = 'integer'
  ) then
    raise exception 'students.age is missing or incompatible: run migrations/202611080002_student_age.sql first';
  end if;

  -- Reuse the schema's integrity lock while replacing sample memberships.
  perform pg_advisory_xact_lock(7280001008::bigint);
  delete from public.student_intakes m
  using public.students s
  where m.student_id = s.id
    and s.student_code ~ '^TP[0-9]{6}$'
    and s.student_code between 'TP000001' and 'TP001000';

  for seed_cohort in
    select * from (values
      ( 1, 100, 3, array['APU1F2611CS(CYB)']),
      ( 2, 100, 3, array['APU1F2611CS']),
      ( 3, 100, 3, array['APU1F2611CS(DF)']),
      ( 4,  40, 1, array['APU1F2611CS(SE)']),
      ( 5, 100, 3, array['APD1F2611CS(CYB)']),
      ( 6, 100, 3, array['APD1F2611CS']),
      ( 7, 100, 3, array['APD1F2611CS(DF)']),
      ( 8,  40, 1, array['APD1F2611CS(SE)']),
      ( 9,  80, 2, array['APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)']),
      (10,  80, 2, array['APD1F2407CS', 'APD2F2506CS', 'APD3F2609CS']),
      (11,  80, 2, array['APD1F2507CS(CYB)', 'APD2F2606CS(CYB)']),
      (12,  80, 2, array['APD1F2507CS', 'APD2F2606CS'])
    ) as plan(cohort_order, student_count, max_group, intake_codes)
    order by cohort_order
  loop
    intake_uuids := array[]::uuid[];
    foreach intake_code_value in array seed_cohort.intake_codes loop
      insert into public.intakes (intake_code, max_group)
      values (intake_code_value, seed_cohort.max_group)
      on conflict (intake_code) do update
      set max_group = excluded.max_group
      returning id into intake_uuid;
      intake_uuids := array_append(intake_uuids, intake_uuid);
    end loop;

    for local_student_number in 1..seed_cohort.student_count loop
      sample_number := sample_number + 1;
      student_code_value := 'TP' || lpad(sample_number::text, 6, '0');
      student_name_value := given_names[((sample_number - 1) % 40) + 1]
        || ' ' || surnames[((sample_number - 1) / 40) + 1];
      student_age_value := 18 + ((sample_number - 1) % 8);

      insert into public.students (student_code, full_name, age)
      values (student_code_value, student_name_value, student_age_value)
      on conflict (student_code) do update
      set full_name = excluded.full_name,
          age = excluded.age
      returning id into student_uuid;

      foreach intake_uuid in array intake_uuids loop
        insert into public.student_intakes (student_id, intake_id, group_number)
        values (
          student_uuid,
          intake_uuid,
          ((local_student_number - 1) % seed_cohort.max_group) + 1
        )
        on conflict (student_id, intake_id) do update
        set group_number = excluded.group_number;
      end loop;
    end loop;
  end loop;

  select count(*), count(distinct full_name)
  into seeded_count, distinct_name_count
  from public.students
  where student_code ~ '^TP[0-9]{6}$'
    and student_code between 'TP000001' and 'TP001000';

  select count(*) into membership_count
  from public.student_intakes m
  join public.students s on s.id = m.student_id
  where s.student_code ~ '^TP[0-9]{6}$'
    and s.student_code between 'TP000001' and 'TP001000';

  if sample_number <> 1000 or seeded_count <> 1000 or distinct_name_count <> 1000
     or membership_count <> 1480 then
    raise exception 'Expected 1,000 sample students and 1,480 memberships; rolling back this seed';
  end if;

  raise notice 'Seeded 1,000 student identities and 1,480 memberships across 18 intakes.';
end;
$seed_students$;

-- Independent verification: actual sample-student memberships by intake/group.
-- Expected: 18 rows; sum(sample_students) = 1,480, not 1,000, because four cohorts
-- share their students across multiple intakes. Student identities total 1,000.
with group_counts as (
  select i.intake_code, i.max_group, m.group_number, count(*) as student_count
  from public.students s
  join public.student_intakes m on m.student_id = s.id
  join public.intakes i on i.id = m.intake_id
  where s.student_code ~ '^TP[0-9]{6}$'
    and s.student_code between 'TP000001' and 'TP001000'
  group by i.intake_code, i.max_group, m.group_number
)
select
  intake_code,
  max_group,
  sum(student_count)::integer as sample_students,
  jsonb_object_agg(group_number::text, student_count order by group_number) as students_per_group
from group_counts
group by intake_code, max_group
order by intake_code;
