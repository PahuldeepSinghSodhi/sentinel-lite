"""Administrator-controlled provisioning; sign-in never links accounts by email."""
from uuid import uuid4

from app.cloud import db
from app.cloud.aws_clients import client
from app.cloud.aws_auth import issuer
from app.cloud.settings import value


def provision(email, enabled=True):
    cognito = client("cognito-idp")
    pool = value("COGNITO_USER_POOL_ID")
    try:
        user = cognito.admin_get_user(UserPoolId=pool, Username=email)
        attributes = user["UserAttributes"]
    except cognito.exceptions.UserNotFoundException:
        if not enabled:
            return
        created = cognito.admin_create_user(UserPoolId=pool, Username=email, MessageAction="SUPPRESS",
            UserAttributes=[{"Name":"email","Value":email},{"Name":"email_verified","Value":"true"}])
        user = created["User"]
        attributes = user["Attributes"]
    subject = next(a["Value"] for a in attributes if a["Name"] == "sub")
    with db.connect() as conn:
        existing = conn.execute("SELECT id FROM app_users WHERE lower(email)=%s FOR UPDATE", (email,)).fetchone()
        user_id = str(existing["id"]) if existing else str(uuid4())
        conn.execute("""INSERT INTO app_users(id,email,email_verified,disabled) VALUES (%s,%s,true,%s)
            ON CONFLICT(id) DO UPDATE SET disabled=EXCLUDED.disabled,
            email_verified=EXCLUDED.email_verified""", (user_id,email,not enabled))
        conn.execute("""INSERT INTO auth_identities(issuer,subject,app_user_id) VALUES (%s,%s,%s)
            ON CONFLICT(issuer,subject) DO NOTHING""", (issuer(),subject,user_id))
        bound = conn.execute("SELECT app_user_id FROM auth_identities WHERE issuer=%s AND subject=%s", (issuer(),subject)).fetchone()
        if str(bound["app_user_id"]) != user_id:
            raise RuntimeError("Account mapping requires administrator review")
    operation = cognito.admin_enable_user if enabled else cognito.admin_disable_user
    operation(UserPoolId=pool,Username=user["Username"])
