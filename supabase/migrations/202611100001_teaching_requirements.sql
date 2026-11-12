-- Step 2: weekly teaching demand, not timetable generation or booking validation.
-- Apply once after schema.sql (or the membership/age upgrades) as postgres.
-- Compatible with class_sections both before and after removal of required_room_type.
begin;

create table public.teaching_plans (
  id uuid primary key default gen_random_uuid(),
  section_id uuid not null references public.class_sections(id),
  first_week_start date not null check (extract(isodow from first_week_start) = 1),
  week_count integer not null check (week_count > 0),
  occurrences_per_week integer not null default 1 check (occurrences_per_week > 0),
  timezone text not null default 'Asia/Kuala_Lumpur',
  unique (id, section_id),
  unique (section_id, first_week_start)
);

create table public.teaching_occurrences (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null,
  section_id uuid not null,
  original_week_start date not null check (extract(isodow from original_week_start) = 1),
  target_week_start date not null check (extract(isodow from target_week_start) = 1),
  occurrence_number integer not null check (occurrence_number > 0),
  requirement_status text not null default 'required'
    check (requirement_status in ('required', 'cancelled')),
  foreign key (plan_id, section_id) references public.teaching_plans(id, section_id),
  unique (plan_id, original_week_start, occurrence_number),
  unique (id, section_id)
);
create index teaching_occurrences_target_idx on public.teaching_occurrences(target_week_start, id);

-- Existing bookings stay intact and unlinked; their teaching demand cannot be guessed.
alter table public.class_sessions add column occurrence_id uuid;
alter table public.class_sessions add constraint class_session_occurrence_unique unique (occurrence_id);
alter table public.class_sessions add constraint class_session_occurrence_section_fk
  foreign key (occurrence_id, section_id) references public.teaching_occurrences(id, section_id);

create trigger campus_integrity_lock before insert or update or delete on public.teaching_plans
for each statement execute function campus_private.lock_integrity_changes();
create trigger campus_integrity_lock before insert or update or delete on public.teaching_occurrences
for each statement execute function campus_private.lock_integrity_changes();

create function campus_private.validate_teaching_plan()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from pg_catalog.pg_timezone_names where name = new.timezone) then
    raise exception 'Unknown teaching-plan timezone' using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' and row(new.id, new.section_id, new.first_week_start, new.week_count,
      new.occurrences_per_week, new.timezone) is distinct from
      row(old.id, old.section_id, old.first_week_start, old.week_count, old.occurrences_per_week, old.timezone)
     and exists (select 1 from public.teaching_occurrences where plan_id = old.id) then
    raise exception 'Teaching plan is fixed after occurrences exist; create a new non-overlapping period';
  end if;
  if exists (select 1 from public.teaching_plans p where p.section_id = new.section_id
      and p.id <> new.id
      and new.first_week_start < p.first_week_start + p.week_count * 7
      and p.first_week_start < new.first_week_start + new.week_count * 7) then
    raise exception 'Teaching periods for the same section must not overlap' using errcode = '23514';
  end if;
  return new;
end;
$$;
create trigger validate_teaching_plan before insert or update on public.teaching_plans
for each row execute function campus_private.validate_teaching_plan();

create function campus_private.validate_teaching_occurrence()
returns trigger language plpgsql security definer set search_path = '' as $$
declare p public.teaching_plans;
begin
  if tg_op = 'DELETE' then
    raise exception 'Cancel a teaching occurrence instead of deleting its identity';
  end if;
  if tg_op = 'UPDATE' and row(new.id, new.plan_id, new.section_id, new.original_week_start, new.occurrence_number)
      is distinct from row(old.id, old.plan_id, old.section_id, old.original_week_start, old.occurrence_number) then
    raise exception 'Teaching occurrence identity and original requirement are immutable';
  end if;
  select * into p from public.teaching_plans where id = new.plan_id;
  if not found then
    raise exception 'Teaching plan does not exist' using errcode = '23503';
  end if;
  if new.section_id <> p.section_id or new.original_week_start < p.first_week_start
     or new.original_week_start >= p.first_week_start + p.week_count * 7
     or new.occurrence_number > p.occurrences_per_week then
    raise exception 'Occurrence does not match its teaching plan' using errcode = '23514';
  end if;
  if exists (select 1 from public.class_sessions cs where cs.occurrence_id = new.id and cs.status = 'scheduled'
      and (new.requirement_status = 'cancelled'
        or new.target_week_start <> date_trunc('week', cs.starts_at at time zone p.timezone)::date)) then
    raise exception 'Update the linked booking before changing its occurrence state or target week';
  end if;
  return new;
