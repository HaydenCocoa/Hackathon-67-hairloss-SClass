-- Removes ALL student records, intake memberships, and meeting attendance.
-- Run the entire file as postgres in Supabase Dashboard > SQL Editor.
-- Keeps login accounts in auth.users and all shared campus/schedule records.
-- Existing login links disappear with the deleted student records.
-- Deletes children first to satisfy foreign keys. No CASCADE is used.

begin;

delete from public.meeting_students;
delete from public.student_intakes;
delete from public.students;

commit;
