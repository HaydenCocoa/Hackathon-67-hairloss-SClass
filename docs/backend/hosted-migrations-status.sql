-- Read-only: shows which scheduling migrations a database already has.
-- Run in the Supabase SQL Editor. Changes nothing.
select
  to_regclass('public.teaching_occurrences') is not null as "202611100001 teaching requirements (prerequisite)",
  exists (select 1 from information_schema.columns
          where table_schema = 'public' and table_name = 'class_sessions' and column_name = 'removed_at')
    as "202611110001 admin timetable",
  not exists (select 1 from information_schema.columns
              where table_schema = 'public' and table_name = 'class_sections' and column_name = 'required_room_type')
    as "202611100002 room type removed",
  exists (select 1 from pg_constraint
          where conrelid = 'public.class_sessions'::regclass and contype = 'c'
            and pg_get_constraintdef(oid) ilike '%rescheduled%')
  and exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
              where n.nspname = 'campus_private' and p.proname = 'validate_occurrence_booking'
                and p.prosrc like '%rescheduled%')
    as "202611120001 rescheduled status",
  exists (select 1 from information_schema.columns
          where table_schema = 'public' and table_name = 'class_sessions' and column_name = 'created_by')
    as "202611120002 save audit",
  exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
          where n.nspname = 'public' and p.proname = 'admin_reschedule_class' and p.prosrc like '%course_kind%')
    as "202611120003 admin reschedule fixes";
