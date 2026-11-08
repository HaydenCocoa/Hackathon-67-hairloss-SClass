-- SMART CAMPUS -- initial Supabase schema (PostgreSQL 15+)
-- Run this entire file ONCE in Supabase Dashboard > SQL Editor as postgres.
-- Uses the existing auth.users and auth.uid(); never creates/replaces them.
-- Supports the rooms table from the earlier tutorial if its definition is unchanged.
-- Other application tables must not already exist. No existing tables are dropped.
-- All changes are transactional: an error rolls back this setup.
-- This is schema setup, not the scheduling engine: overlap/capacity checking,
-- rescheduling RPCs, automatic audit writes, and notifications come next.

begin;

create schema if not exists campus_private;
revoke all on schema campus_private from public, anon, authenticated;

-- 1. Identity and intake data. Authentication accounts may be linked later.
create table public.intakes (
  id uuid primary key default gen_random_uuid(),
  intake_code text not null unique check (btrim(intake_code) <> ''),
  max_group integer not null default 1 check (max_group >= 1)
);

create table public.students (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid unique references auth.users(id) on delete set null,
  student_code text not null unique check (btrim(student_code) <> ''),
  full_name text not null check (btrim(full_name) <> '')
);

-- Group membership belongs to the student/intake pair, not the student's identity.
create table public.student_intakes (
  student_id uuid not null references public.students(id),
  intake_id uuid not null references public.intakes(id),
  group_number integer not null default 1 check (group_number >= 1),
  primary key (student_id, intake_id)
);

create table public.lecturers (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid unique references auth.users(id) on delete set null,
  lecturer_code text not null unique check (btrim(lecturer_code) <> ''),
  full_name text not null check (btrim(full_name) <> '')
);

create table public.admins (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid unique references auth.users(id) on delete set null,
  full_name text not null check (btrim(full_name) <> '')
);

-- 2. One course row per teaching type: CS101 lecture and CS101 lab may coexist.
create table public.courses (
  id uuid primary key default gen_random_uuid(),
  course_code text not null check (btrim(course_code) <> ''),
  name text not null check (btrim(name) <> ''),
  course_type text not null
    check (course_type in ('lecture', 'tutorial', 'lab', 'others')),
  duration_minutes integer not null check (duration_minutes > 0),
  constraint courses_code_type_unique unique (course_code, course_type)
);

create table public.course_offerings (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses(id),
  intake_id uuid not null references public.intakes(id),
  lecturer_id uuid not null references public.lecturers(id),
  constraint course_offerings_course_intake_unique unique (course_id, intake_id)
);

create table public.class_sections (
  id uuid primary key default gen_random_uuid(),
  offering_id uuid not null references public.course_offerings(id),
  group_number integer not null default 1 check (group_number >= 1),
  required_room_type text not null
    check (required_room_type in ('classroom', 'lab', 'auditorium')),
  constraint class_sections_offering_group_unique unique (offering_id, group_number)
);

-- IF NOT EXISTS is intentional only for this earlier tutorial table.
create table if not exists public.rooms (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  building text not null,
  capacity integer not null check (capacity > 0),
  room_type text not null
    check (room_type in ('classroom', 'lab', 'auditorium')),
  is_active boolean not null default true
);

-- 3. Dated bookings. No stored ends_at on class_sessions.
create table public.class_sessions (
  id uuid primary key default gen_random_uuid(),
  section_id uuid not null references public.class_sections(id),
  room_id uuid references public.rooms(id),
  starts_at timestamptz not null,
  status text not null default 'scheduled'
    check (status in ('scheduled', 'cancelled')),
  constraint scheduled_class_requires_room
    check (status <> 'scheduled' or room_id is not null)
);

create table public.meeting_sessions (
  id uuid primary key default gen_random_uuid(),
  lecturer_id uuid not null references public.lecturers(id),
  room_id uuid references public.rooms(id), -- NULL for an online meeting
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  status text not null default 'scheduled'
    check (status in ('scheduled', 'cancelled')),
  constraint meeting_positive_duration check (ends_at > starts_at)
);

