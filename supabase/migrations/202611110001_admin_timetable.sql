-- Apply to a development database after the existing schema and migrations.
-- Cancellation removal hides a session while retaining its history.
begin;

alter table public.class_sessions add column removed_at timestamptz;
alter table public.class_sessions add column removed_by uuid references auth.users(id);
alter table public.class_sessions add constraint removed_session_is_cancelled
  check ((removed_at is null and removed_by is null) or
         (removed_at is not null and removed_by is not null and status = 'cancelled'));

create or replace view public.class_session_details with (security_invoker = true) as
select cs.id, cs.section_id, cs.room_id, cs.starts_at,
  cs.starts_at + c.duration_minutes * interval '1 minute' as ends_at,
  cs.status, s.group_number, s.required_room_type,
  o.id as offering_id, o.intake_id, o.lecturer_id,
  c.id as course_id, c.course_code, c.name as course_name,
  c.course_type, c.duration_minutes
from public.class_sessions cs
join public.class_sections s on s.id = cs.section_id
join public.course_offerings o on o.id = s.offering_id
join public.courses c on c.id = o.course_id
where cs.removed_at is null;

-- Share the existing configuration lock for meeting changes as well.
create trigger campus_integrity_lock before insert or update or delete on public.meeting_sessions
for each statement execute function campus_private.lock_integrity_changes();
create trigger campus_integrity_lock before insert or update or delete on public.meeting_students
for each statement execute function campus_private.lock_integrity_changes();
create trigger campus_integrity_lock before insert or update or delete on public.rooms
for each statement execute function campus_private.lock_integrity_changes();

create function public.admin_reschedule_class(
  session_id uuid, expected_start timestamptz, expected_room uuid,
  new_start timestamptz, new_room uuid, change_reason text
) returns void language plpgsql security definer set search_path = '' as $$
declare
  current_session public.class_sessions%rowtype;
  course_duration integer;
  group_intake uuid;
  target_group integer;
  teacher uuid;
  room_requirement text;
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
  if current_session.status <> 'scheduled' then
    raise exception 'Only scheduled classes can be rescheduled' using errcode = '22023';
  end if;
  if current_session.starts_at is distinct from expected_start or current_session.room_id is distinct from expected_room then
    raise exception 'Class changed since it was loaded. Refresh and try again' using errcode = '40001';
  end if;
  select c.duration_minutes, o.intake_id, s.group_number, o.lecturer_id, s.required_room_type
    into course_duration, group_intake, target_group, teacher, room_requirement
  from public.class_sections s join public.course_offerings o on o.id = s.offering_id
  join public.courses c on c.id = o.course_id where s.id = current_session.section_id;
  new_end := new_start + course_duration * interval '1 minute';
  select count(*) into student_count from public.student_intakes si
    where si.intake_id = group_intake and si.group_number = target_group;
  if not exists (select 1 from public.rooms r where r.id = new_room and r.is_active
                 and r.room_type = room_requirement and r.capacity >= student_count) then
    raise exception 'Room is unavailable, unsuitable or too small' using errcode = '22023';
  end if;
  if exists (
    select 1 from public.class_sessions cs
    join public.class_sections s on s.id = cs.section_id
    join public.course_offerings o on o.id = s.offering_id
    join public.courses c on c.id = o.course_id
    where cs.id <> session_id and cs.status = 'scheduled'
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
  update public.class_sessions set starts_at = new_start, room_id = new_room where id = session_id;
  insert into public.schedule_changes(class_session_id, changed_by, action, reason, old_values, new_values)
  values (session_id, auth.uid(), 'reschedule', btrim(change_reason),
    jsonb_build_object('starts_at', current_session.starts_at, 'room_id', current_session.room_id),
    jsonb_build_object('starts_at', new_start, 'room_id', new_room));
end;
$$;

create function public.admin_remove_cancelled_class(session_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.admins where auth_user_id = auth.uid()) then
    raise exception 'Administrator access required' using errcode = '42501';
  end if;
  update public.class_sessions set removed_at = now(), removed_by = auth.uid()
  where id = session_id and status = 'cancelled' and removed_at is null;
  if not found then
    raise exception 'Cancelled class not found or already removed' using errcode = 'P0002';
  end if;
end;
$$;
revoke all on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) from public, anon;
revoke all on function public.admin_remove_cancelled_class(uuid) from public, anon;
grant execute on function public.admin_reschedule_class(uuid, timestamptz, uuid, timestamptz, uuid, text) to authenticated;
grant execute on function public.admin_remove_cancelled_class(uuid) to authenticated;
commit;
