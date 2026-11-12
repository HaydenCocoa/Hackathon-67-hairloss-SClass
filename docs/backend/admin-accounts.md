# Admin-created logins for new students and lecturers

Added 13 November 2026. Main record: [agents.md](agents.md#admin-search-and-logins-for-new-students-and-lecturers--13-november-2026).

## Requirement

The user asked for an email field on the admin page's **Add student** (Intakes > Students) and **Add lecturer** forms. When the new user is created, the app also creates a temporary password: their TP number followed by 4 random digits. The user asked for Supabase's documentation on password handling and authentication to be followed.

- The TP number is the record's code: `student_code` for students and `lecturer_code` for lecturers.
- This changes login decision 2 ("the app never creates accounts") for these two forms only. Public sign-up and password reset are still out of scope; see [login](login.md).

## What Supabase's documentation says, and how it is applied

| Source (checked 13 November 2026) | Point | How the backend follows it |
| --- | --- | --- |
| [Auth admin `createUser`](https://supabase.com/docs/reference/javascript/auth-admin-createuser) | Creates a user from `email`, `password` and `email_confirm`. It must be called only on a server, and the service role key must never reach a browser. | The FastAPI backend calls `POST /auth/v1/admin/users` with `email_confirm: true` and `app_metadata: {must_change_password: true}`, using the server-only `SUPABASE_KEY`. The browser talks only to `/api/admin/...` with its login cookie. Without `email_confirm`, login would fail with `EMAIL_NOT_CONFIRMED`. |
| [Password security](https://supabase.com/docs/guides/auth/password-security) | Supabase Auth hashes passwords with bcrypt and a random salt per password. Only the hash is stored, in `auth.users.encrypted_password`. Minimum length, character rules and leaked-password checks are project settings. | The backend does **not** hash or encrypt the password itself; Supabase Auth does. The backend sends the plain password once, over HTTPS, and never stores or logs it. A rejected password returns a readable 422 (see below). |
| [API keys](https://supabase.com/docs/guides/api/api-keys) | Secret keys (`sb_secret_…`) go in the `apikey` header, not `Authorization: Bearer`, because they are not JWTs. A secret key is refused from a browser. | The existing `Supabase` client already sends `apikey` and adds `Authorization: Bearer` only for legacy JWT keys (`eyJ…`). A test checks that a non-JWT key goes only in `apikey`. |

## Temporary password

- `temporary_password(code)` returns `code + secrets.randbelow(10000)` written as 4 digits (`0000`–`9999`), for example `TP0123450042`. `secrets` is Python's cryptographically secure random source.
- The API response returns it **once** (`temporary_password`, with `Cache-Control: no-store`). The page shows it in a "Login created" box with a **Copy** button and the note that it cannot be shown again. Nothing else keeps it: not the database (only Supabase's bcrypt hash), not logs, not the browser's storage.
- **Weakness:** only the 4 digits are secret; the code is known to classmates. That is 10,000 possibilities. Supabase Auth rate-limits sign-in attempts.
- **Forced change (since 13 November 2026):** the login is created with `app_metadata.must_change_password = true`, so at first login the user must choose their own password before any other page or API works. See [login: forced password change](login.md#forced-password-change).
- If the hosted project requires a longer password or symbols, Supabase Auth refuses it (`weak_password`), and the API returns 422 "The temporary password does not meet this project's password rules in Supabase Auth." Nothing is created.

## API

All routes are admin-only, like the rest of `/api/admin`.

### `POST /api/admin/intakes/{intake_id}/students`

Body: `{student_code, full_name, age?, group_number, email?}`.

1. If the student code already exists, that student is added to the intake as before. Their name, age and login stay as they are, the email is ignored, and no login is created. Reply: `{id, existing: true, full_name}`.
2. Otherwise `email` is required (422 "Enter the new student's email address."). The address is trimmed and lower-cased; its shape is checked before Supabase checks it again.
3. The login is created in Supabase Auth.
4. The student row is created with `auth_user_id` set to that login, then the intake membership.
5. Reply: `{id, existing: false, full_name, email, temporary_password}`.

### `POST /api/admin/lecturers`

Body: `{lecturer_code, full_name, email}`. This route is registered before the generic `/api/admin/{table}` route, so lecturer **edits and deletes** still use the generic route (an edit cannot send `email`).

1. An existing lecturer code returns 409 before any login is made.
2. The login is created, then the lecturer row with `auth_user_id`.
3. Reply: the lecturer row plus `email` and `temporary_password`.

### Failures and undo

The login and the rows are separate requests, not one transaction. If a later step fails, the earlier ones are undone in reverse order: the new student row is deleted, then the login (`DELETE /auth/v1/admin/users/{id}`). Undoing the login is best effort; if Supabase cannot be reached at that moment, an unlinked login can remain, and login refuses unlinked accounts (`ACCOUNT_NOT_LINKED`).

| Supabase Auth reply | API reply |
| --- | --- |
| `email_exists` / `user_already_exists` | 409 "An account with this email already exists." |
| `weak_password` | 422 (see above) |
| `email_address_invalid` / `validation_failed` | 422 "Supabase Auth rejected this email address." |
| 401 / 403 | 502 "The server key cannot create logins. SUPABASE_KEY must be the secret (service role) key." |
| Unreachable or anything else | 502 |

An email that already has a login is refused rather than linked. This keeps the admin page from taking over an existing account, such as an admin's.

## Side effects to know about

- **Removing a student from their last intake** deleted their record only when they had no login. New students now always have a login, so their record (and login) stays; the reply says `student_deleted: false`, as before for linked students.
- **Deleting a lecturer** deletes only the `lecturers` row. Their Supabase login remains, unlinked, so login refuses it. Delete it in the Supabase dashboard if needed.
- Students and lecturers created **before** 13 November keep whatever login they had. There is no form for adding a login to an existing record; use the steps in [login](login.md#account-setup).

## Verification (13 November 2026)

- `backend/tests/test_admin_intake_students.py`: 12 passed (7 before; 5 new, 2 updated). New cases: login + record + membership in that order with the request bodies and headers checked; a missing or malformed email; undo of the row and the login when the membership fails; a duplicate email (409, nothing created) for students and lecturers; the lecturer flow (success, existing code, undo after a failed insert, missing email, no login); lecturer edits without `email`; the password format.
- These tests use a mock Supabase. **Not checked against hosted Supabase**, including its password settings and whether `SUPABASE_KEY` there is the secret key.
