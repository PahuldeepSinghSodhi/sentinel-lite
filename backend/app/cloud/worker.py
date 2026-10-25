"""Durable review worker used by the on-demand Modal processing function."""
import logging
import os
import shutil
import threading
import time
import traceback
from pathlib import Path
from uuid import UUID

from app.cloud import db, jobs, store
from app.cloud.auth import user_context
from app.cloud.settings import PROVIDER, user_table, validate_settings
from app.cases import sources, workflow

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sentinel.worker")


def record_heartbeat():
    if PROVIDER == "aws":
        with db.connect() as conn:
            conn.execute("""INSERT INTO worker_status(name,updated_at,ready) VALUES ('primary',now(),true)
                ON CONFLICT(name) DO UPDATE SET updated_at=now(), ready=true""")


def run_once() -> bool:
    job = jobs.claim()
    if not job:
        return False
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(60):
            try:
                jobs.extend(job["id"])
                record_heartbeat()
            except Exception:
                log.warning("Could not extend job lease %s", job["id"])
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with db.connect() as conn:
            active = " AND NOT disabled AND email_verified" if PROVIDER == "aws" else ""
            owner = conn.execute(f"SELECT lower(email) AS email FROM {user_table()} WHERE id = %s{active}",
                                 (job["owner_id"],)).fetchone()
            invited = owner and conn.execute("SELECT 1 FROM app_invites WHERE email = %s AND enabled",
                                             (owner["email"],)).fetchone()
        if not invited:
            raise PermissionError("Owner invitation revoked")
        with user_context({"id": job["owner_id"], "email": owner["email"], "role": "reviewer"}, job["id"]):
            # psycopg returns UUID objects for job rows, while case file paths
            # and FAISS scratch paths require a string component.
            case_id = str(job["case_id"])
            if PROVIDER == "aws":
                from app.cloud.aws_jobs import perform
                result_id, result = perform(job)
                jobs.finish(job["id"], result_id, result)
                return True
            elif job["kind"] == "start":
                sources.build_index(case_id)
                store.sync_artifacts(case_id)
                store.mark_started(case_id)
                result_id = None
            else:
                store.ensure_index(case_id, "contract_index")
                result_id = workflow.scan_case(case_id)
        jobs.finish(job["id"], result_id)
        return True
    except Exception as exc:
        # Log only the failure location, never exception text: exception messages
        # may contain source excerpts, credentials, or database connection data.
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        log.error("Job %s failed (%s at %s:%s)", job["id"],
                  type(exc).__name__, Path(frame.filename).name, frame.lineno)
        from app.cloud.uploads import UploadValidationError
        if PROVIDER == "aws" and isinstance(exc, UploadValidationError):
            jobs.fail(job, public_error=str(exc), terminal=True, error_code="upload_invalid")
        elif PROVIDER == "aws" and job["kind"] == "demo" and isinstance(exc, ValueError):
            jobs.fail(job, public_error=str(exc), terminal=True, error_code="sample_invalid")
        elif PROVIDER == "aws" and str(exc) == "Choose and test an AI provider in Settings first":
            jobs.fail(job,public_error="Choose and test an AI provider in Settings first",terminal=True)
        else:
            jobs.fail(job)
        return True
    finally:
        stopped.set()
        thread.join(timeout=1)
        # Each container's scratch holds only temporary processing copies.
        scratch = store.root().resolve()
        target = (scratch / str(UUID(str(job["case_id"])))).resolve()
        if target.parent == scratch:
            shutil.rmtree(target, ignore_errors=True)
        if PROVIDER == "aws":
            # Large PDFs and embedding batches leave free arenas in glibc.
            # Return them to the OS while keeping the warmed model in memory.
            import ctypes
            import gc
            gc.collect()
            trim = getattr(ctypes.CDLL(None), "malloc_trim", None) if os.name != "nt" else None
            if trim:
                trim(0)


def main() -> None:
    validate_settings()
    if PROVIDER == "aws":
        with db.connect() as conn:
            conn.execute("UPDATE worker_status SET ready=false WHERE name='primary'")
        from app.embeddings.model import get_embedding_model
        get_embedding_model().embed_query("Readiness check")
    last_heartbeat = 0
    while True:
        if time.monotonic() - last_heartbeat > 30:
            record_heartbeat()
            last_heartbeat = time.monotonic()
        if not run_once():
            time.sleep(2)


if __name__ == "__main__":
    main()
