"""AWS SDK clients use the instance role or selected local profile, never inline keys."""
from functools import lru_cache
import json
import time

from app.cloud.settings import value


@lru_cache(maxsize=8)
def client(service):
    import boto3
    from botocore.config import Config
    return boto3.client(service, region_name=value("AWS_REGION"), config=Config(
        signature_version="s3v4" if service == "s3" else None,
        connect_timeout=5, read_timeout=20, retries={"mode": "standard", "max_attempts": 3}))


_database = None
_database_until = 0


def database_dsn():
    global _database, _database_until
    if _database is None or time.monotonic() >= _database_until:
        from psycopg.conninfo import make_conninfo
        secret = json.loads(client("secretsmanager").get_secret_value(
            SecretId=value("SENTINEL_DATABASE_SECRET_ID"))["SecretString"])
        _database = make_conninfo(host=secret["host"], port=secret.get("port", 5432),
                                 dbname=secret.get("dbname", "sentinel"), user=secret["username"],
                                 password=secret["password"], sslmode="verify-full",
                                 sslrootcert=value("SENTINEL_RDS_CA_FILE"), connect_timeout=5)
        _database_until = time.monotonic() + 300
    return _database
