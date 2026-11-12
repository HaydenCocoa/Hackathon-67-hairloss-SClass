-- Lecturer rescheduling in one database transaction under the timetable lock.
--
-- Before: PATCH /api/lecturers/{id}/sessions/{id} checked clashes in the backend, then
-- updated class_sessions and inserted the schedule_changes row as two separate requests
-- with the server key, guarded only by a per-process asyncio lock. Two backend instances
-- (Vercel), a timetable save or an admin move could interleave and double-book, and a
-- failed history insert left the class moved without a record (lecturer review, finding 4).
--
-- After:
-- 1. campus_private.move_class_session holds the move that public.admin_reschedule_class
--    already did (202611120003), unchanged: advisory lock 7280001008, expected start/room
--    check, room suitability and capacity, the auditorium rule, clash re-check, status
--    'rescheduled', and the schedule_changes row, all in one transaction.
-- 2. public.admin_reschedule_class keeps its signature and admin check and now calls it.
-- 3. New public.lecturer_reschedule_class: the same move, allowed only for the lecturer who
--    teaches the class (lecturers.auth_user_id = auth.uid()). changed_by is that lecturer.
--
-- Still not checked here (same as the admin function): opening hours and the 15-minute gap.
-- The backend checks them with the scheduling engine just before calling these functions.
-- Requires 202611110001, 202611120001 and 202611120003. Safe to run more than once. Changes no rows.

begin;

do $$
begin
  if to_regprocedure('public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text)') is null then
    raise exception 'Apply 202611110001_admin_timetable.sql before this migration';
  end if;
  if pg_get_functiondef('public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text)'::regprocedure)
       not ilike '%allowed_types%'
     and to_regprocedure('campus_private.move_class_session(uuid, timestamptz, uuid, timestamptz, uuid, text)') is null then
    raise exception 'Apply 202611120003_admin_reschedule_fixes.sql before this migration';
  end if;
end;
$$;

create or replace function campus_private.move_class_session(
  session_id uuid, expected_start timestamptz, expected_room uuid,
  new_start timestamptz, new_room uuid, change_reason text
) returns void language plpgsql security definer set search_path = '' as $$
declare
  current_session public.class_sessions%rowtype;
  chosen public.rooms%rowtype;
  course_duration integer;
  course_kind text;
  allowed_types text[];
  group_intake uuid;
  target_group integer;
  teacher uuid;
  student_count integer;
  new_end timestamptz;
