"""Durable review worker used by the on-demand Modal processing function."""
import logging
import shutil
import threading
import time
import traceback
from pathlib import Path
from uuid import UUID

from app.cloud import db, jobs, store
from app.cloud.auth import user_context
from app.cloud.settings import validate_settings
from app.cases import sources, workflow

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sentinel.worker")


def run_once() -> bool:
    job = jobs.claim()
    if not job:
        return False
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(60):
            try:
                jobs.extend(job["id"])
            except Exception:
                log.warning("Could not extend job lease %s", job["id"])
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with db.connect() as conn:
            owner = conn.execute("SELECT lower(email) AS email FROM auth.users WHERE id = %s",
                                 (job["owner_id"],)).fetchone()
            invited = owner and conn.execute("SELECT 1 FROM app_invites WHERE email = %s AND enabled",
                                             (owner["email"],)).fetchone()
        if not invited:
            raise PermissionError("Owner invitation revoked")
        with user_context({"id": job["owner_id"], "email": owner["email"], "role": "reviewer"}, job["id"]):
            # psycopg returns UUID objects for job rows, while case file paths
            # and FAISS scratch paths require a string component.
            case_id = str(job["case_id"])
            if job["kind"] == "start":
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


def main() -> None:
    validate_settings()
    while True:
        if not run_once():
            time.sleep(2)


if __name__ == "__main__":
    main()
