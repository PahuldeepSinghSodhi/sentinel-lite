"""Quota-reserved direct uploads. Staged objects are validated by the worker before adoption."""
from pathlib import Path
from uuid import UUID, uuid4

from app.cloud import db, objects, store
from app.cloud.auth import current_user
from app.cloud.aws_clients import client
from app.cloud.settings import BUCKET, GLOBAL_LIMIT, USER_LIMIT


def authorize(case_id, kind, filename, size):
    from app.cases.store import FILE_RULES, MAX_FILE_BYTES
    extension = Path(filename).suffix.lower()
    if kind not in FILE_RULES or extension not in FILE_RULES[kind]["extensions"] or not 0 < size <= MAX_FILE_BYTES:
        raise ValueError("Choose a supported file up to 10 MiB")
    owner = current_user()["id"]
    upload_id = str(uuid4())
    path = f"staging/{owner}/{case_id}/{upload_id}{extension}"
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7281901)")
        conn.execute("UPDATE uploads SET status='expired' WHERE status='reserved' AND expires_at<now()")
        case = store._owner(conn, case_id)
        if case["status"] != "draft":
            raise ValueError("Files are locked after review starts")
        if conn.execute("SELECT 1 FROM uploads WHERE case_id=%s AND kind=%s AND status IN ('reserved','queued')", (case_id,kind)).fetchone():
            raise ValueError("This file is already uploading or being validated")
        own, total = store._usage(conn, owner)
        reserved = conn.execute("""SELECT COALESCE(sum(size),0) AS total,
            COALESCE(sum(size) FILTER (WHERE owner_id=%s),0) AS own FROM uploads WHERE status IN ('reserved','queued')""", (owner,)).fetchone()
        if own + reserved["own"] + size > USER_LIMIT or total + reserved["total"] + size > GLOBAL_LIMIT:
            raise ValueError("Cloud storage limit reached; delete an unused case before uploading")
        conn.execute("""INSERT INTO uploads(id,case_id,owner_id,kind,filename,extension,size,path,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'reserved')""", (upload_id,case_id,owner,kind,Path(filename).name[:200],extension,size,path))
    ticket = client("s3").generate_presigned_post(Bucket=BUCKET, Key=path,
        Fields={"x-amz-server-side-encryption":"AES256"},
        Conditions=[["content-length-range",size,size],{"x-amz-server-side-encryption":"AES256"}], ExpiresIn=300)
    return {"upload_id":upload_id,**ticket}


def confirm(case_id, upload_id, request_key=None):
    from app.cloud.aws_jobs import queue
    upload_id = str(UUID(upload_id))
    with db.connect() as conn:
        store._owner(conn, case_id)
        row = conn.execute("SELECT * FROM uploads WHERE id=%s AND case_id=%s AND owner_id=%s AND expires_at>now()",
                           (upload_id,case_id,current_user()["id"])).fetchone()
    if not row or row["status"] not in {"reserved","queued","completed"}:
        raise ValueError("Upload expired; choose the file again")
    if row["status"] != "completed":
        info = client("s3").head_object(Bucket=BUCKET, Key=row["path"])
        if info["ContentLength"] != row["size"]:
            raise ValueError("Upload size mismatch")
    job = queue(case_id,"upload",{"upload_id":upload_id},request_key)
    with db.connect() as conn:
        conn.execute("UPDATE uploads SET status='queued' WHERE id=%s AND status='reserved'", (upload_id,))
    return job


def validate_upload(upload_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id=%s AND owner_id=%s", (upload_id,current_user()["id"])).fetchone()
    if not row:
        raise KeyError("Upload not found")
    if row["status"] == "completed":
        return
    data = objects.get(row["path"])
    if len(data) != row["size"]:
        raise ValueError("Upload size mismatch")
    store.save_file(str(row["case_id"]),row["kind"],row["filename"],data)
    with db.connect() as conn:
        conn.execute("UPDATE uploads SET status='completed' WHERE id=%s", (upload_id,))
    objects.delete([row["path"]])
