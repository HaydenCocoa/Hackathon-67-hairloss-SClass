-- SMART CAMPUS -- courses for the CS(CYB) cohort, years 1 to 3
--   APD1F2407CS(CYB)  year 1 (both semesters)
--   APD2F2506CS(CYB)  year 2 (both semesters; Internship excluded)
--   APD3F2609CS(CYB)  year 3 (both semesters, from the programme schedule)
-- Run as postgres in Supabase Dashboard > SQL Editor after schema.sql,
-- seed_lecturers.sql, seed_courses.sql and (normally) seed_students.sql, which
-- already creates these three intakes with max_group = 2. A missing intake is
-- created with 2 groups.
--
-- Course codes: CS101-<module> for year 1, CS201-<module> for year 2 and
-- CS301-<module> for year 3.
-- Covers 41 modules: 82 intake offerings (two teaching components each) and
-- one class section per component for every group of the intake (164 sections
-- with 2 groups). It creates 78 course rows of 120 minutes each.
-- CS101-IN and CS101-PYP are not created here: year 1 uses the existing
-- lecture + lab course rows from seed_courses.sql, unchanged. The seed stops if
-- they are missing.
-- Both components of a module use the same lecturer (LEC004-LEC020; LEC001-003
-- stay with APU1F2611CS(SE)). No teaching plans or dated class_sessions are
-- created; dates/times are configured later.
--
-- Works before and after migrations/202611100002_remove_required_room_type.sql:
-- the legacy column is filled only when it still exists.
-- Run the whole file. The seed is atomic and can be rerun without duplicates.

do $seed_courses_cyb$
declare
  module record;
  component text;
  intake_uuid uuid;
  intake_group_limit integer;
  lecturer_uuid uuid;
  course_uuid uuid;
  offering_uuid uuid;
  group_no integer;
  has_room_column boolean;
  module_count integer := 0;
