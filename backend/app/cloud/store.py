"""Cloud case repository with mandatory owner checks and private object storage."""
import os
import shutil
import tempfile
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from app.cloud import db, objects
from app.cloud.auth import current_job, current_user
from app.cloud.settings import CASE_LIMIT, GLOBAL_LIMIT, USER_LIMIT, PROVIDER


def root() -> Path:
    path = Path(os.getenv("SENTINEL_CLOUD_SCRATCH", tempfile.gettempdir())) / "sentinel-cloud-work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _owner(conn, case_id: str) -> dict:
    try:
        case_id = str(UUID(str(case_id)))
    except ValueError as exc:
        raise KeyError("Review case not found") from exc
    row = conn.execute("SELECT * FROM cases WHERE id = %s AND owner_id = %s",
                       (case_id, current_user()["id"])).fetchone()
    if not row:
        raise KeyError("Review case not found")
    return row


def _case_result(conn, row: dict) -> dict:
    case_id = str(row["id"])
    files = {item["kind"]: {key: item[key] for key in
              ("kind", "filename", "extension", "size", "uploaded_at")}
             for item in conn.execute("SELECT * FROM case_files WHERE case_id = %s", (case_id,))}
    scans = []
    for scan in conn.execute("SELECT * FROM scans WHERE case_id = %s ORDER BY created_at, id", (case_id,)):
        item = {key: scan[key] for key in ("id", "case_id", "created_at", "transactions_analyzed", "duration_ms")}
        item["id"] = str(item["id"])
        item["case_id"] = str(item["case_id"])
        item["findings"] = []
        for finding in conn.execute("SELECT * FROM findings WHERE scan_id = %s ORDER BY ordinal", (scan["id"],)):
            data = dict(finding["data_json"])
            brief = conn.execute("SELECT payload_json FROM investigations WHERE finding_id = %s",
                                 (finding["id"],)).fetchone()
            data.update(id=str(finding["id"]), decision=finding["decision"], note=finding["note"],
                        decided_at=finding["decided_at"], investigation=brief["payload_json"] if brief else None)
            item["findings"].append(data)
        scans.append(item)
    questions = []
    for question in conn.execute("SELECT * FROM questions WHERE case_id = %s ORDER BY created_at, id", (case_id,)):
        questions.append({"id": str(question["id"]), "case_id": case_id, "created_at": question["created_at"],
                          "question": question["question"], "answer": question["answer"],
                          "sources": question["sources_json"], "confidence": question["confidence_json"],
                          "presentation": question["presentation_json"]})
    status = row["status"]
    recent_job = conn.execute("""SELECT id, kind, status, error FROM jobs
                                 WHERE case_id = %s ORDER BY created_at DESC LIMIT 1""",
                              (case_id,)).fetchone()
    return {"id": case_id, "name": row["name"], "status": status,
            "created_at": row["created_at"], "started_at": row["started_at"],
            "files": files, "scans": scans, "questions": questions,
            "job": ({"job_id": str(recent_job["id"]), "kind": recent_job["kind"],
                     "status": recent_job["status"], "error": recent_job["error"]} if recent_job else None),
            "ready": status == "active", "can_start": status == "draft" and
            {"transactions", "rate_card"}.issubset(files), "can_report": bool(scans or questions)}


def create_case(name: str = "New review") -> dict:
    clean_name = name.strip()[:100] or "New review"
    owner_id = current_user()["id"]
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7281901)")
        count = conn.execute("SELECT count(*) AS n FROM cases WHERE owner_id = %s", (owner_id,)).fetchone()["n"]
        if count >= CASE_LIMIT:
            raise ValueError(f"Cloud beta allows at most {CASE_LIMIT} cases per account")
        case_id = str(uuid4())
        conn.execute("INSERT INTO cases (id, owner_id, name, status) VALUES (%s, %s, %s, 'draft')",
                     (case_id, owner_id, clean_name))
    return get_case(case_id)


def get_case(case_id: str) -> dict:
    with db.connect() as conn:
        if PROVIDER == "aws":
            return _aws_case_result(conn, _owner(conn, case_id))
        return _case_result(conn, _owner(conn, case_id))


