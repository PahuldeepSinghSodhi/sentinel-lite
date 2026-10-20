"""Verify Supabase bearer tokens and enforce the live invitation allowlist."""
from contextlib import contextmanager
from contextvars import ContextVar

import requests

from app.cloud import db
from app.cloud.settings import value

_user = ContextVar("sentinel_cloud_user", default=None)
_job = ContextVar("sentinel_cloud_job", default=None)


def current_user() -> dict:
    user = _user.get()
    if not user:
        raise PermissionError("Sign in to access this review")
    return user


def current_job() -> str | None:
    return _job.get()


@contextmanager
def user_context(user: dict, job_id: str | None = None):
    token = _user.set(user)
    job_token = _job.set(job_id)
    try:
        yield
    finally:
        _job.reset(job_token)
        _user.reset(token)


def authenticate(header: str) -> dict:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise PermissionError("Sign in to access this review")
    try:
        result = requests.get(
            f"{value('SUPABASE_URL').rstrip('/')}/auth/v1/user",
            headers={"apikey": value("SUPABASE_ANON_KEY"), "Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise PermissionError("Authentication service is unavailable") from exc
    if result.status_code != 200:
        raise PermissionError("Your session has expired; sign in again")
    user = result.json()
    user_id, email = user.get("id"), str(user.get("email") or "").strip().lower()
    if not user_id or not email or not user.get("email_confirmed_at"):
        raise PermissionError("Account is missing a verified email")
    with db.connect() as conn:
        invite = conn.execute("SELECT role FROM app_invites WHERE email = %s AND enabled", (email,)).fetchone()
    if not invite:
        raise PermissionError("This account is not invited to Sentinel")
    return {"id": user_id, "email": email, "role": invite["role"]}


def require_admin() -> dict:
    user = current_user()
    if user["role"] != "admin":
        raise PermissionError("Administrator access required")
    return user
