"""Authenticated cloud-only user, job, and invitation operations."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cloud import db, jobs, providers, store
from app.cloud.auth import current_user, require_admin

router = APIRouter(tags=["Cloud workspace"])


def _error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(404, str(exc.args[0])) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(403, str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(502, str(exc)) from exc
    raise exc


class ProviderSetting(BaseModel):
    provider: str
    model: str
    api_key: str = Field(min_length=8, max_length=500)


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = "reviewer"
    enabled: bool = True


@router.get("/me")
def me():
    user = current_user()
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


@router.get("/me/storage")
def storage_usage():
    return store.usage()


@router.get("/me/model")
def model_settings():
    return providers.settings()


@router.put("/me/model")
def save_model(payload: ProviderSetting):
    try:
        return providers.save(payload.provider, payload.model, payload.api_key)
    except Exception as exc:
        _error(exc)


@router.delete("/me/model", status_code=204)
def remove_model():
    providers.delete()


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    try:
        return jobs.get(job_id)
    except Exception as exc:
        _error(exc)


@router.get("/admin/invites")
def list_invites():
    try:
        require_admin()
        with db.connect() as conn:
            return list(conn.execute("SELECT email, role, enabled, created_at FROM app_invites ORDER BY email"))
    except Exception as exc:
        _error(exc)


@router.put("/admin/invites")
def set_invite(payload: Invite):
    try:
        require_admin()
        email = payload.email.strip().lower()
        if "@" not in email or payload.role not in {"admin", "reviewer"}:
            raise ValueError("Enter a valid email and role")
        if email == current_user()["email"] and (not payload.enabled or payload.role != "admin"):
            raise ValueError("An administrator cannot remove their own administrator access")
        with db.connect() as conn:
            conn.execute("""INSERT INTO app_invites (email, role, enabled) VALUES (%s, %s, %s)
                            ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role,
                            enabled = EXCLUDED.enabled""", (email, payload.role, payload.enabled))
        return {"email": email, "role": payload.role, "enabled": payload.enabled}
    except Exception as exc:
        _error(exc)
