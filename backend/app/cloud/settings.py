"""Cloud-only configuration; no insecure local-data fallback."""
import os

REQUIRED = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL")
BUCKET = os.getenv("SENTINEL_STORAGE_BUCKET", "sentinel-private")
FRONTEND_ORIGIN = os.getenv("SENTINEL_FRONTEND_ORIGIN", "https://sentinel-document-intelligence.vercel.app")
USER_LIMIT = 40 * 1024 * 1024
GLOBAL_LIMIT = 800 * 1024 * 1024
CASE_LIMIT = 2


def validate_settings():
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing cloud configuration: " + ", ".join(missing))
    if not FRONTEND_ORIGIN.startswith("https://") or FRONTEND_ORIGIN.endswith("/"):
        raise RuntimeError("SENTINEL_FRONTEND_ORIGIN must be an HTTPS origin without trailing slash")


def value(name: str) -> str:
    result = os.getenv(name)
    if not result:
        raise RuntimeError(f"Missing cloud configuration: {name}")
    return result
