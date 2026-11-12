-- Bring public.admin_reschedule_class (202611110001) in line with later changes.
--
-- 1. 'rescheduled' (202611120001) is an active booking: such a class can be
--    moved again, it blocks other moves, and a moved class becomes 'rescheduled'
--    (the same as the lecturer endpoint).
-- 2. Room suitability no longer reads class_sections.required_room_type, which
--    202611100002 removes (the old function failed with "column does not
--    exist" after that patch). It uses the course type and the room policy in
--    Config/config.json: scheduling.room_compatibility and reserved_room_types.
--    Keep this function and that file in step.
--
-- Not covered here (still open for step 11): opening hours and the 15-minute gap.
-- Requires 202611110001 and 202611120001. Safe to run more than once. Changes no rows.

begin;

do $$
begin
  if to_regprocedure('public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text)') is null then
    raise exception 'Apply 202611110001_admin_timetable.sql before this migration';
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.class_sessions'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%rescheduled%'
  ) then
    raise exception 'Apply 202611120001_class_session_rescheduled_status.sql before this migration';
  end if;
end;
$$;

create or replace function public.admin_reschedule_class(
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
  if not exists (select 1 from public.admins where auth_user_id = auth.uid()) then
    raise exception 'Administrator access required' using errcode = '42501';
  end if;
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

revoke all on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) from public, anon;
grant execute on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) to authenticated;

commit;