begin
  perform pg_advisory_xact_lock(7280001008::bigint);

  select exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'class_sections'
      and column_name = 'required_room_type'
  ) into has_room_column;

  for module in
    select * from (values
      -- Year 3, semester 1 (programme schedule APD3F2609CS(CYB)).
      -- Codes: CS101-* year 1, CS201-* year 2, CS301-* year 3 (module abbreviation after the dash).
      ('APD3F2609CS(CYB)', 'CS301-INV',  'Investigations',                                  array['lecture','tutorial'], 'LEC004'),
      ('APD3F2609CS(CYB)', 'CS301-ALG',  'Algorithmics',                                    array['lecture','tutorial'], 'LEC005'),
      ('APD3F2609CS(CYB)', 'CS301-VAPT', 'Vulnerability Assessment and Penetration Testing', array['lecture','lab'],      'LEC006'),
      ('APD3F2609CS(CYB)', 'CS301-CIS',  'Cloud Infrastructure and Services',               array['lecture','tutorial'], 'LEC007'),
      ('APD3F2609CS(CYB)', 'CS301-PM',   'Project Management',                              array['lecture','tutorial'], 'LEC008'),
      ('APD3F2609CS(CYB)', 'CS301-DLID', 'Deep Learning for Intrusion Detection',           array['lecture','tutorial'], 'LEC009'),
      ('APD3F2609CS(CYB)', 'CS301-VB',   'Venture Building',                                array['lecture','tutorial'], 'LEC010'),
      ('APD3F2609CS(CYB)', 'CS301-IOT',  'Internet of Things: Concepts and Applications',   array['tutorial','lab'],     'LEC011'),
      -- Year 3, semester 2
      ('APD3F2609CS(CYB)', 'CS301-PRJ',  'Project Module',                                  array['lecture','tutorial'], 'LEC012'),
      ('APD3F2609CS(CYB)', 'CS301-ADS',  'Advanced Database Systems',                       array['lecture','tutorial'], 'LEC013'),
      ('APD3F2609CS(CYB)', 'CS301-ASS',  'Advanced Software Security',                      array['lecture','tutorial'], 'LEC014'),
      ('APD3F2609CS(CYB)', 'CS301-ACS',  'Advanced Cyber Security',                         array['lecture','tutorial'], 'LEC015'),
      -- Year 2, semester 1
      ('APD2F2506CS(CYB)', 'CS201-ENTINV', 'Innovation Process',                      array['lecture','tutorial'], 'LEC016'),
      ('APD2F2506CS(CYB)', 'CS201-OODJ',   'Object Oriented Development with Java',   array['lecture','lab'],      'LEC017'),
      ('APD2F2506CS(CYB)', 'CS201-SDM',    'System Development Methods',              array['lecture','tutorial'], 'LEC018'),
      ('APD2F2506CS(CYB)', 'CS201-SNA',    'System and Network Administration',       array['lecture','lab'],      'LEC019'),
      ('APD2F2506CS(CYB)', 'CS201-CTF',    'Practical CTF Strategies',                array['lecture','lab'],      'LEC020'),
      ('APD2F2506CS(CYB)', 'CS201-SRE',    'Switching and Routing Essentials',        array['lecture','lab'],      'LEC004'),
      ('APD2F2506CS(CYB)', 'CS201-FIS',      'Philosophy and Current Issues',           array['lecture','tutorial'], 'LEC005'),
      -- Year 2, semester 2 (Internship deliberately excluded)
      ('APD2F2506CS(CYB)', 'CS201-HCI',    'Human Computer Interaction',              array['lecture','tutorial'], 'LEC006'),
      ('APD2F2506CS(CYB)', 'CS201-WAPP',   'Web Applications',                        array['lecture','lab'],      'LEC007'),
      ('APD2F2506CS(CYB)', 'CS201-DSTR',   'Data Structures',                         array['lecture','lab'],      'LEC008'),
      ('APD2F2506CS(CYB)', 'CS201-RMCT',   'Research Methods for Computing and Technology', array['lecture','tutorial'], 'LEC009'),
      ('APD2F2506CS(CYB)', 'CS201-COMT',   'Computing Theory',                        array['lecture','tutorial'], 'LEC010'),
      ('APD2F2506CS(CYB)', 'CS201-ISC',    'Implementation of Secure Systems',        array['lecture','tutorial'], 'LEC011'),
      ('APD2F2506CS(CYB)', 'CS201-WPS',      'Workplace Professional Skills',           array['lecture','tutorial'], 'LEC012'),
      -- Year 1, semester 1
      ('APD1F2407CS(CYB)', 'CS101-IDB',    'Introduction to Databases',               array['lecture','tutorial'], 'LEC013'),
      -- NULL name: reuse the existing course rows from seed_courses.sql; not created here.
      ('APD1F2407CS(CYB)', 'CS101-IN',     null,                                      array['lecture','lab'],      'LEC014'),
      ('APD1F2407CS(CYB)', 'CS101-PYP',    null,                                      array['lecture','lab'],      'LEC015'),
      ('APD1F2407CS(CYB)', 'CS101-DGTIN',  'Digital Thinking and Innovation',         array['lecture','tutorial'], 'LEC016'),
      ('APD1F2407CS(CYB)', 'CS101-SSCC',   'System Software and Computing Concepts',  array['lecture','tutorial'], 'LEC017'),
      ('APD1F2407CS(CYB)', 'CS101-PEP',      'Penghayatan Etika dan Peradaban',         array['lecture','tutorial'], 'LEC018'),
      ('APD1F2407CS(CYB)', 'CS101-BM(A)',    'Bahasa Kebangsaan A',                     array['lecture','tutorial'], 'LEC019'),
      ('APD1F2407CS(CYB)', 'CS101-CC2',      'Co-Curricular 2',                         array['lecture','tutorial'], 'LEC020'),
      -- Year 1, semester 2
      ('APD1F2407CS(CYB)', 'CS101-MCFC',   'Mathematical Concept For Computing',      array['lecture','tutorial'], 'LEC004'),
      ('APD1F2407CS(CYB)', 'CS101-ENTDNA', 'Fundamental of Entrepreneurship',         array['lecture','tutorial'], 'LEC005'),
      ('APD1F2407CS(CYB)', 'CS101-SAAD',   'Systems Analysis and Design',             array['lecture','tutorial'], 'LEC006'),
      ('APD1F2407CS(CYB)', 'CS101-IOOP',   'Introduction To Object Oriented Programming', array['lecture','lab'],  'LEC007'),
      ('APD1F2407CS(CYB)', 'CS101-ISFT',   'Introduction to Security and Forensic Technologies', array['lecture','tutorial'], 'LEC008'),
      ('APD1F2407CS(CYB)', 'CS101-ICS',    'Integrated Computer Systems',             array['lecture','tutorial'], 'LEC009'),
      ('APD1F2407CS(CYB)', 'CS101-KIAR',     'Integrity and Anti-Corruption Course',    array['lecture','tutorial'], 'LEC010')
    ) as plan(intake_code, course_code, course_name, components, lecturer_code)
  loop
    insert into public.intakes(intake_code, max_group)
    values (module.intake_code, 2)
    on conflict (intake_code) do nothing;

    select id, max_group into intake_uuid, intake_group_limit
    from public.intakes where intake_code = module.intake_code;

    select id into lecturer_uuid
    from public.lecturers where lecturer_code = module.lecturer_code;

    if not found then
      raise exception 'Lecturer % is missing: run seed_lecturers.sql first', module.lecturer_code;
    end if;

    foreach component in array module.components loop
      if module.course_name is null then
        -- Existing course (CS101-IN, CS101-PYP): link it, never create or change it.
        select id into course_uuid
        from public.courses
        where course_code = module.course_code and course_type = component;

        if not found then
          raise exception 'Course % (%) is missing: run seed_courses.sql first',
            module.course_code, component;
        end if;
      else
        insert into public.courses(course_code, name, course_type, duration_minutes)
        values (module.course_code, module.course_name, component, 120)
        on conflict (course_code, course_type) do update
        set name = excluded.name,
            duration_minutes = excluded.duration_minutes
        returning id into course_uuid;
      end if;

      insert into public.course_offerings(course_id, intake_id, lecturer_id)
      values (course_uuid, intake_uuid, lecturer_uuid)
      on conflict (course_id, intake_id) do update
      set lecturer_id = excluded.lecturer_id
      returning id into offering_uuid;

      for group_no in 1 .. intake_group_limit loop
        if has_room_column then
          -- Legacy column only; dynamic so the block also compiles without it.
          execute 'insert into public.class_sections(offering_id, group_number, required_room_type)
                   values ($1, $2, $3)
                   on conflict (offering_id, group_number) do update
                   set required_room_type = excluded.required_room_type'
          using offering_uuid, group_no,
                case component when 'lab' then 'lab' else 'classroom' end;
        else
          insert into public.class_sections(offering_id, group_number)
          values (offering_uuid, group_no)
          on conflict (offering_id, group_number) do nothing;
        end if;
      end loop;
    end loop;

    module_count := module_count + 1;
  end loop;

  raise notice 'Created/updated % CS(CYB) modules with their offerings and group sections.',
    module_count;
end;
$seed_courses_cyb$;

-- Independent verification: one row per intake. Expected with 2 groups each:
-- APD1F2407CS(CYB) 15 modules, 30 components, 60 sections;
-- APD2F2506CS(CYB) 14 modules, 28 components, 56 sections;
-- APD3F2609CS(CYB) 12 modules, 24 components, 48 sections.
select
  i.intake_code,
  i.max_group,
  count(distinct c.course_code) as modules,
  count(distinct o.id) as components,
  count(s.id) as sections,
  count(distinct l.lecturer_code) as lecturers,
  min(c.duration_minutes) as min_minutes,
  max(c.duration_minutes) as max_minutes
from public.course_offerings o
join public.courses c on c.id = o.course_id
join public.intakes i on i.id = o.intake_id
join public.lecturers l on l.id = o.lecturer_id
left join public.class_sections s on s.offering_id = o.id
where i.intake_code in ('APD1F2407CS(CYB)', 'APD2F2506CS(CYB)', 'APD3F2609CS(CYB)')
group by i.intake_code, i.max_group
order by i.intake_code;
