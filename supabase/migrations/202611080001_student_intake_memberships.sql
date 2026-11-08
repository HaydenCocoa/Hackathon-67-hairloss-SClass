-- Upgrade the PREVIOUS single-intake schema. Run ONCE as postgres.
-- For a new project use schema.sql instead; do not run both setup paths.
-- Preserves student IDs, linked accounts, meetings and other existing records.
-- Copies each student's previous intake/group into a membership before removing
-- the old columns. No CASCADE: unexpected dependencies abort the transaction.
begin;

do $$
begin
  if to_regclass('public.student_intakes') is not null then
    raise exception 'student_intakes already exists; this upgrade is not needed';
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema='public' and table_name='students' and column_name='intake_id')
     or not exists (select 1 from information_schema.columns
                    where table_schema='public' and table_name='students' and column_name='group_number') then
    raise exception 'Expected the previous single-intake schema; use schema.sql for a new project';
  end if;
end;
$$;

-- Pause relevant writes while memberships and policies are transferred.
select pg_advisory_xact_lock(7280001008::bigint);
lock table public.intakes, public.students, public.courses,
  public.course_offerings, public.class_sections, public.class_sessions
  in access exclusive mode;

create table public.student_intakes (
  student_id uuid not null references public.students(id),
  intake_id uuid not null references public.intakes(id),
  group_number integer not null default 1 check (group_number >= 1),
  primary key (student_id, intake_id)
);
create index student_intakes_intake_group_idx
  on public.student_intakes(intake_id, group_number);

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
create trigger campus_integrity_lock before insert or update or delete on public.student_intakes
for each statement execute function campus_private.lock_integrity_changes();
create trigger validate_student_intake_group before insert or update on public.student_intakes
for each row execute function campus_private.validate_student_intake_group();

insert into public.student_intakes(student_id, intake_id, group_number)
select id, intake_id, group_number from public.students;

do $$
begin
  if exists (
    select 1 from public.students st
    left join public.student_intakes membership
      on membership.student_id=st.id and membership.intake_id=st.intake_id
    where membership.student_id is null
       or membership.group_number is distinct from st.group_number
  ) then
    raise exception 'Membership backfill verification failed; upgrade rolled back';
  end if;
end;
$$;

create or replace function campus_private.validate_intake_limit()
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
create or replace function campus_private.can_read_section(section_uuid uuid)
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

alter table public.student_intakes enable row level security;
revoke all on table public.student_intakes from public, anon, authenticated;
grant select on table public.student_intakes to authenticated;
grant all on table public.student_intakes to service_role;
create policy own_or_admin_read on public.student_intakes for select to authenticated
  using ((select campus_private.is_admin())
    or exists (select 1 from public.students st
               where st.id = student_id and st.auth_user_id = (select auth.uid())));

revoke all on function campus_private.validate_student_intake_group()
  from public, anon, authenticated;

drop trigger validate_student_group on public.students;
drop trigger campus_integrity_lock on public.students;
drop function campus_private.validate_student_group();
drop index public.students_intake_group_idx;
alter table public.students drop column intake_id, drop column group_number;

comment on table public.student_intakes is
  'One group per student/intake membership; a student may belong to multiple intakes.';

commit;

-- Verify after successful upgrade:
-- select count(*) as students from public.students;
-- select count(*) as memberships from public.student_intakes;
