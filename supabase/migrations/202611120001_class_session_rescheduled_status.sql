-- Add 'rescheduled' to class_sessions.status.
--
-- Meaning: an ACTIVE booking that a lecturer or admin has moved. It occupies its
-- room, lecturer and students exactly like 'scheduled' and still needs a room.
-- Only 'cancelled' releases the slot. meeting_sessions.status is unchanged.
--
-- Requires 202611100001_teaching_requirements.sql (the occurrence triggers below
-- replace functions created there). Safe to run more than once. Changes no rows.

begin;

do $$
begin
  if to_regclass('public.teaching_occurrences') is null then
    raise exception 'Apply 202611100001_teaching_requirements.sql before this migration';
  end if;
end;
$$;

-- 1. Replace every status-related CHECK on class_sessions, whatever it was named.
do $$
declare c record;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.class_sessions'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%status%'
  loop
    execute format('alter table public.class_sessions drop constraint %I', c.conname);
  end loop;
end;
$$;

alter table public.class_sessions
  add constraint class_sessions_status_check
    check (status in ('scheduled', 'rescheduled', 'cancelled')),
  add constraint scheduled_class_requires_room
    check (status not in ('scheduled', 'rescheduled') or room_id is not null);

-- 2. Room/time lookups cover every active booking.
drop index if exists public.class_sessions_room_time_idx;
create index class_sessions_room_time_idx on public.class_sessions(room_id, starts_at)
  where status in ('scheduled', 'rescheduled');

-- 3. Occurrence triggers treat 'rescheduled' as an active booking.
create or replace function campus_private.validate_teaching_occurrence()
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
  if exists (select 1 from public.class_sessions cs where cs.occurrence_id = new.id
      and cs.status in ('scheduled', 'rescheduled')
      and (new.requirement_status = 'cancelled'
        or new.target_week_start <> date_trunc('week', cs.starts_at at time zone p.timezone)::date)) then
    raise exception 'Update the linked booking before changing its occurrence state or target week';
  end if;
  return new;
end;
$$;

create or replace function campus_private.validate_occurrence_booking()
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
    if new.status in ('scheduled', 'rescheduled') and demand_status = 'cancelled' then
      raise exception 'Explicitly reopen the cancelled requirement before booking a replacement';
    end if;
  end if;
  return new;
end;
$$;

create or replace function campus_private.sync_occurrence_booking()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.occurrence_id is not null then
    update public.teaching_occurrences o set
      requirement_status = case when new.status = 'cancelled' then 'cancelled' else 'required' end,
      target_week_start = case when new.status in ('scheduled', 'rescheduled')
        then date_trunc('week', new.starts_at at time zone p.timezone)::date else o.target_week_start end
    from public.teaching_plans p where o.id = new.occurrence_id and p.id = o.plan_id;
  end if;
  return new;
end;
$$;

revoke all on function campus_private.validate_teaching_occurrence() from public, anon, authenticated;
revoke all on function campus_private.validate_occurrence_booking() from public, anon, authenticated;
revoke all on function campus_private.sync_occurrence_booking() from public, anon, authenticated;

commit;
