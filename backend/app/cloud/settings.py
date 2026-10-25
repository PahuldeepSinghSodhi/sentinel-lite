"""Cloud-only configuration; no insecure local-data fallback."""
import os

PROVIDER = os.getenv("SENTINEL_CLOUD_PROVIDER", "supabase").lower()
if PROVIDER not in {"supabase", "aws"}:
    raise ValueError("SENTINEL_CLOUD_PROVIDER must be supabase or aws")
REQUIRED = (("AWS_REGION", "SENTINEL_DATABASE_SECRET_ID", "SENTINEL_STORAGE_BUCKET",
             "COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID", "SENTINEL_SECRET_PREFIX", "SENTINEL_RDS_CA_FILE") if PROVIDER == "aws" else
            ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL"))
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
    allowed_origins()


def allowed_origins():
    origins = [FRONTEND_ORIGIN] + [o.strip() for o in os.getenv("SENTINEL_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if any(not o.startswith("https://") or o.endswith("/") for o in origins):
        raise RuntimeError("Cloud browser origins must be explicit HTTPS origins")
    return list(dict.fromkeys(origins))


def user_table():
    # Only fixed identifiers can reach SQL; never interpolate a caller value.
    return "app_users" if PROVIDER == "aws" else "auth.users"


def value(name: str) -> str:
    result = os.getenv(name)
    if not result:
        raise RuntimeError(f"Missing cloud configuration: {name}")
    return result
