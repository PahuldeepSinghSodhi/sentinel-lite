"""Private Supabase Storage objects, accessed only after API ownership checks."""
from urllib.parse import quote

import requests

from app.cloud.settings import BUCKET, value


def _url(path: str) -> str:
    encoded = quote(path, safe="/")
    return f"{value('SUPABASE_URL').rstrip('/')}/storage/v1/object/{BUCKET}/{encoded}"


def _headers() -> dict:
    key = value("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def put(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    response = requests.post(_url(path), data=data,
                             headers={**_headers(), "Content-Type": content_type}, timeout=90)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Private storage upload failed ({response.status_code})")


def get(path: str) -> bytes:
    url = f"{value('SUPABASE_URL').rstrip('/')}/storage/v1/object/authenticated/{BUCKET}/{quote(path, safe='/')}"
    response = requests.get(url, headers=_headers(), timeout=90)
    if response.status_code == 404:
        raise FileNotFoundError("Private case object is missing")
    if response.status_code != 200:
        raise RuntimeError(f"Private storage download failed ({response.status_code})")
    return response.content


def delete(paths: list[str]) -> None:
    if not paths:
        return
    response = requests.delete(
        f"{value('SUPABASE_URL').rstrip('/')}/storage/v1/object/{BUCKET}",
        json={"prefixes": paths}, headers={**_headers(), "Content-Type": "application/json"}, timeout=90)
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Private storage deletion failed ({response.status_code})")