create table public.meeting_students (
  meeting_id uuid not null references public.meeting_sessions(id) on delete cascade,
  student_id uuid not null references public.students(id),
  primary key (meeting_id, student_id)
);

create table public.schedule_changes (
  id uuid primary key default gen_random_uuid(),
  class_session_id uuid references public.class_sessions(id),
  meeting_session_id uuid references public.meeting_sessions(id),
  changed_by uuid not null references auth.users(id),
  action text not null check (action in ('cancel', 'reschedule')),
  reason text,
  old_values jsonb not null check (jsonb_typeof(old_values) = 'object'),
  new_values jsonb not null check (jsonb_typeof(new_values) = 'object'),
  created_at timestamptz not null default now(),
  constraint schedule_changes_one_session
    check (num_nonnulls(class_session_id, meeting_session_id) = 1)
);

-- 4. Index the relationships and the starting points for timetable queries.
-- PRIMARY KEY / UNIQUE constraints already create their own indexes.
create index student_intakes_intake_group_idx on public.student_intakes(intake_id, group_number);
create index offerings_intake_idx on public.course_offerings(intake_id);
create index offerings_lecturer_idx on public.course_offerings(lecturer_id);
create index sections_group_idx on public.class_sections(group_number);
create index class_sessions_section_time_idx on public.class_sessions(section_id, starts_at);
create index class_sessions_room_time_idx on public.class_sessions(room_id, starts_at)
  where status = 'scheduled';
create index meetings_lecturer_time_idx on public.meeting_sessions(lecturer_id, starts_at)
  where status = 'scheduled';
create index meetings_room_time_idx on public.meeting_sessions(room_id, starts_at)
  where status = 'scheduled';
create index meeting_students_student_idx on public.meeting_students(student_id);
create index changes_class_idx on public.schedule_changes(class_session_id);
create index changes_meeting_idx on public.schedule_changes(meeting_session_id);
create index changes_actor_idx on public.schedule_changes(changed_by);

-- 5. Cross-table integrity rules.
-- A common transaction lock deliberately serializes these configuration writes
-- for the hackathon dataset. It does NOT implement booking conflict detection.
-- READ COMMITTED is Supabase/Postgres's usual isolation level. Reject stronger
-- snapshot isolation here rather than validating ranges against stale snapshots.
create function campus_private.lock_integrity_changes()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'Campus configuration writes require READ COMMITTED isolation';
  end if;
  perform pg_advisory_xact_lock(7280001008::bigint);
  return null; -- statement-level trigger
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['intakes', 'student_intakes', 'courses', 'course_offerings',
                           'class_sections', 'class_sessions'] loop
    execute format('create trigger campus_integrity_lock before insert or update or delete on public.%I for each statement execute function campus_private.lock_integrity_changes()', t);
  end loop;
end;
$$;

create function campus_private.validate_student_intake_group()
returns trigger language plpgsql security definer set search_path = '' as $$
declare group_limit integer;
begin
  select max_group into group_limit from public.intakes where id = new.intake_id;
  if not found then
    raise exception 'Membership intake does not exist' using errcode = '23503';
  end if;
  if new.group_number > group_limit then
    raise exception 'Student group % exceeds intake maximum %', new.group_number, group_limit
      using errcode = '23514';
  end if;
  return new;
end;
$$;
create trigger validate_student_intake_group before insert or update on public.student_intakes
for each row execute function campus_private.validate_student_intake_group();

create function campus_private.validate_section_group()
returns trigger language plpgsql security definer set search_path = '' as $$
declare group_limit integer;
begin
  select i.max_group into group_limit
  from public.course_offerings o join public.intakes i on i.id = o.intake_id
  where o.id = new.offering_id;
  if not found then
    raise exception 'Course offering does not exist' using errcode = '23503';
  end if;
  if new.group_number > group_limit then
    raise exception 'Section group % exceeds intake maximum %', new.group_number, group_limit
      using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' then
    if new.offering_id is distinct from old.offering_id
       and exists (select 1 from public.class_sessions where section_id = old.id) then
      raise exception 'Cannot change a section offering after sessions exist';
    end if;
  end if;
  return new;
