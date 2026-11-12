-- Step 4: one read-only snapshot for the trusted scheduling backend.
-- Apply once after 202611100001_teaching_requirements.sql as postgres.
-- Compatible with the optional 202611100002 room-requirement removal patch.
begin;

create function public.load_scheduling_data(p_week_start date, p_timezone text)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare result jsonb;
begin
  if p_week_start is null or extract(isodow from p_week_start) <> 1 then
    raise exception 'week_start must be a Monday' using errcode = '22023';
  end if;
  if p_timezone is null or not exists (select 1 from pg_catalog.pg_timezone_names where name = p_timezone) then
    raise exception 'Unknown scheduling timezone' using errcode = '22023';
  end if;

  with horizon as (
    select p_week_start::timestamp at time zone p_timezone as starts_at,
           (p_week_start + 7)::timestamp at time zone p_timezone as ends_at
  ), requirements as (
    select * from public.teaching_occurrence_details where target_week_start = p_week_start
  ), classes as (
    select d.id, cs.occurrence_id, d.section_id, d.intake_id, d.group_number,
           d.lecturer_id, d.room_id, d.starts_at, d.ends_at, d.duration_minutes, d.status
    from public.class_session_details d
    join public.class_sessions cs on cs.id = d.id
    cross join horizon h
    where d.status = 'scheduled' and d.starts_at < h.ends_at and d.ends_at > h.starts_at
  ), meetings as (
    select m.id, m.lecturer_id, m.room_id, m.starts_at, m.ends_at, m.status,
      coalesce((select jsonb_agg(ms.student_id order by ms.student_id)
                from public.meeting_students ms where ms.meeting_id = m.id), '[]'::jsonb) as student_ids
    from public.meeting_sessions m cross join horizon h
    where m.status = 'scheduled' and m.starts_at < h.ends_at and m.ends_at > h.starts_at
  ), relevant_sections as (
    select section_id from requirements union select section_id from classes
  ), rosters as (
    select s.id as section_id, o.intake_id, s.group_number,
      coalesce(jsonb_agg(distinct membership.student_id order by membership.student_id)
               filter (where membership.student_id is not null), '[]'::jsonb) as student_ids
    from relevant_sections relevant
    join public.class_sections s on s.id = relevant.section_id
    join public.course_offerings o on o.id = s.offering_id
    left join public.student_intakes membership
      on membership.intake_id = o.intake_id and membership.group_number = s.group_number
    group by s.id, o.intake_id, s.group_number
  ), relevant_lecturers as (
    select lecturer_id from requirements union select lecturer_id from classes union select lecturer_id from meetings
  )
  select jsonb_build_object(
    'schema_version', 1,
    'week_start', p_week_start,
    'timezone', p_timezone,
    'horizon_starts_at', h.starts_at,
    'horizon_ends_at', h.ends_at,
    'captured_at', transaction_timestamp(),
    'database_snapshot', pg_current_snapshot()::text,
    'requirements', coalesce((select jsonb_agg(to_jsonb(r) order by r.occurrence_id) from requirements r), '[]'::jsonb),
    'rosters', coalesce((select jsonb_agg(to_jsonb(r) order by r.section_id) from rosters r), '[]'::jsonb),
    'rooms', coalesce((select jsonb_agg(jsonb_build_object('id', r.id, 'name', r.name, 'building', r.building,
                 'capacity', r.capacity, 'room_type', r.room_type, 'is_active', r.is_active) order by r.id)
                 from public.rooms r), '[]'::jsonb),
    'lecturers', coalesce((select jsonb_agg(jsonb_build_object('id', l.id) order by l.id)
                   from public.lecturers l join relevant_lecturers needed on needed.lecturer_id = l.id), '[]'::jsonb),
    'class_bookings', coalesce((select jsonb_agg(to_jsonb(c) order by c.id) from classes c), '[]'::jsonb),
    'meeting_bookings', coalesce((select jsonb_agg(to_jsonb(m) order by m.id) from meetings m), '[]'::jsonb)
  ) into result from horizon h;
  return result;
end;
$$;

revoke all on function public.load_scheduling_data(date, text) from public, anon, authenticated;
grant execute on function public.load_scheduling_data(date, text) to service_role;
comment on function public.load_scheduling_data(date, text) is
  'Read-only complete weekly scheduling input under one MVCC snapshot. Trusted server only; no bookings or plan expansion.';
notify pgrst, 'reload schema';
commit;