begin
  if new_start is null or new_room is null or nullif(btrim(change_reason), '') is null then
    raise exception 'Start, room and reason are required' using errcode = '22023';
  end if;
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'READ COMMITTED isolation is required';
  end if;
  perform pg_advisory_xact_lock(7280001008::bigint);
  select * into current_session from public.class_sessions where id = session_id for update;
  if not found or current_session.removed_at is not null then
    raise exception 'Class not found' using errcode = 'P0002';
  end if;
  if current_session.status not in ('scheduled', 'rescheduled') then
    raise exception 'Only scheduled classes can be rescheduled' using errcode = '22023';
  end if;
  if current_session.starts_at is distinct from expected_start or current_session.room_id is distinct from expected_room then
    raise exception 'Class changed since it was loaded. Refresh and try again' using errcode = '40001';
  end if;

  select c.duration_minutes, c.course_type, o.intake_id, s.group_number, o.lecturer_id
    into course_duration, course_kind, group_intake, target_group, teacher
  from public.class_sections s join public.course_offerings o on o.id = s.offering_id
  join public.courses c on c.id = o.course_id where s.id = current_session.section_id;
  new_end := new_start + course_duration * interval '1 minute';
  select count(*) into student_count from public.student_intakes si
    where si.intake_id = group_intake and si.group_number = target_group;

  -- scheduling.room_compatibility in Config/config.json ('others' has no rooms).
  allowed_types := case course_kind
    when 'lecture' then array['classroom', 'auditorium']
    when 'tutorial' then array['classroom', 'lab']
    when 'lab' then array['classroom', 'lab']
    else array[]::text[] end;
  select * into chosen from public.rooms r where r.id = new_room;
  if not found or not chosen.is_active or not (chosen.room_type = any(allowed_types))
     or chosen.capacity < student_count then
    raise exception 'Room is unavailable, unsuitable or too small' using errcode = '22023';
  end if;
  -- scheduling.reserved_room_types: an auditorium only when no other permitted room seats the class.
  if chosen.room_type = 'auditorium' and exists (
    select 1 from public.rooms r
    where r.is_active and r.room_type = any(allowed_types) and r.room_type <> 'auditorium'
      and r.capacity >= student_count
  ) then
    raise exception 'Auditoriums are kept for classes no other permitted room can seat' using errcode = '22023';
  end if;

  if exists (
    select 1 from public.class_sessions cs
    join public.class_sections s on s.id = cs.section_id
    join public.course_offerings o on o.id = s.offering_id
    join public.courses c on c.id = o.course_id
    where cs.id <> session_id and cs.status in ('scheduled', 'rescheduled')
      and cs.starts_at < new_end and cs.starts_at + c.duration_minutes * interval '1 minute' > new_start
      and (cs.room_id = new_room or o.lecturer_id = teacher or exists (
        select 1 from public.student_intakes a join public.student_intakes b on a.student_id = b.student_id
        where a.intake_id = group_intake and a.group_number = target_group
          and b.intake_id = o.intake_id and b.group_number = s.group_number
      ) or (o.intake_id = group_intake and s.group_number = target_group))
  ) or exists (
    select 1 from public.meeting_sessions m
    where m.status = 'scheduled' and m.starts_at < new_end and m.ends_at > new_start
      and (m.room_id = new_room or m.lecturer_id = teacher or exists (
        select 1 from public.meeting_students ms join public.student_intakes si on si.student_id = ms.student_id
        where ms.meeting_id = m.id and si.intake_id = group_intake and si.group_number = target_group
      ))
  ) then
    raise exception 'The room, lecturer or students have another booking at this time' using errcode = '23P01';
  end if;

  update public.class_sessions set starts_at = new_start, room_id = new_room, status = 'rescheduled'
  where id = session_id;
  insert into public.schedule_changes(class_session_id, changed_by, action, reason, old_values, new_values)
  values (session_id, auth.uid(), 'reschedule', btrim(change_reason),
    jsonb_build_object('starts_at', current_session.starts_at, 'room_id', current_session.room_id,
                       'status', current_session.status),
    jsonb_build_object('starts_at', new_start, 'room_id', new_room, 'status', 'rescheduled'));
end;
$$;

-- Internal: callable only through the two checked public functions below.
revoke all on function campus_private.move_class_session(uuid, timestamptz, uuid, timestamptz, uuid, text)
  from public, anon, authenticated;

create or replace function public.admin_reschedule_class(
  session_id uuid, expected_start timestamptz, expected_room uuid,
  new_start timestamptz, new_room uuid, change_reason text
) returns void language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.admins where auth_user_id = auth.uid()) then
    raise exception 'Administrator access required' using errcode = '42501';
  end if;
  perform campus_private.move_class_session(session_id, expected_start, expected_room, new_start, new_room, change_reason);
end;
$$;

create or replace function public.lecturer_reschedule_class(
  session_id uuid, expected_start timestamptz, expected_room uuid,
  new_start timestamptz, new_room uuid, change_reason text
) returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or not exists (
    select 1 from public.class_sessions cs
    join public.class_sections s on s.id = cs.section_id
    join public.course_offerings o on o.id = s.offering_id
    join public.lecturers l on l.id = o.lecturer_id
    where cs.id = session_id and l.auth_user_id = auth.uid()
  ) then
    if not exists (select 1 from public.class_sessions cs where cs.id = session_id and cs.removed_at is null) then
      raise exception 'Class not found' using errcode = 'P0002';
    end if;
    raise exception 'Only the lecturer who teaches this class can reschedule it' using errcode = '42501';
  end if;
  perform campus_private.move_class_session(session_id, expected_start, expected_room, new_start, new_room, change_reason);
end;
$$;

revoke all on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) from public, anon;
grant execute on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) to authenticated;
revoke all on function public.lecturer_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) from public, anon;
grant execute on function public.lecturer_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) to authenticated;

commit;