def _aws_case_result(conn, row):
    """Fetch findings and investigation briefs in one joined query, not per finding."""
    case_id = str(row["id"])
    files = {r["kind"]: {k:r[k] for k in ("kind","filename","extension","size","uploaded_at")}
             for r in conn.execute("SELECT * FROM case_files WHERE case_id=%s", (case_id,))}
    scans = []
    indexed = {}
    for scan in conn.execute("SELECT * FROM scans WHERE case_id=%s ORDER BY created_at,id", (case_id,)):
        item = {k:scan[k] for k in ("id","case_id","created_at","transactions_analyzed","duration_ms")}
        item.update(id=str(scan["id"]), case_id=case_id, findings=[])
        scans.append(item)
        indexed[str(scan["id"])] = item
    for finding in conn.execute("""SELECT f.*,i.payload_json AS investigation FROM findings f
        JOIN scans s ON s.id=f.scan_id LEFT JOIN investigations i ON i.finding_id=f.id
        WHERE s.case_id=%s ORDER BY s.created_at,s.id,f.ordinal""", (case_id,)):
        item = dict(finding["data_json"])
        item.update(id=str(finding["id"]), decision=finding["decision"], note=finding["note"],
                    decided_at=finding["decided_at"], investigation=finding["investigation"])
        indexed[str(finding["scan_id"])]["findings"].append(item)
    questions = [{"id":str(q["id"]), "case_id":case_id, "created_at":q["created_at"],
                  "question":q["question"], "answer":q["answer"], "sources":q["sources_json"],
                  "confidence":q["confidence_json"], "presentation":q["presentation_json"]}
                 for q in conn.execute("SELECT * FROM questions WHERE case_id=%s ORDER BY created_at,id", (case_id,))]
    job = conn.execute("SELECT id,kind,status,error FROM jobs WHERE case_id=%s ORDER BY created_at DESC LIMIT 1", (case_id,)).fetchone()
    pending = bool(conn.execute("SELECT 1 FROM uploads WHERE case_id=%s AND status IN ('reserved','queued') AND expires_at>now() LIMIT 1", (case_id,)).fetchone())
    return {"id":case_id,"name":row["name"],"status":row["status"],"revision":row["revision"],
            "created_at":row["created_at"],"started_at":row["started_at"],"files":files,"scans":scans,"questions":questions,
            "job": {"job_id":str(job["id"]),"kind":job["kind"],"status":job["status"],"error":job["error"]} if job else None,
            "ready":row["status"]=="active", "can_report":bool(scans or questions),
            "can_start":row["status"]=="draft" and not pending and {"transactions","rate_card"}.issubset(files)}


def list_cases() -> list[dict]:
    with db.connect() as conn:
        return [{key: row[key] for key in ("id", "name", "status", "created_at", "started_at")}
                for row in conn.execute("SELECT * FROM cases WHERE owner_id = %s ORDER BY created_at DESC, id DESC",
                                        (current_user()["id"],))]


def _usage(conn, owner_id: str) -> tuple[int, int]:
    result = conn.execute("""SELECT COALESCE(sum(size), 0) AS total,
                                  COALESCE(sum(size) FILTER (WHERE owner_id = %s), 0) AS own
                           FROM (SELECT c.owner_id, f.size FROM case_files f JOIN cases c ON f.case_id = c.id
                                 UNION ALL
                                 SELECT c.owner_id, a.size FROM case_artifacts a JOIN cases c ON a.case_id = c.id) sizes""",
                          (owner_id,)).fetchone()
    return result["own"], result["total"]


def usage() -> dict:
    with db.connect() as conn:
        own, total = _usage(conn, current_user()["id"])
        return {"used_bytes": own, "limit_bytes": USER_LIMIT, "global_used_bytes": total,
                "global_limit_bytes": GLOBAL_LIMIT, "case_count": conn.execute(
                    "SELECT count(*) AS n FROM cases WHERE owner_id = %s", (current_user()["id"],)
                ).fetchone()["n"], "case_limit": CASE_LIMIT}


