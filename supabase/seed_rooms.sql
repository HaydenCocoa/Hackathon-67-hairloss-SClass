-- SMART CAMPUS -- sample Block B classrooms, Spine labs and auditorium
-- Run after schema.sql in Supabase Dashboard > SQL Editor as postgres.
-- Levels 04 through 09, rooms 01 through 10: 60 rooms in total.
-- Room 05 on every level has 100 seats; all other rooms have 50.
-- Room 10 on every level is inactive: 54 active rooms, 6 inactive rooms.
-- Adds LAB-04-01 through LAB-04-10 in Spine: 50 seats each, type lab.
-- LAB-04-10 is inactive.
-- Auditorium 2 in Spine has 500 seats and is active, type auditorium.
-- Combined total: 71 rooms, 64 active, 7 inactive.
-- Rerunning refreshes these rooms' sample values and preserves their UUIDs.

begin;

insert into public.rooms (name, building, capacity, room_type, is_active)
select
  'B-' || lpad(level.floor_number::text, 2, '0')
       || '-' || lpad(room.room_number::text, 2, '0') as name,
  'Block B' as building,
  case when room.room_number = 5 then 100 else 50 end as capacity,
  'classroom' as room_type,
  room.room_number <> 10 as is_active
from generate_series(4, 9) as level(floor_number)
cross join generate_series(1, 10) as room(room_number)
where true
on conflict (name) do update
set
  building = excluded.building,
  capacity = excluded.capacity,
  room_type = excluded.room_type,
  is_active = excluded.is_active;

insert into public.rooms (name, building, capacity, room_type, is_active)
select
  'LAB-04-' || lpad(lab.room_number::text, 2, '0'),
  'Spine',
  50,
  'lab',
  lab.room_number <> 10
from generate_series(1, 10) as lab(room_number)
where true
on conflict (name) do update
set
  building = excluded.building,
  capacity = excluded.capacity,
  room_type = excluded.room_type,
  is_active = excluded.is_active;

insert into public.rooms (name, building, capacity, room_type, is_active)
values ('Auditorium 2', 'Spine', 500, 'auditorium', true)
on conflict (name) do update
set
  building = excluded.building,
  capacity = excluded.capacity,
  room_type = excluded.room_type,
  is_active = excluded.is_active;

commit;

-- Verify: each of the six levels should show 10 rooms, 9 active, 1 inactive,
-- 9 rooms with 50 seats, and 1 room with 100 seats.
-- Spine LAB-04 should show 10 labs, 9 active, 1 inactive, all with 50 seats.
-- Auditorium 2 should show 1 active auditorium with 500 seats.
select
  building,
  room_type,
  case when room_type = 'auditorium' then name
       else split_part(name, '-', 1) || '-' || split_part(name, '-', 2)
  end as level,
  count(*) as total_rooms,
  count(*) filter (where is_active) as active_rooms,
  count(*) filter (where not is_active) as inactive_rooms,
  count(*) filter (where capacity = 50) as rooms_with_50_seats,
  count(*) filter (where capacity = 100) as rooms_with_100_seats,
  count(*) filter (where capacity = 500) as rooms_with_500_seats
from public.rooms
where (name ~ '^B-0[4-9]-(0[1-9]|10)$' and building = 'Block B')
   or (name ~ '^LAB-04-(0[1-9]|10)$' and building = 'Spine')
   or (name = 'Auditorium 2' and building = 'Spine')
group by building, room_type, level
order by building, level;
