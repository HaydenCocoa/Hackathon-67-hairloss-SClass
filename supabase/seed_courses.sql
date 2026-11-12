-- SMART CAMPUS -- courses for APU1F2611CS(SE), Group 1
-- Run as postgres in Supabase Dashboard > SQL Editor after schema.sql and
-- seed_lecturers.sql. The intake is created with max_group=1 if it is missing.
-- All lectures, labs, and tutorials are 120 minutes, as requested.
-- Each subject uses the same lecturer for both of its teaching components:
-- CS101-PYP -> LEC001; CS101-IN -> LEC002; CS101-ISE -> LEC003.
-- Creates six course rows, six intake offerings, and six Group 1 sections.
-- No dated class_sessions are created; dates/times are configured later.
-- Run the whole file. The seed is atomic and can be rerun without duplicates.

do $seed_courses$
declare
  target_intake_code constant text := 'APU1F2611CS(SE)';
  subject record;
  component record;
  intake_uuid uuid;
  intake_group_limit integer;
  lecturer_uuid uuid;
  course_uuid uuid;
  offering_uuid uuid;
begin
  perform pg_advisory_xact_lock(7280001008::bigint);

  insert into public.intakes(intake_code, max_group)
  values (target_intake_code, 1)
  on conflict (intake_code) do nothing;

  select id, max_group into intake_uuid, intake_group_limit
  from public.intakes where intake_code = target_intake_code;

  if intake_group_limit <> 1 then
    raise exception 'Expected % to have exactly one group; found %',
      target_intake_code, intake_group_limit;
  end if;

  for subject in
    select * from (values
      ('CS101-PYP', 'Introduction to Programming',          'LEC001', 'lab',      'lab'),
      ('CS101-IN',  'Introduction to Networking',           'LEC002', 'lab',      'lab'),
      ('CS101-ISE', 'Introduction to Software Engineering', 'LEC003', 'tutorial', 'classroom')
    ) as plan(course_code, course_name, lecturer_code, second_type, second_room_type)
  loop
    select id into lecturer_uuid
    from public.lecturers where lecturer_code = subject.lecturer_code;

    if not found then
      raise exception 'Lecturer % is missing: run seed_lecturers.sql first', subject.lecturer_code;
    end if;

    for component in
      select * from (values
        ('lecture', 'classroom'),
        (subject.second_type, subject.second_room_type)
      ) as components(course_type, required_room_type)
    loop
      insert into public.courses(course_code, name, course_type, duration_minutes)
      values (subject.course_code, subject.course_name, component.course_type, 120)
      on conflict (course_code, course_type) do update
      set name = excluded.name,
          duration_minutes = excluded.duration_minutes
      returning id into course_uuid;

      insert into public.course_offerings(course_id, intake_id, lecturer_id)
      values (course_uuid, intake_uuid, lecturer_uuid)
      on conflict (course_id, intake_id) do update
      set lecturer_id = excluded.lecturer_id
      returning id into offering_uuid;

      insert into public.class_sections(offering_id, group_number, required_room_type)
      values (offering_uuid, 1, component.required_room_type)
      on conflict (offering_id, group_number) do update
      set required_room_type = excluded.required_room_type;
    end loop;
  end loop;

  raise notice 'Created/updated six course components and their Group 1 offerings for %.',
    target_intake_code;
end;
$seed_courses$;

-- Independent verification: six rows, all 120 minutes, with matching lecturers
-- across the two components for each course code.
select
  i.intake_code,
  c.course_code,
  c.name as course_name,
  c.course_type,
  c.duration_minutes,
  l.lecturer_code,
  l.full_name as lecturer_name,
  s.group_number,
  s.required_room_type
from public.course_offerings o
join public.courses c on c.id = o.course_id
join public.intakes i on i.id = o.intake_id
join public.lecturers l on l.id = o.lecturer_id
join public.class_sections s on s.offering_id = o.id
where i.intake_code = 'APU1F2611CS(SE)'
  and c.course_code in ('CS101-PYP', 'CS101-IN', 'CS101-ISE')
order by c.course_code,
  case c.course_type when 'lecture' then 1 else 2 end,
  s.group_number;
