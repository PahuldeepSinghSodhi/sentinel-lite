"""Start durable cloud jobs on Modal without making local mode depend on it."""

from app.cloud import jobs
from app.cloud.settings import PROVIDER

MODAL_APP_NAME = "sentinel-cloud"
MODAL_WORKER_NAME = "process_jobs"


def queue_and_dispatch(case_id: str, kind: str) -> dict:
    """Persist first, then wake a worker; repeated requests can recover a queue."""
    result = jobs.queue(case_id, kind)
    if PROVIDER == "aws":
        # An always-running worker claims the durable queue; no remote spawn needed.
        return result
    if result["status"] == "queued":
        try:
            import modal

            modal.Function.from_name(MODAL_APP_NAME, MODAL_WORKER_NAME).spawn()
        except Exception as exc:
            # The queued job remains durable. A repeat request or the scheduled
            # recovery function can dispatch it after a transient Modal failure.
            raise RuntimeError("Review queued, but processing could not start; please retry shortly") from exc
    return result
