-- Step 10 save audit: record who saved each class.
--
-- class_sessions.created_by holds the Supabase Auth user who saved the class.
-- When it is set, an AFTER INSERT trigger adds a schedule_changes row with
-- action 'create' in the SAME statement, so the classes and their audit rows are
-- saved together or not at all. Rows inserted without created_by (dashboard,
-- seed scripts) are not refused and get no audit row.
--
-- Audit rows keep class_sessions.class_session_id as a plain foreign key, so an
-- audited class cannot be deleted (cancel it instead). Occurrence-linked
-- classes could not be deleted before this migration either.
--
-- Requires 202611100001_teaching_requirements.sql (occurrence_id). Safe to run
-- more than once. Changes no existing rows.

begin;

do $$
begin
  if to_regclass('public.teaching_occurrences') is null then
    raise exception 'Apply 202611100001_teaching_requirements.sql before this migration';
  end if;
end;
$$;

-- 1. Allow 'create' in schedule_changes.action (replace the check, whatever it was named).
do $$
declare c record;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.schedule_changes'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%action%'
  loop
    execute format('alter table public.schedule_changes drop constraint %I', c.conname);
  end loop;
end;
$$;

alter table public.schedule_changes
  add constraint schedule_changes_action_check
    check (action in ('create', 'cancel', 'reschedule'));

-- 2. Who saved a class (NULL for rows created outside the app's save).
alter table public.class_sessions
  add column if not exists created_by uuid references auth.users(id);

comment on column public.class_sessions.created_by is
  'Supabase Auth user who saved this class from a timetable preview; NULL when inserted elsewhere.';

-- 3. Audit row in the same statement as the insert.
create or replace function campus_private.audit_class_session_create()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.created_by is not null then
    insert into public.schedule_changes (class_session_id, changed_by, action, old_values, new_values)
    values (new.id, new.created_by, 'create', '{}'::jsonb, jsonb_build_object(
      'occurrence_id', new.occurrence_id, 'section_id', new.section_id,
      'room_id', new.room_id, 'starts_at', new.starts_at, 'status', new.status));
  end if;
  return null; -- AFTER trigger
end;
$$;

revoke all on function campus_private.audit_class_session_create() from public, anon, authenticated;

drop trigger if exists audit_class_session_create on public.class_sessions;
create trigger audit_class_session_create after insert on public.class_sessions
for each row execute function campus_private.audit_class_session_create();

comment on table public.schedule_changes is
  'Exactly one session FK. action create = saved from a timetable preview (written by trigger); cancel/reschedule = later changes.';

commit;

-- Ask the Supabase API to see the new column straight away.
notify pgrst, 'reload schema';
