"""Quota-reserved direct uploads. Staged objects are validated by the worker before adoption."""
from pathlib import Path
from uuid import UUID, uuid4

from app.cloud import db, objects, store
from app.cloud.auth import current_user
from app.cloud.aws_clients import client
from app.cloud.settings import BUCKET, GLOBAL_LIMIT, USER_LIMIT


class UploadValidationError(ValueError):
    """Safe, owner-visible rejection; retrying the same bytes cannot fix it."""


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
        if case.get("sample_version"):
            raise ValueError("Sample files are fixed. Create a custom case to upload your own files")
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
    try:
        with db.connect() as conn:
            current = conn.execute("SELECT status FROM uploads WHERE id=%s FOR UPDATE", (upload_id,)).fetchone()
            if not current or current["status"] not in {"reserved","queued","completed"}:
                raise ValueError("Upload was cancelled; choose the file again")
            existing = conn.execute("SELECT id,status FROM jobs WHERE case_id=%s AND kind='upload' AND payload_json->>'upload_id'=%s ORDER BY created_at DESC LIMIT 1",(case_id,upload_id)).fetchone()
            if existing:
                return {"job_id":str(existing["id"]),"status":existing["status"]}
            conn.execute("UPDATE uploads SET status='queued' WHERE id=%s", (upload_id,))
            return queue(case_id,"upload",{"upload_id":upload_id},request_key,connection=conn)
    except Exception:
        fail_upload(upload_id, "Upload could not be queued. Choose the file again.", "upload_queue_failed")
        raise


def cancel(case_id, upload_id):
    upload_id = str(UUID(upload_id))
    with db.connect() as conn:
        store._owner(conn, case_id)
        row = conn.execute("SELECT * FROM uploads WHERE id=%s AND case_id=%s AND owner_id=%s FOR UPDATE", (upload_id,case_id,current_user()["id"])).fetchone()
        if not row:
            raise KeyError("Upload not found")
        if row["status"] in {"queued","completed"}:
            raise ValueError("This upload is already being validated or has finished; check its status")
        conn.execute("UPDATE uploads SET status='failed',error='Upload interrupted; choose the file again',error_code='upload_interrupted' WHERE id=%s", (upload_id,))
    objects.delete([row["path"]])


def fail_upload(upload_id, message, code):
    with db.connect() as conn:
        row = conn.execute("UPDATE uploads SET status='failed',error=%s,error_code=%s WHERE id=%s AND status<>'completed' RETURNING path", (message,code,upload_id)).fetchone()
    if row:
        try:
            objects.delete([row["path"]])
        except Exception:
            import logging
            logging.getLogger("sentinel.worker").warning("Staging cleanup deferred for upload %s", upload_id)


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
    if row["status"] != "queued":
        raise UploadValidationError("Upload is no longer pending. Choose the file again")
    try:
        store.save_file(str(row["case_id"]),row["kind"],row["filename"],data)
    except ValueError as exc:
        raise UploadValidationError(str(exc)) from exc
    with db.connect() as conn:
        conn.execute("UPDATE uploads SET status='completed' WHERE id=%s", (upload_id,))
    objects.delete([row["path"]])
