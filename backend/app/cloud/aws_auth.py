"""Validate Cognito identity JWTs against the fixed pool, then enforce live DB access.

The browser's AWS adapter sends its ID token as the API identity credential.
Issuer, client audience, token_use, expiry and verified email are all required;
an access token or a token from another pool/client cannot pass this gate.
"""
from functools import lru_cache

from psycopg import Error as DatabaseError

from app.cloud import db
from app.cloud.auth import AccessError
from app.cloud.settings import value


def issuer():
    region = value("AWS_REGION")
    return f"https://cognito-idp.{region}.amazonaws.com/{value('COGNITO_USER_POOL_ID')}"


@lru_cache(maxsize=1)
def key_client():
    from jwt import PyJWKClient
    return PyJWKClient(issuer() + "/.well-known/jwks.json", cache_keys=True,
                       max_cached_keys=8, lifespan=300, timeout=5)


def authenticate(token):
    import jwt
    from botocore.exceptions import BotoCoreError, ClientError
    from jwt.exceptions import PyJWKClientConnectionError
    try:
        key = key_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=value("COGNITO_CLIENT_ID"),
                            issuer=issuer(), options={"require": ["exp", "iat", "sub", "aud", "iss", "token_use"]})
    except PyJWKClientConnectionError as exc:
        raise AccessError("auth_unavailable", "Authentication service is unavailable; please retry", 503) from exc
    except jwt.PyJWTError as exc:
        raise AccessError("session_invalid", "Your session has expired; sign in again", 401) from exc
    if claims.get("token_use") != "id":
        raise AccessError("session_invalid", "Sign in to access this review", 401)
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise AccessError("account_unverified", "Account is missing a verified email", 403)
    try:
        with db.connect() as conn:
            user = conn.execute("""SELECT u.id, lower(u.email) AS email, u.disabled, i.role
                FROM auth_identities a JOIN app_users u ON u.id=a.app_user_id
                LEFT JOIN app_invites i ON i.email=lower(u.email) AND i.enabled
                WHERE a.issuer=%s AND a.subject=%s""", (issuer(), claims["sub"])).fetchone()
    except (DatabaseError, OSError, BotoCoreError, ClientError) as exc:
        raise AccessError("auth_unavailable", "Invitation service is unavailable; please retry", 503) from exc
    # Never auto-link identities by an email supplied by a client.
    if not user or user["disabled"] or user["email"] != email or not user["role"]:
        raise AccessError("invite_required", "This account is not invited to Sentinel", 403)
    return {"id": str(user["id"]), "email": email, "role": user["role"]}
