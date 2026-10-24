"""Provider keys stay in Secrets Manager. The database holds only a secret reference."""
from app.cloud import db
from app.cloud.auth import current_user
from app.cloud.aws_clients import client
from app.cloud.settings import value


def load():
    with db.connect() as conn:
        row = conn.execute("SELECT provider, model, secret_id FROM model_settings WHERE owner_id=%s",
                           (current_user()["id"],)).fetchone()
    if not row:
        raise RuntimeError("Choose and test an AI provider in Settings first")
    secret = client("secretsmanager").get_secret_value(SecretId=row["secret_id"])["SecretString"]
    return row["provider"], row["model"], secret


def save(provider, model, key):
    from botocore.exceptions import ClientError
    secret_id = value("SENTINEL_SECRET_PREFIX").rstrip("/") + "/" + str(current_user()["id"])
    service = client("secretsmanager")
    try:
        service.create_secret(Name=secret_id, SecretString=key,
                              Tags=[{"Key": "Application", "Value": "Sentinel"}])
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceExistsException":
            raise
        metadata = service.describe_secret(SecretId=secret_id)
        if metadata.get("DeletedDate"):
            service.restore_secret(SecretId=secret_id)
        service.put_secret_value(SecretId=secret_id, SecretString=key)
    with db.connect() as conn:
        conn.execute("""INSERT INTO model_settings (owner_id, provider, model, secret_id) VALUES (%s,%s,%s,%s)
            ON CONFLICT (owner_id) DO UPDATE SET provider=EXCLUDED.provider, model=EXCLUDED.model,
            secret_id=EXCLUDED.secret_id, updated_at=now()""", (current_user()["id"], provider, model, secret_id))


def delete():
    with db.connect() as conn:
        row = conn.execute("SELECT secret_id FROM model_settings WHERE owner_id=%s FOR UPDATE",
                           (current_user()["id"],)).fetchone()
        if row:
            client("secretsmanager").delete_secret(SecretId=row["secret_id"], RecoveryWindowInDays=7)
            conn.execute("DELETE FROM model_settings WHERE owner_id=%s", (current_user()["id"],))
