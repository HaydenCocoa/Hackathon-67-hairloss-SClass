# Admin portal setup

The Admin portal is available at `/#/admin`. It provides intake CRUD and a read-only
university timetable viewer. It does not generate or edit schedules.

## Administrator access

The admin page does not provide a separate login screen. It reuses the authenticated
Supabase session created by the application's shared login flow. With the default
Supabase JavaScript client storage, the frontend reads the access token from the
`*-auth-token` browser storage entry and sends it to FastAPI as a bearer token.

A signed-in user must also have a matching row in `public.admins` whose `auth_user_id`
equals the Supabase Auth user's UUID. Register the user through the SQL Editor if needed:

```sql
insert into public.admins (auth_user_id, full_name)
values ('AUTH-USER-UUID', 'Administrator Name');
```

The backend verifies the Supabase token and administrator membership for every admin
API request. Do not expose `SUPABASE_KEY` in Vue, a `VITE_` variable, or browser storage.

## API routes

All admin routes require `Authorization: Bearer <Supabase access token>` and verify
membership in `public.admins`.

- `GET /api/admin/intakes` — list intake records.
- `POST /api/admin/intakes` — create an intake.
- `PATCH /api/admin/intakes/{id}` — update an intake.
- `DELETE /api/admin/intakes/{id}` — delete an intake, subject to database foreign keys.
- `GET /api/admin/timetable?start=...&end=...&intake_id=...` — read class sessions from
  `public.class_session_details`, with room, lecturer and intake details.

## Timetable behaviour

The timetable viewer reads existing `class_sessions` through the
`class_session_details` view. It does not create, reschedule, or delete class sessions.
An empty timetable is expected until the scheduling algorithm writes generated sessions
to the existing database tables. Date ranges are limited to 31 days.

## Run

Start FastAPI and Vite using the existing project instructions. Open `http://127.0.0.1:5173/#/admin`.
The Supabase schema must already be applied and `.env` must contain `SUPABASE_URL` and
a server-only `SUPABASE_KEY`.

## Local dev bypass (temporary)

Until the shared login exists, set `ADMIN_DEV_BYPASS=1` in `.env` and restart FastAPI. The admin
API then skips the token + `public.admins` check **only** when `Config/config.json` has
`"environment": "development"` and the request comes from localhost. The backend uses its
server-side `SUPABASE_KEY` for data access. Delete the variable once real login is wired in.
