"""Encrypted application backup and isolated PostgreSQL restore. Never writes to the source.

Run with Python 3.12+ and scripts/requirements-recovery.txt. Credentials are read
from a local dotenv file, never command arguments or logs. This intentionally is
not a Supabase platform/auth-session/Vault dump.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import sys
from urllib.parse import quote, urlparse
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import requests

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "sentinel-recovery-v1"
# An explicit allowlist prevents schema additions from silently exporting secrets.
TABLES = {
    "auth.users": "id email created_at updated_at email_confirmed_at banned_until deleted_at is_anonymous",
    "auth.identities": "id user_id provider provider_id created_at updated_at",
    "public.app_invites": "email role enabled created_at",
    "public.cases": "id owner_id name status created_at started_at",
    "public.case_files": "case_id kind filename extension size path uploaded_at",
    "public.case_artifacts": "case_id name path size",
    "public.jobs": "id case_id owner_id kind status attempts leased_until result_id error created_at updated_at",
    "public.scans": "id case_id job_id created_at transactions_analyzed duration_ms",
    "public.findings": "id scan_id ordinal data_json decision note decided_at",
    "public.investigations": "finding_id payload_json",
    "public.questions": "id case_id created_at question answer sources_json confidence_json presentation_json",
    "public.model_settings": "owner_id provider model updated_at",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def protect_dir(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # whoami CSV is parsed rather than shell-expanded account names.
        import csv
        sid = next(csv.reader(subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], text=True).splitlines()))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       check=True, capture_output=True)
    else:
        path.chmod(0o700)
    return path


def dpapi(value, decrypt=False):
    if os.name != "nt":
        raise ValueError("DPAPI keys require Windows; use a password-wrapped recovery key on other systems")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, output = Blob(len(value), buffer), Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("Windows could not unlock this recovery key")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def seal(key, data, name):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, (FORMAT + ":" + name).encode())


def unseal(key, data, name):
    return AESGCM(key).decrypt(data[:12], data[12:], (FORMAT + ":" + name).encode())


def read_key(path):
    data = Path(path).read_bytes()
    if data.startswith(b"DPAPI1\n"):
        return dpapi(data[7:], decrypt=True)
    if data.startswith(b"SCRYPT1\n"):
        salt, body = data[8:24], data[24:]
        password = getpass.getpass("Recovery key password: ").encode()
        wrapping = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password)
        return unseal(wrapping, body, "portable-key")
    raise ValueError("Unknown recovery key format")


def read_rows(conn):
    public = {name.split(".")[1]: set(columns.split()) for name, columns in TABLES.items()
              if name.startswith("public.")}
    actual = {}
    for table, column in conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"):
        actual.setdefault(table, set()).add(column)
    expected = {**public, "model_settings": public["model_settings"] | {"vault_id"}}
    if actual != expected:
        raise ValueError("Application schema changed; update the export allowlist before taking a backup")
    result = {}
    for name, columns in TABLES.items():
        schema, table = name.split(".")
        query = sql.SQL("SELECT to_jsonb(t) FROM (SELECT {} FROM {}.{}) t").format(
            sql.SQL(",").join(map(sql.Identifier, columns.split())),
            sql.Identifier(schema), sql.Identifier(table))
        result[name] = sorted((r[0] for r in conn.execute(query)), key=canonical)
    return result


def inventory(conn, bucket):
    return [r[0] for r in conn.execute("""SELECT jsonb_build_object(
        'id', id, 'name', name, 'version', version, 'updated_at', updated_at,
        'size', (metadata->>'size')::bigint) FROM storage.objects
        WHERE bucket_id=%s ORDER BY name""", (bucket,))]


def snapshot(conn, bucket):
    # One consistent DB snapshot. Storage consistency is checked again afterwards.
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    conn.execute("SET LOCAL statement_timeout='30s'")
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    return read_rows(conn), inventory(conn, bucket)


def validate_path(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe object path")


def validate_records(rows, objects):
    if set(rows) != set(TABLES):
        raise ValueError("Unexpected table inventory")
    for name, records in rows.items():
        expected = set(TABLES[name].split())
        if any(set(row) != expected for row in records):
            raise ValueError("Unexpected or missing columns: " + name)
    sizes = {o["name"]: o["size"] for o in objects}
    if len(sizes) != len(objects):
        raise ValueError("Duplicate object names")
    for name in sizes:
        validate_path(name)
    for table in ("public.case_files", "public.case_artifacts"):
        for row in rows[table]:
            if row["path"] not in sizes or sizes[row["path"]] != row["size"]:
                raise ValueError("Missing or mismatched referenced object")


def backup(env_file, destination, key_dir):
    dest = Path(destination).resolve()
    if dest == ROOT or ROOT in dest.parents:
        raise ValueError("Backups must be outside the repository")
    if dest.exists():
        raise ValueError("Choose a new backup directory")
    env = dotenv_values(env_file)
    url = env["SUPABASE_URL"].rstrip("/")
    if urlparse(url).scheme != "https" or not (urlparse(url).hostname or "").endswith(".supabase.co"):
        raise ValueError("Expected an HTTPS Supabase project endpoint")
    source = env["SUPABASE_DB_URL"]
    bucket = env.get("SENTINEL_STORAGE_BUCKET") or "sentinel-private"
    dest = protect_dir(dest)
    protect_dir(dest / "objects")
    key_dir = protect_dir(key_dir)
    key = secrets.token_bytes(32)
    key_file = key_dir / (dest.name + ".key.dpapi")
    with key_file.open("xb") as f:
        f.write(b"DPAPI1\n" + dpapi(key))
    with psycopg.connect(source, connect_timeout=15) as conn:
        rows, objects = snapshot(conn, bucket)
    validate_records(rows, objects)
    headers = {"apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
               "Authorization": "Bearer " + env["SUPABASE_SERVICE_ROLE_KEY"]}
    files = []
    for i, obj in enumerate(objects):
        # Object names never become local paths. Each blob has its own authenticated ciphertext.
        name = f"objects/{i:06d}.enc"
        response = requests.get(
            f"{url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(obj['name'], safe='/')}",
            headers=headers, timeout=90)
        if response.status_code != 200:
            raise ValueError(f"Private object download failed ({response.status_code})")
        data = response.content
        if len(data) != obj["size"]:
            raise ValueError("Downloaded object size mismatch")
        (dest / name).write_bytes(seal(key, data, name))
        files.append({**obj, "file": name, "sha256": digest(data)})
    # Fail closed if a review/upload/worker changed either DB rows or storage metadata.
    with psycopg.connect(source, connect_timeout=15) as conn:
        after_rows, after_objects = snapshot(conn, bucket)
    if canonical((rows, objects)) != canonical((after_rows, after_objects)):
        raise ValueError("Source changed during capture; backup is incomplete. Retry when idle")
    schema = (ROOT / "backend/migrations/001_cloud.sql").read_bytes()
    (dest / "schema.enc").write_bytes(seal(key, schema, "schema.enc"))
    manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
                "source": urlparse(url).hostname, "bucket": bucket, "tables": rows,
                "objects": files, "schema_sha256": digest(schema),
                "excluded": ["Vault secrets", "password hashes", "sessions", "refresh/access tokens", "deployment credentials"],
                "source_consistent": True}
    (dest / "manifest.enc").write_bytes(seal(key, canonical(manifest), "manifest.enc"))
    summary = verify(dest, key_file)
    (dest / "verification.json").write_bytes(canonical(summary))
    print(json.dumps({**summary, "backup_directory": str(dest), "key_file": str(key_file)}))


def load_backup(directory, key_file):
    dest, key = Path(directory).resolve(), read_key(key_file)
    manifest = json.loads(unseal(key, (dest / "manifest.enc").read_bytes(), "manifest.enc"))
    if manifest["format"] != FORMAT or not manifest["source_consistent"]:
        raise ValueError("Incomplete or unsupported backup")
    validate_records(manifest["tables"], manifest["objects"])
    return dest, key, manifest


def verify(directory, key_file):
    dest, key, manifest = load_backup(directory, key_file)
    schema = unseal(key, (dest / "schema.enc").read_bytes(), "schema.enc")
    if digest(schema) != manifest["schema_sha256"]:
        raise ValueError("Schema hash mismatch")
    names = set()
    for obj in manifest["objects"]:
        name = obj["file"]
        if name in names or not name.startswith("objects/") or not name.endswith(".enc"):
            raise ValueError("Invalid encrypted object location")
        validate_path(name)
        names.add(name)
        data = unseal(key, (dest / name).read_bytes(), name)
        if len(data) != obj["size"] or digest(data) != obj["sha256"]:
            raise ValueError("Object hash mismatch")
    return {"verified": True, "tables": {name: len(rows) for name, rows in manifest["tables"].items()},
            "objects": len(names), "object_bytes": sum(o["size"] for o in manifest["objects"]),
            "source_consistent": True, "provider_keys_excluded": True}


def restore(directory, key_file, admin_url, object_directory):
    """Restore only into a NEW database on a loopback PostgreSQL server.

    This is a data recovery rehearsal, not a deployed Supabase clone. Accounts
    and provider preferences are preserved; login and provider keys need setup.
    """
    verify(directory, key_file)
    dest, key, manifest = load_backup(directory, key_file)
    info = psycopg.conninfo.conninfo_to_dict(admin_url)
    if info.get("host") not in ("127.0.0.1", "::1", "localhost") or info.get("hostaddr", info["host"]) not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("Restore is restricted to a local PostgreSQL server")
    target = Path(object_directory).resolve()
    if target.exists() or target == ROOT or ROOT in target.parents:
        raise ValueError("Use a new restore directory outside the repository")
    target = protect_dir(target)
    name = "sentinel_restore_" + uuid4().hex[:16]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        if str(admin.execute("SELECT inet_server_addr()").fetchone()[0]) not in ("127.0.0.1", "::1"):
            raise ValueError("Restore server must be loopback-only")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    info["dbname"] = name
    schema = unseal(key, (dest / "schema.enc").read_bytes(), "schema.enc").decode()
    # Reuse actual table constraints, indexes and FKs. Supabase policies/hooks and
    # storage schema remain platform configuration, not part of the local clone.
    schema = schema.split("-- Only the trusted API", 1)[0]
    with psycopg.connect(**info) as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid PRIMARY KEY, email text, created_at timestamptz, updated_at timestamptz, email_confirmed_at timestamptz, banned_until timestamptz, deleted_at timestamptz, is_anonymous boolean)")
        conn.execute("CREATE TABLE auth.identities (id uuid PRIMARY KEY, user_id uuid REFERENCES auth.users(id), provider text, provider_id text, created_at timestamptz, updated_at timestamptz)")
        conn.execute(schema)
        conn.execute("CREATE TABLE public.recovery_model_preferences (owner_id uuid PRIMARY KEY REFERENCES auth.users(id), provider text, model text, updated_at timestamptz)")
        # JSON keys are sorted for hashing. Restore in FK order, not JSON order.
        for table in TABLES:
            records = manifest["tables"][table]
            schema_name, table_name = table.split(".")
            if table_name == "model_settings":
                table_name = "recovery_model_preferences"
            for row in records:
                columns = list(row)
                values = [Jsonb(row[c]) if isinstance(row[c], (dict, list)) else row[c] for c in columns]
                conn.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                    sql.Identifier(schema_name), sql.Identifier(table_name),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns)), values)
        # Compare actual restored values, not just insertion counts.
        for table, expected in manifest["tables"].items():
            schema_name, table_name = table.split(".")
            if table_name == "model_settings":
                table_name = "recovery_model_preferences"
            actual = [r[0] for r in conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {}.{} t").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)))]
            if canonical(sorted(actual, key=canonical)) != canonical(sorted(expected, key=canonical)):
                raise ValueError("Restored row mismatch: " + table)
    for i, obj in enumerate(manifest["objects"]):
        data = unseal(key, (dest / obj["file"]).read_bytes(), obj["file"])
        # Flat names avoid Windows reserved names and path traversal entirely.
        path = target / f"{i:06d}.blob"
        path.write_bytes(data)
        if digest(path.read_bytes()) != obj["sha256"]:
            raise ValueError("Restored file hash mismatch")
    (target / "object-map.json").write_bytes(canonical([
        {"file": f"{i:06d}.blob", "original_name": obj["name"], "sha256": obj["sha256"]}
        for i, obj in enumerate(manifest["objects"])]))
    report = {**verify(directory, key_file), "restored_database": name,
              "restored_values_match": True, "restored_files_match": True,
              "login_reconfiguration_required": True, "provider_key_reentry_required": True}
    (dest / "restore-verification.json").write_bytes(canonical(report))
    print(json.dumps(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("backup")
    b.add_argument("--env-file", type=Path, default=ROOT / "backend/.env.cloud")
    b.add_argument("--destination", type=Path, required=True)
    b.add_argument("--key-directory", type=Path, default=Path.home() / ".sentinel-recovery-keys")
    for command in ("verify", "restore", "export-key"):
        p = commands.add_parser(command)
        p.add_argument("--key-file", type=Path, required=True)
        if command != "export-key":
            p.add_argument("--backup", type=Path, required=True)
        if command == "restore":
            p.add_argument("--local-admin-env", type=Path, required=True,
                           help="Dotenv containing LOCAL_RESTORE_DB_URL; loopback only")
            p.add_argument("--object-directory", type=Path, required=True)
        if command == "export-key":
            p.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            backup(args.env_file, args.destination, args.key_directory)
        elif args.command == "verify":
            print(json.dumps(verify(args.backup, args.key_file)))
        elif args.command == "restore":
            restore(args.backup, args.key_file,
                    dotenv_values(args.local_admin_env)["LOCAL_RESTORE_DB_URL"], args.object_directory)
        else:
            password = getpass.getpass("New portable recovery password (at least 16 characters): ")
            if len(password) < 16 or password != getpass.getpass("Repeat password: "):
                raise ValueError("Password too short or does not match")
            salt = secrets.token_bytes(16)
            wrapping = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode())
            protect_dir(args.destination.parent)
            with args.destination.open("xb") as f:
                f.write(b"SCRYPT1\n" + salt + seal(wrapping, read_key(args.key_file), "portable-key"))
            print("Password-protected portable recovery key exported")
    except Exception as exc:
        # Never print exception text: network/DB exceptions can contain credentials or private rows.
        reason = str(exc) if type(exc) is ValueError else type(exc).__name__
        print("Recovery operation failed: " + reason + ". No source data was changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
