"""Scheduled health metrics and encrypted, key-excluding application recovery copies.

Invoked by fixed Systems Manager documents, never through the public API.
Recovery drills use a new private schema and a unique object prefix; live tables
are never overwritten. Provider keys and authentication sessions are excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.encoders import jsonable_encoder
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from app.cloud import db
from app.cloud.aws_clients import client
from app.cloud.settings import BUCKET, value

TABLES = ("app_users", "auth_identities", "app_invites", "cases", "case_files", "case_artifacts",
          "jobs", "uploads", "scans", "findings", "investigations", "questions", "recovery_model_preferences")
FORMAT = "sentinel-aws-recovery-v1"


def canonical(data):
    return json.dumps(jsonable_encoder(data), sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def key():
    return bytes.fromhex(client("secretsmanager").get_secret_value(
        SecretId=value("SENTINEL_BACKUP_SECRET_ID"))["SecretString"])


def encrypt(secret, data, name):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(secret).encrypt(nonce, data, (FORMAT+":"+name).encode())


def decrypt(secret, data, name):
    return AESGCM(secret).decrypt(data[:12], data[12:], (FORMAT+":"+name).encode())


def metric(name, amount, unit="Count"):
    client("cloudwatch").put_metric_data(Namespace="Sentinel", MetricData=[{
        "MetricName": name, "Value": amount, "Unit": unit}])


def backup():
    bucket = value("SENTINEL_BACKUP_BUCKET")
    prefix = "daily/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + "/"
    secret = key()
    with db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        tables = {table: list(conn.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table))))
                  for table in TABLES}
        # Preserve selection without copying secret values or secret references.
        preferences = list(conn.execute("SELECT owner_id,provider,model,updated_at FROM model_settings"))
        combined = {str(r["owner_id"]): r for r in tables["recovery_model_preferences"]}
        combined.update({str(r["owner_id"]): r for r in preferences})
        tables["recovery_model_preferences"] = list(combined.values())
    paths = sorted({r["path"] for table in ("case_files", "case_artifacts") for r in tables[table]})
    objects = []
    s3 = client("s3")
    for index, path in enumerate(paths):
        response = s3.get_object(Bucket=BUCKET, Key=path)
        try:
            data = response["Body"].read()
        finally:
            response["Body"].close()
        name = f"objects/{index:06}.enc"
        sealed = encrypt(secret, data, name)
        s3.put_object(Bucket=bucket, Key=prefix+name, Body=sealed, ServerSideEncryption="AES256")
        # Read-after-write validates encrypted bytes before publishing completion.
        stored = s3.get_object(Bucket=bucket, Key=prefix+name)["Body"].read()
        if digest(stored) != digest(sealed):
            raise RuntimeError("Recovery object verification failed")
        objects.append({"path": path, "file": name, "size": len(data), "sha256": digest(data)})
    manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
                "tables": tables, "objects": objects}
    sealed = encrypt(secret, canonical(manifest), "manifest")
    s3.put_object(Bucket=bucket, Key=prefix+"manifest.enc", Body=sealed, ServerSideEncryption="AES256")
    published = s3.get_object(Bucket=bucket, Key=prefix+"manifest.enc")["Body"].read()
    if digest(published) != digest(sealed):
        raise RuntimeError("Recovery manifest verification failed")
    s3.put_object(Bucket=bucket, Key=prefix+"COMPLETE.json", Body=canonical({
        "format": FORMAT, "manifest_sha256": digest(sealed), "created_at": manifest["created_at"]}),
        ServerSideEncryption="AES256")
    metric("BackupSuccess", 1)
    print(json.dumps({"backup_prefix": prefix, "counts": {t: len(rows) for t, rows in tables.items()},
                      "objects": len(objects), "bytes": sum(o["size"] for o in objects)}))
    return prefix


def latest():
    objects = [item for page in client("s3").get_paginator("list_objects_v2").paginate(
        Bucket=value("SENTINEL_BACKUP_BUCKET"), Prefix="daily/")
        for item in page.get("Contents", []) if item["Key"].endswith("/COMPLETE.json")]
    return max(objects, key=lambda item: item["LastModified"]) if objects else None


def restore_drill(prefix=None):
    s3, bucket, secret = client("s3"), value("SENTINEL_BACKUP_BUCKET"), key()
    completed = latest()
    prefix = prefix or (completed["Key"].removesuffix("COMPLETE.json") if completed else None)
    if not prefix or not prefix.startswith("daily/") or not prefix.endswith("/"):
        raise ValueError("Select a completed daily backup")
    complete = json.loads(s3.get_object(Bucket=bucket, Key=prefix+"COMPLETE.json")["Body"].read())
    sealed = s3.get_object(Bucket=bucket, Key=prefix+"manifest.enc")["Body"].read()
    if digest(sealed) != complete["manifest_sha256"]:
        raise RuntimeError("Recovery manifest hash mismatch")
    manifest = json.loads(decrypt(secret, sealed, "manifest"))
    if manifest["format"] != FORMAT or set(manifest["tables"]) not in (set(TABLES),set(TABLES)-{"uploads"}):
        raise ValueError("Unsupported recovery schema")
    manifest["tables"].setdefault("uploads", [])
    master = json.loads(client("secretsmanager").get_secret_value(
        SecretId=value("BOOTSTRAP_SECRET"))["SecretString"])
    schema = "restore_" + uuid4().hex
    targets = []
    try:
        with psycopg.connect(host=master["host"], dbname="sentinel", user=master["username"],
                             password=master["password"], sslmode="verify-full",
                             sslrootcert=value("SENTINEL_RDS_CA_FILE"), connect_timeout=10) as conn:
            # No live-table mutation. This transaction is rolled back after comparison.
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            source = Path("/app/aws/schema.sql").read_text().replace("public.", schema+".").replace("SCHEMA public", "SCHEMA "+schema)
            conn.execute(source)
            for table in TABLES:
                records = manifest["tables"][table]
                for row in records:
                    columns = list(row)
                    conn.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns)),
                        [Jsonb(row[c]) if isinstance(row[c], (dict, list)) else row[c] for c in columns])
            # Insert triggers bump revisions; restore their captured values before comparison.
            for row in manifest["tables"]["cases"]:
                conn.execute(sql.SQL("UPDATE {}.cases SET revision=%s WHERE id=%s").format(sql.Identifier(schema)), (row["revision"], row["id"]))
            for table, expected in manifest["tables"].items():
                actual = [r[0] for r in conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {}.{} t").format(sql.Identifier(schema), sql.Identifier(table)))]
                # PostgreSQL timestamp JSON uses an offset; normalize temporal strings.
                def normalized(row):
                    return {k: (datetime.fromisoformat(v).isoformat() if isinstance(v, str) and k in {
                        "created_at", "updated_at", "started_at", "uploaded_at", "decided_at", "leased_until", "expires_at"} and v else v)
                        for k,v in row.items()}
                captured = set(expected[0]) if expected else set()
                if sorted(canonical(normalized({k:r[k] for k in captured})) for r in actual) != sorted(canonical(normalized(r)) for r in expected):
                    raise RuntimeError("Restored table comparison failed: "+table)
            for obj in manifest["objects"]:
                sealed = s3.get_object(Bucket=bucket, Key=prefix+obj["file"])["Body"].read()
                data = decrypt(secret, sealed, obj["file"])
                if len(data) != obj["size"] or digest(data) != obj["sha256"]:
                    raise RuntimeError("Restored object hash mismatch")
                target = "restore-drills/"+schema+"/"+obj["file"]
                targets.append(target)
                s3.put_object(Bucket=BUCKET, Key=target, Body=data, ServerSideEncryption="AES256")
                if digest(s3.get_object(Bucket=BUCKET, Key=target)["Body"].read()) != obj["sha256"]:
                    raise RuntimeError("Restored S3 object verification failed")
            conn.rollback()
        metric("RestoreDrillSuccess", 1)
        print(json.dumps({"restore_verified": True, "backup_prefix": prefix,
                          "table_counts": {t: len(rows) for t,rows in manifest["tables"].items()}, "objects": len(targets)}))
    finally:
        for target in targets:
            s3.delete_object(Bucket=BUCKET, Key=target)


def monitor():
    import requests
    try:
        ready=requests.get(value("SENTINEL_API_HEALTH_URL"),timeout=10).status_code==200
    except requests.RequestException:
        ready=False
    metric("APIReady",int(ready))
    with db.connect() as conn:
        worker = conn.execute("SELECT extract(epoch FROM now()-updated_at) AS age FROM worker_status WHERE name='primary' AND ready").fetchone()
        metric("WorkerAgeSeconds", float(worker["age"]) if worker else 86400, "Seconds")
        metric("FailedJobs24h", conn.execute("SELECT count(*) AS n FROM jobs WHERE status='failed' AND updated_at>now()-interval '24 hours'").fetchone()["n"])
        metric("OldestPendingSeconds", float(conn.execute("SELECT COALESCE(extract(epoch FROM now()-min(created_at)),0) AS age FROM jobs WHERE status IN ('queued','running')").fetchone()["age"]), "Seconds")
        conn.execute("UPDATE uploads SET status='expired' WHERE status='reserved' AND expires_at<now()")
    completed = latest()
    age = (datetime.now(timezone.utc)-completed["LastModified"]).total_seconds() if completed else 864000
    metric("BackupAgeSeconds", age, "Seconds")
    import boto3
    from botocore.config import Config
    plan=boto3.client("freetier",region_name="us-east-1",config=Config(connect_timeout=5,read_timeout=10,retries={"max_attempts":2})).get_account_plan_state()
    metric("RemainingCreditsUSD",float(plan["accountPlanRemainingCredits"]["amount"]),"None")
    metric("FreePlanActive",int(plan["accountPlanType"]=="FREE" and plan["accountPlanStatus"]=="ACTIVE"))
    if Path("/host-meminfo").exists():
        fields = dict(line.split(":",1) for line in Path("/host-meminfo").read_text().splitlines())
        metric("AvailableMemoryMiB", int(fields["MemAvailable"].split()[0])/1024, "Megabytes")
    if Path("/host-root").exists():
        usage = os.statvfs("/host-root")
        metric("DiskFreePercent", 100*usage.f_bavail/usage.f_blocks, "Percent")
    metric("MonitorSuccess", 1)
    print('{"monitor":"completed"}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "monitor", "restore-drill"])
    parser.add_argument("--prefix")
    args = parser.parse_args()
    try:
        {"backup": backup, "monitor": monitor, "restore-drill": lambda: restore_drill(args.prefix)}[args.action]()
    except Exception as exc:
        # Exception values can contain credentials/SQL parameters, so only log type.
        metric("OperationFailure", 1)
        print(json.dumps({"operation_failed": args.action, "error_type": type(exc).__name__}))
        raise SystemExit(1)