end;
$$;
create trigger validate_teaching_occurrence before insert or update or delete on public.teaching_occurrences
for each row execute function campus_private.validate_teaching_occurrence();

create function public.materialize_teaching_plan(p_plan_id uuid)
returns integer language plpgsql security invoker set search_path = '' as $$
declare p public.teaching_plans; inserted_count integer;
begin
  if current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'Teaching demand writes require READ COMMITTED isolation';
  end if;
  perform pg_advisory_xact_lock(7280001008::bigint);
  select * into p from public.teaching_plans where id = p_plan_id;
  if not found then
    raise exception 'Teaching plan does not exist' using errcode = '23503';
  end if;
  insert into public.teaching_occurrences(plan_id, section_id, original_week_start, target_week_start, occurrence_number)
    select p.id, p.section_id, p.first_week_start + w * 7, p.first_week_start + w * 7, n
    from generate_series(0, p.week_count - 1) w
    cross join generate_series(1, p.occurrences_per_week) n
    on conflict (plan_id, original_week_start, occurrence_number) do nothing;
  get diagnostics inserted_count = row_count;
  return inserted_count;
end;
$$;

create function campus_private.expand_teaching_plan()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.materialize_teaching_plan(new.id);
  return new;
end;
$$;
create trigger expand_teaching_plan after insert on public.teaching_plans
for each row execute function campus_private.expand_teaching_plan();

create function campus_private.validate_occurrence_booking()
returns trigger language plpgsql security definer set search_path = '' as $$
declare demand_status text;
begin
  if tg_op = 'DELETE' then
    if old.occurrence_id is not null then
      raise exception 'Cancel a linked booking instead of deleting its occurrence history';
    end if;
    return old;
  end if;
  if tg_op = 'UPDATE' and old.occurrence_id is not null
     and new.occurrence_id is distinct from old.occurrence_id then
    raise exception 'Cannot detach or replace a linked teaching occurrence';
  end if;
  if new.occurrence_id is not null then
    select requirement_status into demand_status from public.teaching_occurrences where id = new.occurrence_id;
    if new.status = 'scheduled' and demand_status = 'cancelled' then
      raise exception 'Explicitly reopen the cancelled requirement before booking a replacement';
    end if;
  end if;
  return new;
end;
$$;
create trigger validate_occurrence_booking before insert or update or delete on public.class_sessions
for each row execute function campus_private.validate_occurrence_booking();

create function campus_private.sync_occurrence_booking()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.occurrence_id is not null then
    update public.teaching_occurrences o set
      requirement_status = case when new.status = 'cancelled' then 'cancelled' else 'required' end,
      target_week_start = case when new.status = 'scheduled'
        then date_trunc('week', new.starts_at at time zone p.timezone)::date else o.target_week_start end
    from public.teaching_plans p where o.id = new.occurrence_id and p.id = o.plan_id;
  end if;
  return new;
end;
$$;
create trigger sync_occurrence_booking after insert or update on public.class_sessions
for each row execute function campus_private.sync_occurrence_booking();