def save_file(case_id: str, kind: str, filename: str, data: bytes) -> dict:
    from app.cases.store import validate_file
    extension, count = validate_file(kind, filename, data)
    if PROVIDER == "aws" and extension == ".csv" and count * 384 * 4 + len(data) > USER_LIMIT:
        raise ValueError("The searchable index for this file would exceed your cloud storage limit")
    owner_id = current_user()["id"]
    path = f"{owner_id}/{case_id}/files/{kind}-{uuid4()}{extension}"
    old_path = None
    uploaded = False
    try:
        # Validate ownership and case state before touching private Storage.
        with db.connect() as conn:
            case = _owner(conn, case_id)
            if case["status"] != "draft":
                raise ValueError("Files are locked after a review starts. Create a new case for new uploads")
        objects.put(path, data)
        uploaded = True
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(7281901)")
            case = _owner(conn, case_id)
            if case["status"] != "draft":
                raise ValueError("Files are locked after a review starts. Create a new case for new uploads")
            old = conn.execute("SELECT path, size FROM case_files WHERE case_id = %s AND kind = %s",
                               (case_id, kind)).fetchone()
            own, total = _usage(conn, owner_id)
            old_size = old["size"] if old else 0
            if own - old_size + len(data) > USER_LIMIT or total - old_size + len(data) > GLOBAL_LIMIT:
                raise ValueError("Cloud storage limit reached; delete an unused case before uploading")
            conn.execute("""INSERT INTO case_files (case_id, kind, filename, extension, size, path)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (case_id, kind) DO UPDATE SET filename = EXCLUDED.filename,
                            extension = EXCLUDED.extension, size = EXCLUDED.size, path = EXCLUDED.path,
                            uploaded_at = now()""",
                         (case_id, kind, Path(filename).name[:200], extension, len(data), path))
            old_path = old["path"] if old else None
    except Exception:
        if uploaded:
            objects.delete([path])
        raise
    if old_path:
        objects.delete([old_path])
    folder = root() / case_id
    folder.mkdir(parents=True, exist_ok=True)
    for previous in folder.glob(f"{kind}.*"):
        previous.unlink()
    (folder / f"{kind}{extension}").write_bytes(data)
    return {"kind": kind, "filename": Path(filename).name, "extension": extension,
            "size": len(data), "items": count}


def file_path(case_id: str, kind: str) -> Path:
    case_id = str(case_id)
    with db.connect() as conn:
        _owner(conn, case_id)
        row = conn.execute("SELECT path, extension FROM case_files WHERE case_id = %s AND kind = %s",
                           (case_id, kind)).fetchone()
    if not row:
        raise KeyError(f"{kind} file not found")
    version = "-" + hashlib.sha256(row["path"].encode()).hexdigest()[:16] if PROVIDER == "aws" else ""
    target = root() / case_id / f"{kind}{version}{row['extension']}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(objects.get(row["path"]))
    return target


def mark_started(case_id: str) -> None:
    with db.connect() as conn:
        case = _owner(conn, case_id)
        if case["status"] not in {"draft", "starting"}:
            raise ValueError("Review case has already started")
        kinds = {row["kind"] for row in conn.execute("SELECT kind FROM case_files WHERE case_id = %s", (case_id,))}
        if not {"transactions", "rate_card"}.issubset(kinds):
            raise ValueError("Transactions and approved rate card are required")
        conn.execute("UPDATE cases SET status = 'active', started_at = now() WHERE id = %s", (case_id,))


def require_active(case_id: str) -> None:
    with db.connect() as conn:
        if _owner(conn, case_id)["status"] != "active":
            raise ValueError("Start the review after uploading transactions and rate card")


