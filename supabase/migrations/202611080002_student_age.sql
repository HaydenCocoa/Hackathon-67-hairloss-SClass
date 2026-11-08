-- Add integer age to an existing students table. Run as postgres in SQL Editor.
-- Existing students retain their records; unknown ages remain NULL.
-- Can be rerun. If an incompatible age column already exists, stop and roll back.

begin;

alter table public.students add column if not exists age integer;

do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'students'
      and column_name = 'age' and data_type = 'integer'
  ) then
    raise exception 'students.age must have type integer';
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.students'::regclass
      and conname = 'students_age_nonnegative'
  ) then
    alter table public.students
      add constraint students_age_nonnegative check (age >= 0);
  end if;
end;
$$;

comment on column public.students.age is
  'Age in whole years; NULL when unknown. Sample students use ages 18 through 25.';

commit;
