-- SMART CAMPUS -- 20 fictional sample lecturers
-- Run after schema.sql in Supabase Dashboard > SQL Editor as postgres.
-- Codes: LEC001 through LEC020. Each lecturer has a different common name.
-- Login accounts are not created; auth_user_id is initially NULL for new rows.
-- Rerunning refreshes names, preserving existing UUIDs and linked login accounts.

begin;

insert into public.lecturers (lecturer_code, full_name)
values
  ('LEC001', 'Ahmad Hakim'),
  ('LEC002', 'Siti Aisyah'),
  ('LEC003', 'Muhammad Farhan'),
  ('LEC004', 'Nur Farah'),
  ('LEC005', 'Amir Hassan'),
  ('LEC006', 'Aina Zainal'),
  ('LEC007', 'Daniel Tan'),
  ('LEC008', 'Michelle Lim'),
  ('LEC009', 'Jason Lee'),
  ('LEC010', 'Rachel Wong'),
  ('LEC011', 'Kevin Chen'),
  ('LEC012', 'Emily Teoh'),
  ('LEC013', 'David Ng'),
  ('LEC014', 'Sarah Goh'),
  ('LEC015', 'Arun Kumar'),
  ('LEC016', 'Priya Nair'),
  ('LEC017', 'Ravi Raj'),
  ('LEC018', 'Divya Menon'),
  ('LEC019', 'Adam Wilson'),
  ('LEC020', 'Emma Thomas')
on conflict (lecturer_code) do update
set full_name = excluded.full_name;

commit;

-- Verify: returns the 20 sample lecturers in code order.
select lecturer_code, full_name, auth_user_id
from public.lecturers
where lecturer_code ~ '^LEC(00[1-9]|01[0-9]|020)$'
order by lecturer_code;
