"""Durable AWS operations share the PostgreSQL queue and serial warmed worker."""
from uuid import UUID, uuid4
from contextlib import nullcontext

from psycopg.types.json import Jsonb

from app.cloud import db, store
from app.cloud.auth import current_user

KINDS = {"start", "scan", "upload", "question", "investigate", "report"}


def queue(case_id, kind, payload=None, request_key=None, *, connection=None):
    if kind not in KINDS:
        raise ValueError("Unknown operation")
    case_id = str(UUID(str(case_id)))
    payload = payload or {}
    if request_key is not None:
        request_key = str(UUID(request_key))
    with (nullcontext(connection) if connection is not None else db.connect()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(str(current_user()["id"]),))
        case = conn.execute("SELECT * FROM cases WHERE id=%s AND owner_id=%s FOR UPDATE",(case_id,current_user()["id"])).fetchone()
        if not case:
            raise KeyError("Review case not found")
        if request_key:
            previous = conn.execute("SELECT id, status, case_id, kind, payload_json FROM jobs WHERE owner_id=%s AND request_key=%s",
                                    (current_user()["id"], request_key)).fetchone()
            if previous:
                if str(previous["case_id"]) != case_id or previous["kind"] != kind or previous["payload_json"] != payload:
                    raise ValueError("This retry key belongs to a different operation")
                return {"job_id": str(previous["id"]), "status": previous["status"]}
        pending = conn.execute("""SELECT id,status FROM jobs WHERE case_id=%s AND kind=%s
            AND payload_json=%s AND status IN ('queued','running') LIMIT 1""", (case_id, kind, Jsonb(payload))).fetchone()
        if pending:
            return {"job_id": str(pending["id"]), "status": pending["status"]}
        count=conn.execute("SELECT count(*) AS n FROM jobs WHERE owner_id=%s AND status IN ('queued','running')",(current_user()["id"],)).fetchone()["n"]
        if count>=4:
            raise ValueError("Wait for your queued operations to finish before starting another")
        if kind == "start":
            if case["status"] != "draft":
                raise ValueError("Review has already started")
            if conn.execute("SELECT 1 FROM uploads WHERE case_id=%s AND status IN ('reserved','queued') AND expires_at>now()", (case_id,)).fetchone():
                raise ValueError("Wait for your files to finish validation")
            kinds = {r["kind"] for r in conn.execute("SELECT kind FROM case_files WHERE case_id=%s", (case_id,))}
            if not {"transactions", "rate_card"}.issubset(kinds):
                raise ValueError("Upload transactions and rate card before starting")
            conn.execute("UPDATE cases SET status='starting' WHERE id=%s", (case_id,))
        elif kind != "upload" and case["status"] != "active":
            raise ValueError("Start the review before running this operation")
        job_id = str(uuid4())
        conn.execute("""INSERT INTO jobs (id,case_id,owner_id,kind,payload_json,request_key)
            VALUES (%s,%s,%s,%s,%s,%s)""", (job_id, case_id, current_user()["id"], kind, Jsonb(payload), request_key))
        return {"job_id": job_id, "status": "queued"}


def perform(job):
    from app.cases import investigation, questions, report, sources, workflow
    case_id = str(job["case_id"])
    payload = job["payload_json"]
    if job["kind"] == "demo":
        from app.cloud.samples import prepare_sample
        return None, prepare_sample(case_id)
    if job["kind"] == "start":
        sources.build_index(case_id)
        store.sync_artifacts(case_id)
        store.mark_started(case_id)
        return None, {"case_id": case_id}
    if job["kind"] == "scan":
        store.ensure_index(case_id, "contract_index")
        result_id = workflow.scan_case(case_id)
        return str(result_id), {"case_id": case_id}
    if job["kind"] == "upload":
        from app.cloud.uploads import validate_upload
        validate_upload(payload["upload_id"])
        return None, store.get_case(case_id)
    if job["kind"] == "question":
        # A retry after a committed answer must return that answer, not call the LLM again.
        with db.connect() as conn:
            previous = conn.execute("SELECT result_id FROM jobs WHERE id=%s", (job["id"],)).fetchone()
        if previous["result_id"]:
            item_id = str(previous["result_id"])
        else:
            result = questions.answer_case_question(case_id, payload["question"], top_k=payload["top_k"])
            # Link answer and job in one transaction so a worker crash cannot duplicate a committed answer.
            item_id = str(uuid4())
            from fastapi.encoders import jsonable_encoder
            with db.connect() as conn:
                conn.execute("""INSERT INTO questions (id,case_id,question,answer,sources_json,confidence_json,presentation_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", (item_id,case_id,payload["question"],result["answer"],
                    Jsonb(jsonable_encoder(result["sources"])),Jsonb(jsonable_encoder(result.get("confidence",{}))),Jsonb(jsonable_encoder(result.get("presentation")))))
                conn.execute("UPDATE jobs SET result_id=%s WHERE id=%s", (item_id, job["id"]))
        return item_id, next(q for q in store.get_case(case_id)["questions"] if q["id"] == item_id)
    if job["kind"] == "investigate":
        return None, investigation.investigate(case_id, payload["finding_id"])
    if job["kind"] == "report":
        case = store.get_case(case_id)
        pdf = report.make_pdf(case)
        store.save_report(case_id, pdf, revision=case["revision"])
        return None, {"case_id": case_id}
    raise ValueError("Unknown operation")
