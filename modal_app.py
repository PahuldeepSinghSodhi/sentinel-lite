"""On-demand Modal deployment for Sentinel's invite-only cloud mode.

Deploy only after verifying a Starter workspace and a hard usage/spend cap
that cannot exceed the included monthly credit. Do not put secrets here.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent
APP_NAME = "sentinel-cloud"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(ROOT / "backend" / "requirements.txt"))
    .pip_install("modal==1.6.2")
    .env({"SENTINEL_MODE": "cloud"})
    .add_local_dir(str(ROOT / "backend" / "app"), remote_path="/root/app")
    .add_local_dir(str(ROOT / "backend" / "data"), remote_path="/root/data")
)

secret = modal.Secret.from_name(
    "sentinel-cloud",
    required_keys=[
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
        "SENTINEL_FRONTEND_ORIGIN",
    ],
)
app = modal.App(APP_NAME)


@app.function(image=image, secrets=[secret], cpu=0.5, memory=2048,
              max_containers=1, scaledown_window=10, timeout=180)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def api():
    from app.main import app as fastapi_app

    return fastapi_app


@app.function(image=image, secrets=[secret], cpu=1.0, memory=4096,
              max_containers=1, scaledown_window=10, timeout=900)
def process_jobs():
    from app.cloud.settings import validate_settings
    from app.cloud.worker import run_once

    validate_settings()
    # Bound each invocation; the recovery function picks up any remainder.
    for _ in range(8):
        if not run_once():
            break


@app.function(image=image, secrets=[secret], cpu=0.125, memory=512,
              scaledown_window=10, schedule=modal.Period(hours=1), timeout=60)
def recover_jobs():
    """Wake one worker for jobs left behind by a transient dispatch/crash."""
    from app.cloud import jobs
    from app.cloud.settings import validate_settings

    validate_settings()
    if jobs.has_due():
        process_jobs.spawn()