def add_scan(case_id: str, items: list[dict], transactions: int, duration_ms: int) -> str:
    with db.connect() as conn:
        _owner(conn, case_id)
        job_id = current_job()
        if job_id:
            previous = conn.execute("SELECT id FROM scans WHERE job_id = %s", (job_id,)).fetchone()
            if previous:
                return previous["id"]
        scan_id = str(uuid4())
        conn.execute("""INSERT INTO scans (id, case_id, job_id, transactions_analyzed, duration_ms)
                        VALUES (%s, %s, %s, %s, %s)""", (scan_id, case_id, job_id, transactions, duration_ms))
        for ordinal, item in enumerate(items):
            conn.execute("INSERT INTO findings (id, scan_id, ordinal, data_json) VALUES (%s, %s, %s, %s)",
                         (str(uuid4()), scan_id, ordinal, Jsonb(item)))
    return scan_id


def decide(case_id: str, finding_id: str, decision: str, note: str) -> dict:
    from app.cases.store import DECISIONS, utc_now
    if decision not in DECISIONS:
        raise ValueError("Choose Investigate, Approved exception, or False alarm")
    note = note.strip()[:1000]
    if decision == "approved_exception" and not note:
        raise ValueError("An approved exception requires a reason")
    try:
        finding_id = str(UUID(str(finding_id)))
    except ValueError as exc:
        raise KeyError("Finding not found in this review case") from exc
    with db.connect() as conn:
        _owner(conn, case_id)
        row = conn.execute("""UPDATE findings SET decision = %s, note = %s, decided_at = now()
                              WHERE id = %s AND scan_id IN (SELECT id FROM scans WHERE case_id = %s)
                              RETURNING decided_at""", (decision, note, finding_id, case_id)).fetchone()
        if not row:
            raise KeyError("Finding not found in this review case")
    return {"id": finding_id, "decision": decision, "note": note, "decided_at": row["decided_at"]}


def get_finding(case_id: str, finding_id: str) -> dict:
    for scan in get_case(case_id)["scans"]:
        for finding in scan["findings"]:
            if finding["id"] == finding_id:
                return finding
    raise KeyError("Finding not found in this review case")


def save_investigation(case_id: str, finding_id: str, payload: dict) -> dict:
    try:
        finding_id = str(UUID(str(finding_id)))
    except ValueError as exc:
        raise KeyError("Finding not found in this review case") from exc
    with db.connect() as conn:
        _owner(conn, case_id)
        valid = conn.execute("SELECT id FROM findings WHERE id = %s AND scan_id IN (SELECT id FROM scans WHERE case_id = %s)",
                             (finding_id, case_id)).fetchone()
        if not valid:
            raise KeyError("Finding not found in this review case")
        conn.execute("""INSERT INTO investigations (finding_id, payload_json) VALUES (%s, %s)
                        ON CONFLICT (finding_id) DO NOTHING""", (finding_id, Jsonb(jsonable_encoder(payload))))
        return conn.execute("SELECT payload_json FROM investigations WHERE finding_id = %s",
                            (finding_id,)).fetchone()["payload_json"]


