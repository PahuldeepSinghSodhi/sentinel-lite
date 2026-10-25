"""Durable, idempotent review jobs stored in Postgres."""
from uuid import UUID, uuid4

from app.cloud import db
from app.cloud.auth import current_user
from app.cloud.settings import PROVIDER


def queue(case_id: str, kind: str) -> dict:
    if PROVIDER == "aws":
        from app.cloud.aws_jobs import queue as aws_queue
        return aws_queue(case_id, kind)
    if kind not in {"start", "scan"}:
        raise ValueError("Unknown job type")
    owner_id = current_user()["id"]
    with db.connect() as conn:
        case = conn.execute("SELECT status FROM cases WHERE id = %s AND owner_id = %s FOR UPDATE",
                            (case_id, owner_id)).fetchone()
        if not case:
            raise KeyError("Review case not found")
        pending = conn.execute("""SELECT id, status FROM jobs WHERE case_id = %s AND kind = %s
                                  AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1""",
                               (case_id, kind)).fetchone()
        if pending:
            return {"job_id": pending["id"], "status": pending["status"]}
        if kind == "start":
            if case["status"] != "draft":
                raise ValueError("Review has already started")
            kinds = {row["kind"] for row in conn.execute(
                "SELECT kind FROM case_files WHERE case_id = %s", (case_id,))}
            if not {"transactions", "rate_card"}.issubset(kinds):
                raise ValueError("Upload transactions and rate card before starting")
            conn.execute("UPDATE cases SET status = 'starting' WHERE id = %s", (case_id,))
        elif case["status"] != "active":
            raise ValueError("Start the review before scanning")
        job_id = str(uuid4())
        conn.execute("INSERT INTO jobs (id, case_id, owner_id, kind) VALUES (%s, %s, %s, %s)",
                     (job_id, case_id, owner_id, kind))
        return {"job_id": job_id, "status": "queued"}


def get(job_id: str) -> dict:
    try:
        job_id = str(UUID(str(job_id)))
    except ValueError as exc:
        raise KeyError("Job not found") from exc
    with db.connect() as conn:
        columns = "id, case_id, kind, status, attempts, result_id, error, created_at, updated_at"
        if PROVIDER == "aws":
            columns += ", result_json, error_code"
        row = conn.execute(f"SELECT {columns} FROM jobs WHERE id = %s AND owner_id = %s",
                           (job_id, current_user()["id"])).fetchone()
    if not row:
        raise KeyError("Job not found")
    return {"job_id": row.pop("id"), **row}


def has_due() -> bool:
    """Check whether the scheduled recovery function needs to wake a worker."""
    with db.connect() as conn:
        row = conn.execute("""SELECT 1 FROM jobs WHERE
                              (status = 'queued' AND (leased_until IS NULL OR leased_until < now()))
                              OR (status = 'running' AND leased_until < now())
                              LIMIT 1""").fetchone()
    return row is not None


def claim() -> dict | None:
    with db.connect() as conn:
        # A worker can die during its last attempt without calling fail().
        # Expired final leases must become visible failures, not run forever.
        exhausted = list(conn.execute("""UPDATE jobs SET status = 'failed', leased_until = null,
                             error = 'Processing stopped after three attempts', updated_at = now()
                             WHERE status = 'running' AND leased_until < now() AND attempts >= 3
                             RETURNING case_id, kind, id"""))
        for item in exhausted:
            if PROVIDER == "aws" and item["kind"] == "upload":
                conn.execute("UPDATE uploads SET status='failed' WHERE id=(SELECT (payload_json->>'upload_id')::uuid FROM jobs WHERE id=%s)", (item["id"],))
            if item["kind"] in {"start","demo"}:
                conn.execute("UPDATE cases SET status = 'draft' WHERE id = %s AND status = 'starting'",
                             (item["case_id"],))
        row = conn.execute("""SELECT * FROM jobs WHERE
                              ((status = 'queued' AND (leased_until IS NULL OR leased_until < now()))
                               OR (status = 'running' AND leased_until < now()))
                              AND attempts < 3 ORDER BY created_at
                              LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
        if not row:
            return None
        conn.execute("""UPDATE jobs SET status = 'running', attempts = attempts + 1,
                        leased_until = now() + interval '15 minutes', updated_at = now()
                        WHERE id = %s""", (row["id"],))
        row["attempts"] += 1
        row["status"] = "running"
        return row


def finish(job_id: str, result_id: str | None = None, result: dict | None = None) -> None:
    with db.connect() as conn:
        if PROVIDER == "aws":
            from psycopg.types.json import Jsonb
            from fastapi.encoders import jsonable_encoder
            conn.execute("""UPDATE jobs SET status='completed', result_id=%s, result_json=%s, error=null,
                leased_until=null, updated_at=now() WHERE id=%s""", (result_id, Jsonb(jsonable_encoder(result)), job_id))
            return
        conn.execute("""UPDATE jobs SET status = 'completed', result_id = %s, error = null,
                        leased_until = null, updated_at = now() WHERE id = %s""", (result_id, job_id))


def extend(job_id: str) -> None:
    with db.connect() as conn:
        conn.execute("""UPDATE jobs SET leased_until = now() + interval '15 minutes', updated_at = now()
                        WHERE id = %s AND status = 'running'""", (job_id,))


def fail(job: dict, public_error: str | None = None, *, terminal=False, error_code=None) -> None:
    final = terminal or job["attempts"] >= 3
    with db.connect() as conn:
        conn.execute("""UPDATE jobs SET status = %s,
                        leased_until = CASE WHEN %s THEN null ELSE now() + interval '1 minute' END,
                        error = %s, updated_at = now() WHERE id = %s""",
                     ("failed" if final else "queued", final,
                      (public_error or "Processing failed; retry or contact the administrator") if final else None,
                      job["id"]))
        if PROVIDER == "aws":
            conn.execute("UPDATE jobs SET error_code=%s WHERE id=%s", (error_code if final else None,job["id"]))
        if final and job["kind"] in {"start","demo"}:
            conn.execute("UPDATE cases SET status = 'draft' WHERE id = %s AND status = 'starting'",
                         (job["case_id"],))
    if final and PROVIDER == "aws" and job["kind"] == "upload":
        from app.cloud.uploads import fail_upload
        fail_upload(job["payload_json"]["upload_id"], public_error or "Validation could not finish; choose the file again", error_code or "upload_failed")
