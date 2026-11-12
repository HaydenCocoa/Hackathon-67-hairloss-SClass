# Login and role-based access

Implemented and verified locally: 12 November 2026, branch `feature-login`. **Not run against the hosted Supabase project.**

Related: [backend record](agents.md), [scheduling preview](schedule-preview-api.md), [timetable saving](timetable-saving.md).

## Requirement

Everyone visiting the website must log in at `/login`. Roles are Admin, Student and Lecturer, using accounts stored in Supabase. Every page that needs a login redirects to `/login` when the visitor is not logged in.

## Accepted decisions (12 November 2026)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Login identifier | Email + password from Supabase Auth. |
| 2 | Accounts | Created and linked by the project owner in Supabase (see [Account setup](#account-setup)); the app never creates accounts. |
| 3 | Where login happens | In the backend; the session is kept in httpOnly cookies. No Supabase key or token reaches the browser. |
| 4 | Page addresses | `/login`, `/student`, `/lecturer`, `/admin`. Old `#/student`, `#/lecturer`, `#main` links redirect. |
| 5 | Account linked to several roles | admin > lecturer > student. |
| 6 | Main menu | Removed. `/admin` is an empty placeholder; the admin area is built by another team member. |
| 7 | Student and lecturer pages | Not changed. Only routing to them; the shell passes the logged-in student's code to the student page through its existing `studentCode` prop. |
| 8 | Sign-up and forgot password | Out of scope. Public sign-up should be disabled in Supabase. |
| 9 | Development pages | Moved under `/admin`, require an admin login, and keep the existing development-mode and localhost checks. |

## How it works

```
Browser ──POST /api/auth/login {email, password}──▶ FastAPI ──/auth/v1/token (password)──▶ Supabase Auth
                                                      │◀── access + refresh tokens, user id
                                                      ├─ role: admins → lecturers → students by auth_user_id
Browser ◀── Set-Cookie sclass_access, sclass_refresh (httpOnly, SameSite=Lax, Path=/) + {role, name, home}
Later requests: cookie → FastAPI asks Supabase /auth/v1/user (cached 60 s) → role → route check
```

- **Session check.** `get_session` verifies the access token with Supabase (`/auth/v1/user`), which works with both `sb_secret` and legacy keys and needs no extra library. Results are cached in memory for up to 60 seconds (never past the token's expiry), so a revoked session can stay usable for up to a minute.
- **Expiry.** When the access token has expired, the refresh token is used automatically and new cookies are set. If both fail, the cookies are cleared and the user is treated as logged out.
- **Unlinked accounts.** A valid Supabase account with no `admins`/`lecturers`/`students` row is refused (`ACCOUNT_NOT_LINKED`) and its Supabase session is revoked.
- **Cookies.** httpOnly (JavaScript cannot read them), `SameSite=Lax` (not sent on cross-site POSTs), `Secure` when served over HTTPS. Access cookie lifetime follows Supabase (`expires_in`); refresh cookie 7 days.
- **Redirects after login.** `?next=` is followed only for same-site page paths inside the user's own area (for example an admin returning to the scheduling page); anything else goes to the role's home page.

## Pages

| Path | Not logged in | Logged in |
| --- | --- | --- |
| `/` | → `/login` | → own home |
| `/login` | Login page | → `next` (if allowed) or own home |
| `/student` | → `/login?next=/student` | Students only; others → own home |
| `/lecturer` | → `/login?next=/lecturer` | Lecturers only; others → own home |
| `/admin` | → `/login?next=/admin` | Admins only; others → own home |
| `/admin/schedule` | → `/login?next=/admin/schedule` | Admins only; others → own home. Scheduling workspace opened from Admin > Timetable > Schedule Class (added 12 November 2026; placeholder for now) |
| `/admin/development/scheduling-test-hayden` | → `/login?next=…` | Admins only (plus development mode and localhost) |

The backend applies these rules when a page is loaded directly; the Vue app repeats them for the Vite dev server and in-app navigation. If any API call returns 401 later (session expired), the app sends the user to `/login` and back afterwards. A thin bar above each page shows the user's name, role and a **Log out** button.

## API access

| Endpoint | Access |
| --- | --- |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Public / logged in (`me` returns 401 when not logged in) |
| `GET /api/health`, `GET /api/config`, `/docs`, `/openapi.json` | Public |
| `GET /api/health/database`, `GET /api/rooms` | Any logged-in user |
| `GET /api/student/{code}`, `…/timetable` | Students: their own code only (403 otherwise); admins: any |
| `GET /api/lecturers` | Lecturers: only themselves; admins: all; students: 403 |
| `GET /api/lecturers/{id}/timetable` | Lecturers: their own id only; admins: any |
| `PATCH /api/lecturers/{id}/sessions/{sid}` | Lecturers: own id **and** the class must belong to that lecturer; admins: any lecturer's class |
| `POST /api/schedules/generate`, `POST /api/schedules/save`, scheduling page and assets | Admins only, plus development mode and localhost |
| `/api/admin/*` (admin page) | Admins only: the login session, or a pasted Supabase token (since 12 November 2026). Timetable changes run in the database as that admin. |

Errors: `401 AUTH_REQUIRED`, `403 FORBIDDEN_ROLE` / `ADMIN_REQUIRED`; login errors `INVALID_CREDENTIALS` (401), `ACCOUNT_NOT_LINKED` / `EMAIL_NOT_CONFIRMED` (403), `TOO_MANY_ATTEMPTS` (429), `AUTH_NOT_CONFIGURED` (503), `AUTH_UNAVAILABLE` (502), `AUTH_TIMEOUT` (504). The student endpoints keep their existing plain-text error style. Passwords and tokens are never returned in response bodies or logged.

## Account setup

The app does not create accounts. In the Supabase dashboard:

1. **Authentication → Sign In / Providers:** keep Email enabled; turn **off** "Allow new users to sign up".
2. **Authentication → Users → Add user:** enter the email and password and tick **Auto Confirm User** (unconfirmed accounts get `EMAIL_NOT_CONFIRMED`).
3. Link each account to its record in the SQL Editor (replace the placeholders):

   ```sql
   update public.students  set auth_user_id = (select id from auth.users where email = '<student email>')  where student_code  = '<STUDENT CODE>';
   update public.lecturers set auth_user_id = (select id from auth.users where email = '<lecturer email>') where lecturer_code = '<LECTURER CODE>';
   insert into public.admins (auth_user_id, full_name) select id, '<Admin name>' from auth.users where email = '<admin email>';
   ```

The backend uses the existing `SUPABASE_URL` and `SUPABASE_KEY` from `.env`; no new setting is required.

## Code changes

| File | Change |
| --- | --- |
| `backend/app/auth.py` (new) | Supabase Auth client, role lookup, session cache, cookie middleware, `get_session` / `require_roles` dependencies, `/api/auth/*` routes |
| `backend/app/main.py` | Auth router and middleware; page routes `/`, `/login`, `/student`, `/lecturer`, `/admin` with server-side redirects; database health needs a login |
| `backend/app/student.py` | Login required; students limited to their own code |
| `backend/app/lecturer.py` | Login required; lecturers limited to their own id and classes (the reschedule endpoint previously let anyone move any class); lecturer list narrowed to self for lecturers |
| `backend/app/scheduling/preview.py` | Page moved to `/admin/development/scheduling-test-hayden`; page redirects to login; APIs and assets admin-only |
| `backend/app/scheduling/development/*` | New asset paths, "← Admin" link, redirect to login on 401 |
| `frontend/src/App.vue` | Main menu removed; now the router shell with login checks and the session bar |
| `frontend/src/router.js`, `auth/session.js`, `auth/LoginPage.vue`, `admin/AdminPage.vue` (new) | Path router, session helpers, login page, empty admin page (one link to the scheduling page) |
| `frontend/src/main.js` | Redirect to `/login` when any API call returns 401 |
| `frontend/vite.config.js` | Proxy `/admin/development` to FastAPI |

`frontend/src/student/*` and `frontend/src/lecturer/*` are unchanged.

## Verification (12 November 2026)

Local stand-ins only; the hosted Supabase project was not contacted.

- **23 new backend auth tests passed** (`backend/tests/test_auth.py`) against a fake Supabase Auth + role tables: login for each role and the role priority, cookie flags, wrong password, unknown and unlinked accounts, unconfirmed email, malformed input rejected before Supabase, token refresh, cleared cookies on a revoked session, logout, page redirects and `next` safety, student/lecturer/admin API limits including the reschedule ownership check, admin-only scheduling page and APIs (and 404 outside development), session caching, missing configuration.
- Existing preview/save/app tests now act as a logged-in admin (or student, for database health) by overriding `get_session`; their behaviour checks are unchanged.
- **Full backend suite: 193 passed, 10 failed, 95 errors, 1 skipped** — the same 10 failures and 95 errors that `main` already had (stale fixtures, recorded in the step 10 entry); +23 from the new tests.
- **7 new frontend tests passed** (`frontend/src/auth/auth.test.js`, Node): `next` safety, landing page per role, legacy hash links, navigation, session load/login/logout handling. The existing 12 lecturer tests still pass. `npm run build` succeeds.
- **19 scheduling page tests passed**, including both served-page tests, which now log in as a synthetic QA admin on the local QA service (port 8001, stopped afterwards).
- **Not verified:** login against the real hosted Supabase (including whether its sign-in accepts the configured key type), and the Vue pages in a real browser (no browser was available in this session).

## Known limits

- Sessions are cached per server process for up to 60 seconds; logging out revokes the Supabase session, but another server process could still accept the old token for up to a minute.
- All Supabase Auth requests come from the backend's address, so Supabase's per-IP login rate limit is shared by all users of one server.
- The student page still has its own "Switch" button and code box (not changed, decision 7); entering another student's code now returns 403.
- The backend still reads data with the service key and enforces access in Python; the database's row-level security policies (which use `auth.uid()`) are not used by these requests.
- The save audit was implemented on 12 November using the session's Supabase user id ([save audit](save-audit.md)). `SessionUser.auth_user_id` is server-side only and is not returned by `/api/auth/*`.
- `frontend/src/student/README.md` and `frontend/src/lecturer/README.md` still mention the old `#/student` and `#/lecturer` addresses; they belong to those pages' owners and were left unchanged.
