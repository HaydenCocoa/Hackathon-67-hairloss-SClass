"""Login with Supabase Auth (email + password); the session lives in httpOnly cookies.

The browser never sees a Supabase key or token. FastAPI exchanges the email and
password for Supabase tokens, stores them in httpOnly cookies, verifies the
access token with Supabase on later requests (cached briefly), and maps the
Supabase user to exactly one role through the auth_user_id columns:
admin > lecturer > student when an account is linked to several.
"""

import base64
import json
import os
import time
from contextvars import ContextVar
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import SupabaseSettings

Role = Literal["admin", "lecturer", "student"]
HOME: dict[str, str] = {"admin": "/admin", "lecturer": "/lecturer", "student": "/student"}
# Accounts created with a temporary password (admin page) carry this flag in Supabase
# app_metadata, which only the server key can change. Until it is cleared, the user's
# only page is PASSWORD_PAGE and other APIs answer 403 PASSWORD_CHANGE_REQUIRED.
PASSWORD_FLAG = "must_change_password"
PASSWORD_PAGE = "/change-password"
ACCESS_COOKIE = "sclass_access"
REFRESH_COOKIE = "sclass_refresh"
REFRESH_MAX_AGE = 7 * 24 * 3600
SESSION_CACHE_SECONDS = 60


class SessionUser(BaseModel):
    role: Role
    name: str
    email: str | None = None
    profile_id: str = Field(description="id in admins, lecturers or students")
    code: str | None = Field(default=None, description="student_code or lecturer_code")
    home: str
    # Supabase Auth user id, used server-side for audit (schedule_changes.changed_by).
    # Never sent to the browser.
    auth_user_id: str = Field(exclude=True)
    must_change_password: bool = False


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)
    # Supabase Auth hashes with bcrypt, which uses at most 72 bytes.
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Use at most 72 bytes")
        return value


def password_change_required() -> HTTPException:
    return auth_error(403, "PASSWORD_CHANGE_REQUIRED", "Change your temporary password to continue.")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def clean(cls, value: str) -> str:
        value = value.strip()
        if "@" not in value:
            raise ValueError("Enter an email address")
        return value


def auth_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message}, headers={"Cache-Control": "no-store"})


