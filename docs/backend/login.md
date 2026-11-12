# Login and role-based access

Implemented and verified locally: 12 November 2026, branch `feature-login`. **Not run against the hosted Supabase project.**

Related: [backend record](agents.md), [scheduling preview](schedule-preview-api.md), [timetable saving](timetable-saving.md).

## Requirement

Everyone visiting the website must log in at `/login`. Roles are Admin, Student and Lecturer, using accounts stored in Supabase. Every page that needs a login redirects to `/login` when the visitor is not logged in.

## Accepted decisions (12 November 2026)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Login identifier | Email + password from Supabase Auth. |
| 2 | Accounts | Created and linked by the project owner in Supabase (see [Account setup](#account-setup)). **Changed 13 November 2026:** the admin page's Add student and Add lecturer forms now also create a confirmed login with a temporary password and link it ([admin-created logins](admin-accounts.md)). |
| 3 | Where login happens | In the backend; the session is kept in httpOnly cookies. No Supabase key or token reaches the browser. |
| 4 | Page addresses | `/login`, `/student`, `/lecturer`, `/admin`. Old `#/student`, `#/lecturer`, `#main` links redirect. |
| 5 | Account linked to several roles | admin > lecturer > student. |
| 6 | Main menu | Removed. `/admin` is an empty placeholder; the admin area is built by another team member. |
| 7 | Student and lecturer pages | Not changed. Only routing to them; the shell passes the logged-in student's code to the student page through its existing `studentCode` prop. |
| 8 | Sign-up and forgot password | Out of scope. Public sign-up should be disabled in Supabase. |
| 10 | Temporary passwords (13 November 2026) | An account created on the admin page must replace its temporary password at first login, at `/change-password`, before it can open any other page or API. See [Forced password change](#forced-password-change). |
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
| `/admin/schedule` | → `/login?next=/admin/schedule` | Admins only; others → own home. Scheduling workspace opened from Admin > Timetable > Schedule Class (added 12 November 2026). Its generate/save calls need an admin login only (production since 12 November 2026) |
| `/admin/development/scheduling-test-hayden` | → `/login?next=…` | Admins only (plus development mode and localhost) |
| `/change-password` | → `/login` | Only while a temporary password is in use; others → own home. Meanwhile every page above sends the user here. |

The backend applies these rules when a page is loaded directly; the Vue app repeats them for the Vite dev server and in-app navigation. If any API call returns 401 later (session expired), the app sends the user to `/login` and back afterwards. A thin bar above each page shows the user's name, role and a **Log out** button.

## API access

| Endpoint | Access |
| --- | --- |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Public / logged in (`me` returns 401 when not logged in) |
| `POST /api/auth/change-password` | Any logged-in user, including one with a temporary password |
| Every other logged-in API | 403 `PASSWORD_CHANGE_REQUIRED` while a temporary password is in use |
| `GET /api/health`, `GET /api/config`, `/docs`, `/openapi.json` | Public |
| `GET /api/health/database`, `GET /api/rooms` | Any logged-in user |
| `GET /api/student/{code}`, `…/timetable` | Students: their own code only (403 otherwise); admins: any |
| `GET /api/lecturers` | Lecturers: only themselves; admins: all; students: 403 |
| `GET /api/lecturers/{id}/timetable` | Lecturers: their own id only; admins: any |
| `PATCH /api/lecturers/{id}/sessions/{sid}` | Lecturers: own id **and** the class must belong to that lecturer; admins: any lecturer's class |
| `POST /api/schedules/generate`, `POST /api/schedules/save` | Admins only, same-site `Origin` (production since 12 November 2026) |
| Scheduling test page and assets (`/admin/development/…`) | Admins only, plus development mode and localhost |
| `GET /api/admin/timetable/{id}/availability`, `POST …/reschedule` | Admins only (the `POST` also needs a same-site `Origin`) |
| `/api/admin/*` (admin page) | Admins only: the login session, or a pasted Supabase token (since 12 November 2026). Timetable changes run in the database as that admin. |

Errors: `401 AUTH_REQUIRED`, `403 FORBIDDEN_ROLE` / `ADMIN_REQUIRED`; login errors `INVALID_CREDENTIALS` (401), `ACCOUNT_NOT_LINKED` / `EMAIL_NOT_CONFIRMED` (403), `TOO_MANY_ATTEMPTS` (429), `AUTH_NOT_CONFIGURED` (503), `AUTH_UNAVAILABLE` (502), `AUTH_TIMEOUT` (504). The student endpoints keep their existing plain-text error style. Passwords and tokens are never logged or returned in response bodies, with one exception since 13 November 2026: the admin-only create routes return a new user's temporary password once, marked `no-store` ([admin-created logins](admin-accounts.md)).

## Forced password change

Added 13 November 2026 at the user's request: "When a new user logs into their interface require them to change their passwords."

- **The flag.** The admin page creates each login with `app_metadata.must_change_password = true` ([admin-created logins](admin-accounts.md)). In Supabase, `app_metadata` can be changed only with the server key; users can edit only `user_metadata`, so they cannot clear the flag themselves.
- **While it is set.** The session reports `must_change_password: true` and `home: "/change-password"`. Page loads go to `/change-password`, and every API except `me`, `logout` and `change-password` answers 403 `PASSWORD_CHANGE_REQUIRED`: through `require_roles`, the admin API's own check, and the scheduling tools. The student and lecturer page components are unchanged; the app shell shows the change page instead of them.
- **`POST /api/auth/change-password`** with `{current_password, new_password}`:
  1. `new_password`: 8 to 72 bytes (bcrypt's limit) and different from the current one. The project's own Supabase password rules apply on top.
  2. The current password is checked by signing in again. That also gives a fresh session, so Supabase's "secure password change" never asks for reauthentication.
  3. The new password is set as the user with `PUT /auth/v1/user` (Supabase `updateUser`, as in [Supabase's password guide](https://supabase.com/docs/guides/auth/passwords)). Supabase stores only its bcrypt hash.
  4. The flag is cleared with the server key (`PUT /auth/v1/admin/users/{id}`, `app_metadata` is merged).
  5. The cookies switch to the fresh session, and the old one is revoked on its own (`/auth/v1/logout?scope=local`). The reply is the updated session, with the role's home page.
- **Errors:** `WRONG_PASSWORD` (400, not 401, so the page does not jump to the login), `SAME_PASSWORD` and `WEAK_PASSWORD` (422; a password found in a breach gets its own message), `PASSWORD_FLAG_NOT_CLEARED` (502: the password changed but the flag did not, so the user is asked again and enters the new password as the current one).
- Accounts without the flag (all accounts made in the Supabase dashboard) are not affected. The endpoint also works for them, but no page links to it, because voluntary password change was not requested.

## Account setup

New students (with a new student code) and new lecturers added on the admin page get a login automatically; see [admin-created logins](admin-accounts.md). For admins, and for students or lecturers that already exist, use the Supabase dashboard:

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
