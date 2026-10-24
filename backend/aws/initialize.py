"""One-time, private RDS bootstrap/import, executed only through Systems Manager.

Reads short-lived migration inputs from encrypted S3/Secrets Manager. Never logs
credentials, user emails, source text, or SQL parameter values.
"""
import hashlib
import json
import os
from pathlib import Path

import boto3
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


def main():
    region = os.environ["AWS_REGION"]
    secrets = boto3.client("secretsmanager",region_name=region)
    s3 = boto3.client("s3",region_name=region)
    master = json.loads(secrets.get_secret_value(SecretId=os.environ["BOOTSTRAP_SECRET"])["SecretString"])
    application = json.loads(secrets.get_secret_value(SecretId=os.environ["DATABASE_SECRET"])["SecretString"])
    key = bytes.fromhex(secrets.get_secret_value(SecretId=os.environ["MIGRATION_SECRET"])["SecretString"])
    encrypted = s3.get_object(Bucket=os.environ["BUCKET"],Key=os.environ["IMPORT_KEY"])["Body"].read()
    payload = json.loads(AESGCM(key).decrypt(encrypted[:12],encrypted[12:],b"sentinel-aws-import-v1"))
    for obj in payload["objects"]:
        body = s3.get_object(Bucket=os.environ["BUCKET"],Key=obj["name"])["Body"]
        hasher = hashlib.sha256()
        count = 0
        try:
            for block in body.iter_chunks(1024*1024):
                hasher.update(block)
                count += len(block)
        finally:
            body.close()
        if count != obj["size"] or hasher.hexdigest() != obj["sha256"]:
            raise RuntimeError("Transferred object integrity check failed")
    with psycopg.connect(host=master["host"],port=5432,dbname="sentinel",user=master["username"],password=master["password"],
                         sslmode="verify-full",sslrootcert="/app/aws/rds-ca.pem",connect_timeout=10) as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s",(application["username"],)).fetchone():
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(application["username"]),sql.Literal(application["password"])))
        conn.execute(Path("/app/aws/schema.sql").read_text())
        for table, records in payload["tables"].items():
            primary = {"auth_identities":["issuer","subject"],"app_invites":["email"],"case_files":["case_id","kind"],
                       "case_artifacts":["case_id","name"],"investigations":["finding_id"],"recovery_model_preferences":["owner_id"]}.get(table,["id"])
            for row in records:
                columns = list(row)
                mutable = [c for c in columns if c not in primary]
                action = sql.SQL("DO UPDATE SET ") + sql.SQL(",").join(
                    sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c),sql.Identifier(c)) for c in mutable) if mutable else sql.SQL("DO NOTHING")
                conn.execute(sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) ON CONFLICT ({}) ").format(
                    sql.Identifier(table),sql.SQL(",").join(map(sql.Identifier,columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),sql.SQL(",").join(map(sql.Identifier,primary))) + action,
                    [Jsonb(row[c]) if isinstance(row[c],(list,dict)) else row[c] for c in columns])
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE sentinel TO {}").format(sql.Identifier(application["username"])))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(application["username"])))
        conn.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(application["username"])))
        conn.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(application["username"])))
        # Verify imported values individually; additional staging rows are not silently deleted.
        for table, records in payload["tables"].items():
            for row in records:
                primary = {"auth_identities":["issuer","subject"],"app_invites":["email"],"case_files":["case_id","kind"],
                           "case_artifacts":["case_id","name"],"investigations":["finding_id"],"recovery_model_preferences":["owner_id"]}.get(table,["id"])
                query = sql.SQL("SELECT to_jsonb(t) FROM public.{} t WHERE ").format(sql.Identifier(table)) + sql.SQL(" AND ").join(
                    sql.SQL("{}=%s").format(sql.Identifier(c)) for c in primary)
                actual = conn.execute(query,[row[c] for c in primary]).fetchone()[0]
                if any(actual[c] != value for c,value in row.items()):
                    raise RuntimeError("Imported record comparison failed: " + table)
    print(json.dumps({"imported_tables":{table:len(rows) for table,rows in payload["tables"].items()},
                      "verified_objects":len(payload["objects"]),"verified_values":True,"provider_keys_imported":False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Initialization failed: " + (str(exc) if type(exc) is RuntimeError else type(exc).__name__))
        raise SystemExit(1)