def safe_next(value: str | None) -> str | None:
    """Only same-site page paths are allowed after login (no open redirects)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    if value.startswith(("/api/", "/login")) or any(ord(ch) < 32 for ch in value):
        return None
    return value


# ---------- Supabase Auth + role lookup ----------

class SupabaseAuth:
    def __init__(self, settings: SupabaseSettings, client: httpx.AsyncClient):
        self.url = os.getenv(settings.url_env, "").strip().rstrip("/")
        self.key = os.getenv(settings.key_env, "").strip()
        if not self.url or not self.key:
            raise auth_error(503, "AUTH_NOT_CONFIGURED", "Login is unavailable: Supabase is not configured on the server.")
        self.client = client
        self.timeout = settings.timeout_seconds

    def _headers(self, bearer: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.key, "Accept": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        elif self.key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    async def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self.client.request(method, f"{self.url}{path}", timeout=self.timeout, **kwargs)
        except httpx.TimeoutException:
            raise auth_error(504, "AUTH_TIMEOUT", "Supabase did not respond in time. Try again.")
        except httpx.RequestError:
            raise auth_error(502, "AUTH_UNAVAILABLE", "Could not reach Supabase. Try again.")

    @staticmethod
    def _tokens(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not body.get("access_token") or not isinstance(body.get("user"), dict):
            raise auth_error(502, "AUTH_UNAVAILABLE", "Supabase returned an unexpected login response.")
        return body

    async def password_login(self, email: str, password: str) -> dict[str, Any]:
        response = await self._call("POST", "/auth/v1/token", params={"grant_type": "password"},
                                    headers=self._headers(), json={"email": email, "password": password})
        if response.status_code == 200:
            return self._tokens(response)
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = str(body.get("error_code") or body.get("error") or "") if isinstance(body, dict) else ""
        if error == "email_not_confirmed":
            raise auth_error(403, "EMAIL_NOT_CONFIRMED", "This account's email is not confirmed in Supabase. Ask an administrator to confirm it.")
        if response.status_code in (400, 401, 422):
            raise auth_error(401, "INVALID_CREDENTIALS", "Incorrect email or password.")
        if response.status_code == 429:
            raise auth_error(429, "TOO_MANY_ATTEMPTS", "Too many login attempts. Wait a moment and try again.")
        raise auth_error(502, "AUTH_UNAVAILABLE", "Supabase could not complete the login. Try again.")

    async def refresh(self, refresh_token: str) -> dict[str, Any] | None:
        response = await self._call("POST", "/auth/v1/token", params={"grant_type": "refresh_token"},
                                    headers=self._headers(), json={"refresh_token": refresh_token})
        if response.status_code == 200:
            return self._tokens(response)
        if response.status_code in (400, 401, 403, 422):
            return None
        raise auth_error(502, "AUTH_UNAVAILABLE", "Supabase could not refresh the session. Try again.")

    async def user(self, access_token: str) -> dict[str, Any] | None:
        response = await self._call("GET", "/auth/v1/user", headers=self._headers(access_token))
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                body = None
            return body if isinstance(body, dict) and body.get("id") else None
        if response.status_code in (401, 403):
            return None
        raise auth_error(502, "AUTH_UNAVAILABLE", "Supabase could not verify the session. Try again.")

    async def logout(self, access_token: str, scope: str | None = None) -> None:
        """Revoke sessions: Supabase's default is all of the user's sessions; scope='local' only this one."""
        try:
            await self.client.post(f"{self.url}/auth/v1/logout", headers=self._headers(access_token), timeout=self.timeout,
                                   params={"scope": scope} if scope else None)
        except httpx.HTTPError:
            pass  # Best effort; the cookies are cleared regardless.

    async def set_password(self, access_token: str, password: str) -> None:
        """Change the logged-in user's own password (Supabase `updateUser`). Supabase Auth
        stores only a bcrypt hash; the password is never stored or logged here."""
        response = await self._call("PUT", "/auth/v1/user", headers=self._headers(access_token), json={"password": password})
        if response.status_code == 200:
            return
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        error = str(body.get("error_code") or "")
        if error == "same_password":
            raise auth_error(422, "SAME_PASSWORD", "Choose a password different from your current one.")
        if error == "weak_password":
            detail = body.get("weak_password")
            reasons = detail.get("reasons") if isinstance(detail, dict) else None
            if isinstance(reasons, list) and "pwned" in reasons:
                raise auth_error(422, "WEAK_PASSWORD", "This password has appeared in a data breach. Choose a different one.")
            raise auth_error(422, "WEAK_PASSWORD", "This password is too weak for this site's rules. Use a longer password with a mix of letters, numbers and symbols.")
        raise auth_error(502, "AUTH_UNAVAILABLE", "Supabase could not change the password. Try again.")

    async def clear_password_flag(self, user_id: str) -> dict[str, Any]:
        """Admin API (server key): clear the temporary-password flag; returns the updated user."""
        response = await self._call("PUT", f"/auth/v1/admin/users/{quote(user_id, safe='')}", headers=self._headers(),
                                    json={"app_metadata": {PASSWORD_FLAG: False}})
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict) or not body.get("id"):
            raise auth_error(502, "PASSWORD_FLAG_NOT_CLEARED",
                             "Your password was changed, but the change could not be recorded. Use your new password as the current one and try again.")
        return body

    async def _rows(self, table: str, select: str, user_id: str) -> list[dict]:
        response = await self._call("GET", f"/rest/v1/{table}", headers=self._headers(),
                                    params=[("select", select), ("auth_user_id", f"eq.{user_id}"), ("limit", "1")])
        if response.status_code != 200:
            raise auth_error(502, "AUTH_UNAVAILABLE", "The account's role could not be loaded.")
        try:
            rows = response.json()
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            raise auth_error(502, "AUTH_UNAVAILABLE", "The account's role could not be loaded.")
        return rows

    async def session_for(self, user: dict[str, Any]) -> SessionUser | None:
        """Map a Supabase user to one role. Priority: admin > lecturer > student."""
        user_id, email = str(user["id"]), user.get("email")
        metadata = user.get("app_metadata")
        must_change = isinstance(metadata, dict) and metadata.get(PASSWORD_FLAG) is True
        for role, table, select, code_key in (
            ("admin", "admins", "id,full_name", None),
            ("lecturer", "lecturers", "id,full_name,lecturer_code", "lecturer_code"),
            ("student", "students", "id,full_name,student_code", "student_code"),
        ):
            rows = await self._rows(table, select, user_id)
            if rows:
                row = rows[0]
                return SessionUser(role=role, name=row.get("full_name") or "", email=email, profile_id=str(row["id"]),
                                   code=row.get(code_key) if code_key else None,
                                   home=PASSWORD_PAGE if must_change else HOME[role],
                                   auth_user_id=user_id, must_change_password=must_change)
        return None


# ---------- Session cache and cookie handling ----------

class SessionCache:
    """Short-lived cache: access token -> SessionUser, so each request does not
    call Supabase. A revoked token stays usable for at most `ttl` seconds."""

    def __init__(self, ttl: float = SESSION_CACHE_SECONDS, size: int = 2048):
        self.ttl, self.size, self.items = ttl, size, {}

    def get(self, token: str) -> SessionUser | None:
        item = self.items.get(token)
        if item and item[0] > time.monotonic():
            return item[1]
        self.items.pop(token, None)
        return None

    def put(self, token: str, session: SessionUser) -> None:
        now = time.monotonic()
        if len(self.items) >= self.size:
            self.items = {key: value for key, value in self.items.items() if value[0] > now}
            if len(self.items) >= self.size:
                self.items.clear()
        lifetime = min(self.ttl, max(0.0, _token_expiry(token) - time.time())) if _token_expiry(token) else self.ttl
        if lifetime > 0:
            self.items[token] = (now + lifetime, session)

    def drop(self, token: str | None) -> None:
        if token:
            self.items.pop(token, None)


def _token_expiry(token: str) -> float | None:
    """Read `exp` from a JWT payload WITHOUT trusting it; only used to stop
    caching a token past its expiry. Validity always comes from Supabase."""
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(data["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return None


# Set-Cookie headers queued during a request (login, refresh, logout) and added
# to the response by AuthCookieMiddleware, whatever response type the route returns.
_PENDING_COOKIES: ContextVar[list | None] = ContextVar("sclass_pending_cookies", default=None)


def _queue_cookie(request: Request, name: str, value: str, max_age: int) -> None:
    pending = _PENDING_COOKIES.get()
    if pending is None:
        return
    carrier = Response()
    carrier.set_cookie(name, value, max_age=max_age, path="/", httponly=True, samesite="lax",
                       secure=request.url.scheme == "https")
    pending.extend(header for header in carrier.raw_headers if header[0] == b"set-cookie")


def queue_session_cookies(request: Request, tokens: dict[str, Any]) -> None:
    expires_in = int(tokens.get("expires_in") or 3600)
    _queue_cookie(request, ACCESS_COOKIE, tokens["access_token"], expires_in)
    if tokens.get("refresh_token"):
        _queue_cookie(request, REFRESH_COOKIE, tokens["refresh_token"], REFRESH_MAX_AGE)


def queue_clear_cookies(request: Request) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        if name in request.cookies:
            _queue_cookie(request, name, "", 0)


class AuthCookieMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        pending: list = []
        token = _PENDING_COOKIES.set(pending)

        async def with_cookies(message):
            if message["type"] == "http.response.start" and pending:
                message = {**message, "headers": [*message.get("headers", []), *pending]}
            await send(message)

        try:
            await self.app(scope, receive, with_cookies)
        finally:
            _PENDING_COOKIES.reset(token)


# ---------- Dependencies ----------

async def get_session(request: Request) -> SessionUser | None:
    """The logged-in user, or None. Refreshes an expired session transparently.
    Tests override this dependency to act as a given user."""
    access, refresh = request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE)
    if not access and not refresh:
        return None
    cache: SessionCache = request.app.state.auth_sessions
    # The verified access token is kept on request.state (server-side only) for calls
    # that must run as this user in the database, such as the admin timetable functions.
    if access and (cached := cache.get(access)):
        request.state.access_token = access
        return cached
    auth = SupabaseAuth(request.app.state.supabase_settings, request.app.state.http_client)
    if access:
        user = await auth.user(access)
        if user and (session := await auth.session_for(user)):
            cache.put(access, session)
            request.state.access_token = access
            return session
    if refresh:
        tokens = await auth.refresh(refresh)
        if tokens and (session := await auth.session_for(tokens["user"])):
            queue_session_cookies(request, tokens)
            cache.put(tokens["access_token"], session)
            request.state.access_token = tokens["access_token"]
            return session
    queue_clear_cookies(request)
    return None


def require_roles(*roles: str, allow_password_change: bool = False):
    """Dependency for API routes: 401 when not logged in, 403 for other roles, and
    403 PASSWORD_CHANGE_REQUIRED while a temporary password is still in use."""

    async def dependency(session: SessionUser | None = Depends(get_session)) -> SessionUser:
        if session is None:
            raise auth_error(401, "AUTH_REQUIRED", "Log in to continue.")
        if session.must_change_password and not allow_password_change:
            raise password_change_required()
        if roles and session.role not in roles:
            raise auth_error(403, "FORBIDDEN_ROLE", "Your account cannot use this feature.")
        return session

    return dependency


require_login = require_roles()
require_admin = require_roles("admin")
require_any_session = require_roles(allow_password_change=True)


def login_redirect(path: str) -> str:
    return f"/login?next={quote(path, safe='/')}"


# ---------- Routes ----------

def create_auth_router() -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/login", response_model=SessionUser, responses={401: {}, 403: {}, 429: {}, 502: {}, 503: {}, 504: {}})
    async def login(body: LoginRequest, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        auth = SupabaseAuth(request.app.state.supabase_settings, request.app.state.http_client)
        tokens = await auth.password_login(body.email, body.password)
        session = await auth.session_for(tokens["user"])
        if session is None:
            await auth.logout(tokens["access_token"])
            raise auth_error(403, "ACCOUNT_NOT_LINKED", "This account is not linked to an admin, lecturer or student record. Contact an administrator.")
        queue_session_cookies(request, tokens)
        request.app.state.auth_sessions.put(tokens["access_token"], session)
        return session

    @router.get("/me", response_model=SessionUser, responses={401: {}})
    async def me(response: Response, session: SessionUser = Depends(require_any_session)):
        response.headers["Cache-Control"] = "no-store"
        return session

    @router.post("/change-password", response_model=SessionUser, responses={400: {}, 401: {}, 422: {}, 502: {}})
    async def change_password(body: PasswordChange, request: Request, response: Response,
                              session: SessionUser = Depends(require_any_session)):
        """Replace the password (required after an admin-created temporary one).

        1. Check the current password by signing in again; this also gives a fresh
           session, so Supabase never asks for reauthentication.
        2. Set the new password as the user (Supabase `updateUser`).
        3. Clear the temporary-password flag with the server key.
        4. Switch the cookies to the fresh session and revoke the old one."""
        response.headers["Cache-Control"] = "no-store"
        if body.new_password == body.current_password:
            raise auth_error(422, "SAME_PASSWORD", "Choose a password different from your current one.")
        if not session.email:
            raise auth_error(400, "NO_EMAIL", "This account has no email address, so its password cannot be changed here.")
        auth = SupabaseAuth(request.app.state.supabase_settings, request.app.state.http_client)
        try:
            tokens = await auth.password_login(session.email, body.current_password)
        except HTTPException as error:
            if isinstance(error.detail, dict) and error.detail.get("code") == "INVALID_CREDENTIALS":
                # 400, not 401: a 401 would make the page send the user back to /login.
                raise auth_error(400, "WRONG_PASSWORD", "Your current password is incorrect.")
            raise
        if str(tokens["user"].get("id")) != session.auth_user_id:
            raise auth_error(400, "WRONG_PASSWORD", "Your current password is incorrect.")
        await auth.set_password(tokens["access_token"], body.new_password)
        user = await auth.clear_password_flag(session.auth_user_id) if session.must_change_password else tokens["user"]
        updated = await auth.session_for(user)
        if updated is None:
            raise auth_error(403, "ACCOUNT_NOT_LINKED", "This account is not linked to an admin, lecturer or student record. Contact an administrator.")
        old_access = getattr(request.state, "access_token", None) or request.cookies.get(ACCESS_COOKIE)
        cache: SessionCache = request.app.state.auth_sessions
        cache.drop(old_access)
        if old_access:
            await auth.logout(old_access, scope="local")
        queue_session_cookies(request, tokens)
        cache.put(tokens["access_token"], updated)
        return updated

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        access = request.cookies.get(ACCESS_COOKIE)
        request.app.state.auth_sessions.drop(access)
        if access:
            try:
                await SupabaseAuth(request.app.state.supabase_settings, request.app.state.http_client).logout(access)
            except HTTPException:
                pass  # Not configured: nothing to revoke upstream.
        queue_clear_cookies(request)
        return {"status": "logged_out"}

    return router