-- Preserve section, lecturer, course type, and duration throughout a fixed plan.
-- Room suitability is owned by backend policy, not section metadata.
create function campus_private.protect_planned_teaching_metadata()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_table_name = 'class_sections' then
    if row(new.offering_id, new.group_number) is distinct from
       row(old.offering_id, old.group_number)
       and exists (select 1 from public.teaching_plans where section_id = old.id) then
      raise exception 'Section teaching details are fixed while a teaching plan exists';
    end if;
  elsif tg_table_name = 'course_offerings' then
    if row(new.course_id, new.intake_id, new.lecturer_id) is distinct from row(old.course_id, old.intake_id, old.lecturer_id)
       and exists (select 1 from public.teaching_plans p join public.class_sections s on s.id = p.section_id
                   where s.offering_id = old.id) then
      raise exception 'Course and lecturer are fixed while a teaching plan exists';
    end if;
  elsif tg_table_name = 'courses' then
    if row(new.duration_minutes, new.course_type) is distinct from row(old.duration_minutes, old.course_type)
       and exists (select 1 from public.teaching_plans p join public.class_sections s on s.id = p.section_id
                   join public.course_offerings o on o.id = s.offering_id where o.course_id = old.id) then
      raise exception 'Course duration and type are fixed while a teaching plan exists';
    end if;
  end if;
  return new;
end;
$$;
create trigger protect_planned_teaching before update on public.class_sections
for each row execute function campus_private.protect_planned_teaching_metadata();
create trigger protect_planned_teaching before update on public.course_offerings
for each row execute function campus_private.protect_planned_teaching_metadata();
create trigger protect_planned_teaching before update on public.courses
for each row execute function campus_private.protect_planned_teaching_metadata();

alter table public.teaching_plans enable row level security;
alter table public.teaching_occurrences enable row level security;
revoke all on public.teaching_plans, public.teaching_occurrences from public, anon, authenticated;
grant select on public.teaching_plans, public.teaching_occurrences to authenticated;
grant all on public.teaching_plans, public.teaching_occurrences to service_role;
create policy teaching_plan_read on public.teaching_plans for select to authenticated
using (campus_private.can_read_section(section_id));
create policy teaching_occurrence_read on public.teaching_occurrences for select to authenticated
using (campus_private.can_read_section(section_id));

create view public.teaching_occurrence_details with (security_invoker = true) as
select t.id as occurrence_id, t.plan_id, t.section_id, t.original_week_start, t.target_week_start,
  ((t.original_week_start - p.first_week_start) / 7 + 1) as teaching_week_number,
  t.occurrence_number, t.requirement_status, p.timezone,
  cs.id as class_session_id, cs.status as booking_status, cs.starts_at, cs.room_id,
  (t.requirement_status = 'required' and (cs.id is null or cs.status = 'cancelled')) as needs_scheduling,
  s.group_number, o.intake_id, o.lecturer_id,
  c.id as course_id, c.course_code, c.name as course_name, c.course_type, c.duration_minutes
from public.teaching_occurrences t
join public.teaching_plans p on p.id = t.plan_id
join public.class_sections s on s.id = t.section_id
join public.course_offerings o on o.id = s.offering_id
join public.courses c on c.id = o.course_id
left join public.class_sessions cs on cs.occurrence_id = t.id;
revoke all on public.teaching_occurrence_details from public, anon, authenticated;
grant select on public.teaching_occurrence_details to authenticated, service_role;

revoke all on function public.materialize_teaching_plan(uuid) from public, anon, authenticated;
grant execute on function public.materialize_teaching_plan(uuid) to service_role;
revoke all on function campus_private.validate_teaching_plan(), campus_private.validate_teaching_occurrence(),
  campus_private.expand_teaching_plan(), campus_private.validate_occurrence_booking(),
  campus_private.sync_occurrence_booking(), campus_private.protect_planned_teaching_metadata()
  from public, anon, authenticated;

comment on table public.teaching_plans is 'Fixed weekly recurrence for one section over a Monday-anchored period; insertion materializes stable occurrences.';
comment on table public.teaching_occurrences is 'Teaching demand independent of time and room. Cancellation and movement preserve original identity.';
comment on column public.class_sessions.occurrence_id is 'Optional for legacy bookings; at most one persistent booking row per occurrence.';
commit;