def add_question(case_id: str, question: str, answer: str, sources: list,
                 confidence: dict, presentation: dict | None = None) -> str:
    with db.connect() as conn:
        _owner(conn, case_id)
        item_id = str(uuid4())
        conn.execute("""INSERT INTO questions (id, case_id, question, answer, sources_json,
                        confidence_json, presentation_json) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                     (item_id, case_id, question, answer, Jsonb(jsonable_encoder(sources)),
                      Jsonb(jsonable_encoder(confidence)),
                      Jsonb(jsonable_encoder(presentation)) if presentation else None))
    return item_id


def sync_artifacts(case_id: str) -> None:
    """Persist newly built FAISS indexes; local scratch is never authoritative."""
    owner_id = current_user()["id"]
    folder = root() / case_id
    for name in ("index", "contract_index"):
        for filename in ("faiss.index", "metadata.json"):
            local = folder / name / filename
            if not local.exists():
                continue
            data = local.read_bytes()
            path = f"{owner_id}/{case_id}/{name}/{uuid4()}-{filename}"
            old_path = None
            with db.connect() as conn:
                _owner(conn, case_id)
            objects.put(path, data)
            try:
                with db.connect() as conn:
                    conn.execute("SELECT pg_advisory_xact_lock(7281901)")
                    _owner(conn, case_id)
                    old = conn.execute("SELECT size, path FROM case_artifacts WHERE case_id = %s AND name = %s",
                                       (case_id, f"{name}/{filename}")).fetchone()
                    own, total = _usage(conn, owner_id)
                    delta = len(data) - (old["size"] if old else 0)
                    if own + delta > USER_LIMIT or total + delta > GLOBAL_LIMIT:
                        raise ValueError("Cloud storage limit reached while indexing")
                    conn.execute("""INSERT INTO case_artifacts (case_id, name, path, size)
                                    VALUES (%s, %s, %s, %s) ON CONFLICT (case_id, name)
                                    DO UPDATE SET path = EXCLUDED.path, size = EXCLUDED.size""",
                                 (case_id, f"{name}/{filename}", path, len(data)))
                    old_path = old["path"] if old else None
            except Exception:
                objects.delete([path])
                raise
            if old_path:
                objects.delete([old_path])


def ensure_index(case_id: str, name: str) -> None:
    if name not in {"index", "contract_index"}:
        raise ValueError("Unknown index")
    with db.connect() as conn:
        _owner(conn, case_id)
        items = list(conn.execute("SELECT name, path FROM case_artifacts WHERE case_id = %s AND name LIKE %s",
                                  (case_id, f"{name}/%")))
    for item in items:
        local = root() / case_id / item["name"]
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(objects.get(item["path"]))


def delete_case(case_id: str) -> None:
    with db.connect() as conn:
        _owner(conn, case_id)
        active_job = conn.execute("SELECT 1 FROM jobs WHERE case_id = %s AND status IN ('queued', 'running')",
                                  (case_id,)).fetchone()
        if active_job:
            raise ValueError("Wait for the current job to finish before deleting this case")
        paths = [row["path"] for row in conn.execute("""SELECT path FROM case_files WHERE case_id = %s
                                                        UNION ALL SELECT path FROM case_artifacts WHERE case_id = %s""",
                                                      (case_id, case_id))]
        objects.delete(paths)
        conn.execute("DELETE FROM cases WHERE id = %s AND owner_id = %s", (case_id, current_user()["id"]))
    # Delete temporary source and index copies too; Storage was the durable copy.
    scratch = root().resolve()
    target = (scratch / str(UUID(str(case_id)))).resolve()
    if target.parent == scratch:
        shutil.rmtree(target, ignore_errors=True)


def save_report(case_id: str, data: bytes, revision=None) -> None:
    owner_id = current_user()["id"]
    path = f"{owner_id}/{case_id}/reports/{uuid4()}.pdf"
    old_path = None
    with db.connect() as conn:
        _owner(conn, case_id)
    objects.put(path, data, "application/pdf")
    try:
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(7281901)")
            _owner(conn, case_id)
            if PROVIDER == "aws":
                current = conn.execute("SELECT revision FROM cases WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
                if revision != current["revision"]:
                    raise RuntimeError("Case changed while preparing report; retry")
            old = conn.execute("SELECT size, path FROM case_artifacts WHERE case_id = %s AND name = 'report.pdf'",
                               (case_id,)).fetchone()
            own, total = _usage(conn, owner_id)
            delta = len(data) - (old["size"] if old else 0)
            if own + delta > USER_LIMIT or total + delta > GLOBAL_LIMIT:
                raise ValueError("Cloud storage limit reached while generating the report")
            conn.execute("""INSERT INTO case_artifacts (case_id, name, path, size) VALUES (%s, 'report.pdf', %s, %s)
                            ON CONFLICT (case_id, name) DO UPDATE SET path = EXCLUDED.path, size = EXCLUDED.size""",
                         (case_id, path, len(data)))
            if PROVIDER == "aws":
                conn.execute("UPDATE case_artifacts SET revision=%s WHERE case_id=%s AND name='report.pdf'", (revision, case_id))
            old_path = old["path"] if old else None
    except Exception:
        objects.delete([path])
        raise
    if old_path:
        objects.delete([old_path])
