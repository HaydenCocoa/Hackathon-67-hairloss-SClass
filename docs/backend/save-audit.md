# Step 10: save audit (who saved a timetable)

Implemented and verified locally: 12 November 2026, branch `backend-enhancement`. **The migration has not been run on the hosted Supabase project.**

Related: [timetable saving](timetable-saving.md), [login](login.md), [backend record](agents.md).

## Requirement

Step 10 must save the assignments and the audit information together in one database transaction. The audit was deferred (decision D4) until login existed, because `schedule_changes.changed_by` must reference a signed-in user. Login has been in place since 12 November.

## Accepted decisions (12 November 2026)

The user accepted every recommendation and asked for the work on the current branch.

| # | Topic | Decision |
| --- | --- | --- |
| A1 | How the audit is made atomic | **Database trigger.** The backend still sends one insert (keeps D3: no database function called by the backend). A second request would not be atomic; a database function would reverse D3. |
| A2 | What is recorded | One `schedule_changes` row per saved class. No separate summary of the save. The request ID stays in `logs/scheduling.log`. |
| A3 | Inserts without an admin | Not refused. Dashboard, seed and other inserts without `created_by` get no audit row. The app's save always sets it. |
| A4 | Deleting audited classes | Stays blocked (the audit's foreign key has no cascade). Cancel instead. Occurrence-linked classes could not be deleted before either. |
| A5 | Student page | The student timetable endpoint ignores `create` rows, so a newly saved class does not appear as "rescheduled". Backend query only; student page components are unchanged. |
| A6 | Viewing the audit | SQL query in this document only; no new API (viewing was out of scope, D6). |
| A7 | Branch | The current branch, `backend-enhancement`. |

## How it works

```
POST /api/schedules/save (admin session)
  → recheck as before → ONE insert into class_sessions, every row with created_by = admin's Supabase user id
      └ AFTER INSERT trigger (same statement): schedule_changes row
          action 'create', changed_by = created_by, old_values {}, new_values {occurrence_id, section_id, room_id, starts_at, status}
```

- Classes and audit rows are written together or not at all: a failed insert (for example a duplicate occurrence) leaves neither.
- One save is identified by the same `changed_by` and the same `created_at` (PostgreSQL's transaction time).
- The admin's Supabase user id comes from the server-side session (`SessionUser.auth_user_id`). It is never returned to the browser (`/api/auth/login`, `/api/auth/me` and the save response omit it).
- The save response adds `saved_by` (the admin's name). The development page shows "recorded as saved by {name}".

## Database change

Migration [`supabase/migrations/202611120002_save_audit.sql`](../../supabase/migrations/202611120002_save_audit.sql):

1. Replaces the `schedule_changes.action` check (found by its definition, not its name) with `create`, `cancel`, `reschedule`.
2. Adds nullable `class_sessions.created_by uuid references auth.users(id)`.
3. Adds `campus_private.audit_class_session_create()` (security definer, not executable by app users) and the `audit_class_session_create` AFTER INSERT trigger.
4. Asks PostgREST to reload its schema so the new column is usable immediately.

It requires `202611100001_teaching_requirements.sql`, can be run more than once, and changes no existing rows. `schema.sql` is unchanged: as with the teaching-requirement migration, a fresh setup runs this migration after the earlier ones.

**Order:** run the migration **before** starting a backend with this change. Without it, every save is refused with `503 AUDIT_NOT_INSTALLED` and nothing is written. Running the migration before updating the backend is harmless (old saves just get no audit row).

## Viewing the audit (SQL Editor)

```sql
select sc.created_at, a.full_name as saved_by, count(*) as classes,
       min(cs.starts_at) as first_class, max(cs.starts_at) as last_class
from public.schedule_changes sc
join public.class_sessions cs on cs.id = sc.class_session_id
left join public.admins a on a.auth_user_id = sc.changed_by
where sc.action = 'create'
group by sc.created_at, a.full_name
order by sc.created_at desc;
```

Saved classes cannot be deleted (their audit rows and the step 2 occurrence rules both block it). To undo a test save, cancel its classes instead.

## Code changes

| File | Change |
| --- | --- |
| `supabase/migrations/202611120002_save_audit.sql` (new) | Column, action value, trigger (above) |
| `supabase/tests/save-audit.test.cjs` (new) | PGlite checks on the legacy and fresh schemas |
| `backend/app/auth.py` | `SessionUser.auth_user_id` (excluded from responses), set at login |
| `backend/app/scheduling/save.py` | `prepare_rows(..., created_by)` adds `created_by` to every row; `SaveResult.saved_by` |
| `backend/app/scheduling/preview.py` | Save passes the admin from `admin_access`; `PGRST204`/`42703` → `503 AUDIT_NOT_INSTALLED`; OpenAPI text |
| `backend/app/student.py` | `SupabaseWriteError` keeps `PGRST204`/`42703`; recent changes filtered to `cancel`/`reschedule` |
| `backend/app/scheduling/development/app.js` | Success message names the saving admin |
| `backend/tests/*` | Test sessions carry `auth_user_id`; new save, error, privacy and student-filter checks |

## Verification (12 November 2026)

Local stand-ins only; the hosted Supabase project was not contacted.

- **Database: 46 new checks passed** (`supabase/tests/save-audit.test.cjs`, PGlite, on the legacy schema and a fresh `schema.sql`, after the teaching and `rescheduled` migrations). They cover: `create` was rejected before and is accepted after; only the action check is replaced; a rerun is harmless; existing rows untouched; one audit row per class with the right `changed_by` and values in a multi-row insert; one shared timestamp; a failed insert leaves neither classes nor audit rows; unknown users are refused; inserts without `created_by` work unaudited; `cancel`/`reschedule` still work; audited classes cannot be deleted; app users cannot execute the trigger function. The other 7 database suites still pass.
- **Backend:** all 32 save tests pass, including the new `created_by` and `saved_by` checks and the two `AUDIT_NOT_INSTALLED` cases. Auth tests check that `auth_user_id` is not in the login or `/me` responses, and a new test checks that students do not see `create` rows. **Full suite: 199 passed, 10 failed, 97 errors, 1 skipped.** Before this change, on the same branch, it was 196 passed with the **same** 10 failures and 97 errors (stale fixtures, recorded earlier).
- **Scheduling page: 19 of 19 passed**, including both served-page tests against the synthetic QA service on port 8001 (stopped afterwards). The real save showed "recorded as saved by QA Admin".
- **Frontend auth tests:** 7 of 7 passed.
- **Not verified:** the migration and a real save on hosted Supabase (including PostgREST's reply when the column is missing, assumed to be `PGRST204`), and the page in a real browser.

## Risks and limits

- **Not run on hosted Supabase.** The user must run the migration in the SQL Editor; until then, saves from this backend return `AUDIT_NOT_INSTALLED`.
- Only saves from this app are audited. The Supabase dashboard, seed scripts and the lecturer reschedule endpoint (step 11) write no audit rows.
- Deleting a Supabase Auth user who saved a timetable fails (both `created_by` and `changed_by` reference `auth.users` without cascade).
- `schedule_changes` is readable under existing row-level security by anyone who can read the class, which includes the saving admin's Auth user id. The app never gives browsers a Supabase token, so this matters only for direct Supabase access.
- `created_by` can still be changed by an update with the service key; the audit row keeps the original value.