end;
$$;
create trigger validate_section_group before insert or update on public.class_sections
for each row execute function campus_private.validate_section_group();

create function campus_private.validate_intake_limit()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.max_group < old.max_group then
    if exists (select 1 from public.student_intakes
               where intake_id = old.id and group_number > new.max_group)
       or exists (select 1 from public.class_sections s
                  join public.course_offerings o on o.id = s.offering_id
                  where o.intake_id = old.id and s.group_number > new.max_group) then
      raise exception 'Cannot reduce max_group: memberships or sections use a higher group'
        using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;
create trigger validate_intake_limit before update on public.intakes
for each row execute function campus_private.validate_intake_limit();

create function campus_private.validate_offering_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare group_limit integer;
begin
  select max_group into group_limit from public.intakes where id = new.intake_id;
  if not found then
    raise exception 'Offering intake does not exist' using errcode = '23503';
  end if;
  if exists (select 1 from public.class_sections
             where offering_id = old.id and group_number > group_limit) then
    raise exception 'New intake does not support an existing section group'
      using errcode = '23514';
  end if;
  if (new.course_id is distinct from old.course_id
      or new.intake_id is distinct from old.intake_id)
     and exists (select 1 from public.class_sessions cs
                 join public.class_sections s on s.id = cs.section_id
                 where s.offering_id = old.id) then
    raise exception 'Cannot change offering course/intake after sessions exist';
  end if;
  return new;
end;
$$;
create trigger validate_offering_change before update on public.course_offerings
for each row execute function campus_private.validate_offering_change();

create function campus_private.protect_course_duration()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.duration_minutes is distinct from old.duration_minutes
     and exists (select 1 from public.class_sessions cs
                 join public.class_sections s on s.id = cs.section_id
                 join public.course_offerings o on o.id = s.offering_id
                 where o.course_id = old.id) then
    raise exception 'Duration is locked because class sessions already exist';
  end if;
  return new;
end;
$$;
create trigger protect_course_duration before update on public.courses
for each row execute function campus_private.protect_course_duration();

-- 6. API read access. Users cannot self-assign roles or write bookings yet.
-- Helpers run as their owner so policies do not recursively query themselves.
-- Their output only describes what the CURRENT authenticated user may access.
create function campus_private.is_admin()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.admins where auth_user_id = auth.uid());
$$;

