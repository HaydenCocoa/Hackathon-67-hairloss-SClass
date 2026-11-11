-- Run the whole patch as postgres in Supabase SQL Editor.
-- Removes the column and its known view/trigger dependencies, preserving data.
-- No CASCADE: unexpected dependencies stop and roll back this patch.
-- The Step 2 migration and backend weekly reader support the removed column.
-- The legacy course seed still needs adaptation before reuse after this patch.
begin;

do $$
declare view_name text; view_sql text; routine regprocedure; routine_sql text;
begin
  foreach view_name in array array['class_session_details', 'teaching_occurrence_details'] loop
    if to_regclass(format('public.%I', view_name)) is not null then
      view_sql := pg_get_viewdef(to_regclass(format('public.%I', view_name)), true);
      view_sql := regexp_replace(view_sql, '\ms\.required_room_type\s*,\s*', '', 'g');
      if view_sql ~ '\mrequired_room_type\M' then
        raise exception 'Unexpected room-type dependency in view %; patch rolled back', view_name;
      end if;
      execute format('drop view public.%I', view_name);
      execute format('create view public.%I with (security_invoker = true) as %s', view_name, view_sql);
      execute format('revoke all on public.%I from public, anon, authenticated', view_name);
      execute format('grant select on public.%I to authenticated, service_role', view_name);
    end if;
  end loop;

  routine := to_regprocedure('campus_private.protect_planned_teaching_metadata()');
  if routine is not null then
    routine_sql := pg_get_functiondef(routine);
    routine_sql := replace(replace(routine_sql, ', new.required_room_type', ''), ', old.required_room_type', '');
    if routine_sql ~ '\mrequired_room_type\M' then
      raise exception 'Unexpected room-type dependency in teaching-plan trigger; patch rolled back';
    end if;
    execute routine_sql;
  end if;
end;
$$;

alter table public.class_sections drop column if exists required_room_type;

commit;
