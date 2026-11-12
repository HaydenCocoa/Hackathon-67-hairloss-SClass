# Vercel deployment (services)

Prepared: 12 November 2026, branch `feature-vercel-services`. **Configuration only — not yet deployed, and `vercel dev` has not been run** (the Vercel CLI is not installed on the development machine). Service names, public paths and the absence of bindings are **pending the user's confirmation**.

Related: [backend record](agents.md), [checklist](../../task_hayden.md), [login](login.md), [scheduling preview](schedule-preview-api.md).

## Requirement

Deploy the repository on Vercel as one project with multiple [services](https://vercel.com/docs/services): the FastAPI backend and the Vue/Vite frontend, on one domain, configured in a root `vercel.json`.

## Configuration

| Service | Root | Framework | Public path | Notes |
| --- | --- | --- | --- | --- |
| `backend` | `backend/` | `fastapi`, entrypoint `app.main:app` | `/api/*` | Build step copies `Config/config.json` into the bundle (see below). |
| `frontend` | `frontend/` | `vite` (`vite build` → `dist/`) | everything else (`/(.*)`, last) | Service-level rewrite `/(.*) → /index.html` gives the Vue path router (`/login`, `/student`, `/lecturer`, `/admin`) its SPA fallback; built files under `/assets/` are served first. |

Vercel passes the original path to a service, so the backend still sees `/api/...`. Every backend route already lives under `/api/`, and every browser call already uses a same-origin relative `/api/...` URL, so no route or client URL changed.

### Bindings: none

Bindings are needed only when one service calls another from server-side code. Here nothing does:

- The frontend is a static build. Its only backend calls are made by the browser to same-origin `/api/...`, which the public rewrite handles.
- The backend never calls the frontend; it calls only Supabase (`SUPABASE_URL`).

The `127.0.0.1:8000` proxy in `frontend/vite.config.js` is only for the existing `npm run dev` / `start-dev.bat` workflow and is not used on Vercel, so it was kept.

### Not publicly routed (decision pending confirmation)

- `/admin/development/*` (scheduling test page) — accepted rules keep it local-development only. Its guard already refuses any request carrying forwarded headers (every Vercel request does), so routing it would only return `403 LOCAL_ACCESS_ONLY`. On Vercel the path falls through to the frontend, whose router sends the user to their home page.
- `/docs` and `/openapi.json` (FastAPI's interactive API docs) — not exposed. Add `{ "source": "/(docs|openapi.json)", "destination": { "service": "backend" } }` before the catch-all to expose them.

## Code change: configuration file location

`backend/app/config.py` read `Config/config.json` relative to the repository root. A service rooted at `backend/` deploys only that directory, so the file would be missing and the backend would fail at startup.

- `vercel.json` gives the backend service the build command `mkdir -p Config && cp ../Config/config.json Config/config.json`, copying the same file into the bundle as `backend/Config/config.json`.
- `default_config_path()` uses `Config/config.json` at the repository root whenever it exists and falls back to `backend/Config/config.json` only when it does not. `Config/config.json` stays the single source of truth; the copy is git-ignored.
- Alternatives considered: moving the file into `backend/` (would break the documented location in `AGENTS.md`), or rooting the backend service at the repository root (dependency discovery for `backend/requirements.txt` and overlap with the frontend service root are unclear).

## Environment variables to set in the Vercel project

- `SUPABASE_URL`, `SUPABASE_KEY` (names from `Config/config.json`). The `.env` file is not deployed; `load_dotenv` silently skips it when missing.

## Behaviour differences from the single-server build

- **Page redirects.** Locally, FastAPI also serves the built pages and redirects logged-out visitors server-side. On Vercel the frontend service serves the pages, so only the Vue app's redirect (which already mirrors the server rules) applies. Data stays protected because every `/api/*` endpoint checks the session itself.
- **Session cache.** The 60-second token cache is per function instance, so instances may verify the same token separately. No correctness change.
- **File logging.** `logs/scheduling.log` cannot be written (read-only filesystem); the existing fallback logs a `file_logging_unavailable` event and keeps console logs, which appear in Vercel Runtime Logs.
- **`Secure` cookies** are set when the backend sees an `https` request scheme. Whether Vercel's Python runtime reports `https` has not been checked; if not, cookies are still httpOnly and `SameSite=Lax`, but without `Secure`.
- **`app.environment`** is `development` in the tracked config. The scheduling development tools remain blocked on Vercel by the localhost/forwarded-header check.

## Verification

- New test `test_config_path_prefers_repository_copy_and_falls_back_to_bundled_copy` passed.
- Full backend suite: 194 passed, 1 skipped, with the same 10 failures and 95 errors as `main` (pre-existing `required_room_type` test fixtures; unrelated).
- `npm run build` in `frontend/` succeeded.
- Simulated Vercel bundle: a copy of only `backend/app` plus the build-step copy of the config, imported as `app.main:app`; `/api/health` returned `ok`, `/api/config` returned the app name, and `/api/auth/me` returned 401 without a session.
- **Not verified:** `vercel dev`, a real Vercel build/deployment, bundle size with `ortools`, SPA fallback behaviour of service-level rewrites, and the cookie `Secure` flag on Vercel.