create function campus_private.can_read_section(section_uuid uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select campus_private.is_admin() or exists (
    select 1 from public.class_sections s
    join public.course_offerings o on o.id = s.offering_id
    join public.lecturers l on l.id = o.lecturer_id
    where s.id = section_uuid and (
      l.auth_user_id = auth.uid() or exists (
        select 1 from public.students st
        join public.student_intakes membership on membership.student_id = st.id
        where st.auth_user_id = auth.uid()
          and membership.intake_id = o.intake_id
          and membership.group_number = s.group_number
      )
    )
  );
$$;

create function campus_private.can_read_meeting(meeting_uuid uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select campus_private.is_admin() or exists (
    select 1 from public.meeting_sessions m
    join public.lecturers l on l.id = m.lecturer_id
    where m.id = meeting_uuid and (
      l.auth_user_id = auth.uid() or exists (
        select 1 from public.meeting_students ms
        join public.students st on st.id = ms.student_id
        where ms.meeting_id = m.id and st.auth_user_id = auth.uid()
      )
    )
  );
$$;

-- RLS on all thirteen application tables. Dashboard SQL remains usable as postgres.
do $$
declare t text;
begin
  foreach t in array array['students','student_intakes','lecturers','admins','intakes','courses',
    'course_offerings','class_sections','rooms','class_sessions','meeting_sessions',
    'meeting_students','schedule_changes'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from public, anon, authenticated', t);
    execute format('grant select on table public.%I to authenticated', t);
    execute format('grant all on table public.%I to service_role', t);
  end loop;
end;
$$;

-- Remove only the named policy from the earlier rooms tutorial, if present.
drop policy if exists "Logged-in users can view rooms" on public.rooms;

create policy catalog_read on public.intakes for select to authenticated using (true);
create policy catalog_read on public.courses for select to authenticated using (true);
create policy catalog_read on public.rooms for select to authenticated using (true);
create policy catalog_read on public.course_offerings for select to authenticated using (true);
create policy own_or_admin_read on public.students for select to authenticated
  using (auth_user_id = (select auth.uid()) or (select campus_private.is_admin()));
create policy own_or_admin_read on public.student_intakes for select to authenticated
  using ((select campus_private.is_admin())
    or exists (select 1 from public.students st
               where st.id = student_id and st.auth_user_id = (select auth.uid())));
create policy own_or_admin_read on public.lecturers for select to authenticated
  using (auth_user_id = (select auth.uid()) or (select campus_private.is_admin()));
create policy own_or_admin_read on public.admins for select to authenticated
  using (auth_user_id = (select auth.uid()) or (select campus_private.is_admin()));
create policy section_read on public.class_sections for select to authenticated
  using (campus_private.can_read_section(id));
create policy session_read on public.class_sessions for select to authenticated
  using (campus_private.can_read_section(section_id));
create policy meeting_read on public.meeting_sessions for select to authenticated
  using (campus_private.can_read_meeting(id));
create policy participant_read on public.meeting_students for select to authenticated
  using ((select campus_private.is_admin())
    or exists (select 1 from public.students s
               where s.id = student_id and s.auth_user_id = (select auth.uid()))
    or exists (select 1 from public.meeting_sessions m
               join public.lecturers l on l.id = m.lecturer_id
               where m.id = meeting_id and l.auth_user_id = (select auth.uid())));
create policy change_read on public.schedule_changes for select to authenticated
  using ((select campus_private.is_admin())
    or exists (select 1 from public.class_sessions cs where cs.id = class_session_id)
    or (meeting_session_id is not null and campus_private.can_read_meeting(meeting_session_id)));

grant usage on schema campus_private to authenticated;
revoke all on all functions in schema campus_private from public, anon, authenticated;
grant execute on function campus_private.is_admin() to authenticated;
grant execute on function campus_private.can_read_section(uuid) to authenticated;
grant execute on function campus_private.can_read_meeting(uuid) to authenticated;

-- 7. Query this view for a class timetable INCLUDING calculated end times.
-- security_invoker preserves the querying user's underlying RLS permissions.
create view public.class_session_details with (security_invoker = true) as
select
  cs.id, cs.section_id, cs.room_id, cs.starts_at,
  cs.starts_at + c.duration_minutes * interval '1 minute' as ends_at,
  cs.status, s.group_number, s.required_room_type,
  o.id as offering_id, o.intake_id, o.lecturer_id,
  c.id as course_id, c.course_code, c.name as course_name,
  c.course_type, c.duration_minutes
from public.class_sessions cs
join public.class_sections s on s.id = cs.section_id
join public.course_offerings o on o.id = s.offering_id
join public.courses c on c.id = o.course_id;

revoke all on public.class_session_details from public, anon, authenticated;
grant select on public.class_session_details to authenticated, service_role;

comment on column public.intakes.max_group is 'Consecutive valid groups are 1 through this number.';
comment on table public.student_intakes is 'One group per student/intake membership; a student may belong to multiple intakes.';
comment on column public.courses.duration_minutes is 'Positive whole minutes; locked once any class sessions exist.';
comment on table public.class_sessions is 'Stores start time only. Use class_session_details for calculated ends_at.';
comment on table public.schedule_changes is 'Exactly one session FK. Future scheduling RPC must write audit history atomically.';

commit;

-- Optional verification after successful setup:
-- select * from public.class_session_details limit 10;
-- select tablename, rowsecurity from pg_tables where schemaname = 'public';
