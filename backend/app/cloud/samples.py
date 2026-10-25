"""One private, resumable synthetic sample per invited account."""
from uuid import uuid4

from app.cloud import db, store
from app.cloud.auth import current_user
from app.config import BACKEND_DIR

VERSION = "procurement-v1"
FILES = (("transactions", "sample_transactions.csv"), ("rate_card", "rate_card.csv"),
         ("contract", "sample_docs/service_agreement.txt"))


def open_sample():
    owner = current_user()["id"]
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(owner),))
        case = conn.execute("SELECT * FROM cases WHERE owner_id=%s AND sample_version IS NOT NULL FOR UPDATE", (owner,)).fetchone()
        if case and case["status"] == "active":
            case_id = str(case["id"])
        else:
            if case:
                case_id = str(case["id"])
            else:
                case_id = str(uuid4())
                conn.execute("INSERT INTO cases(id,owner_id,name,status,sample_version) VALUES (%s,%s,%s,'starting',%s)",
                             (case_id, owner, "Sample procurement review", VERSION))
            pending = conn.execute("SELECT id FROM jobs WHERE case_id=%s AND status IN ('queued','running') LIMIT 1", (case_id,)).fetchone()
            if not pending:
                count = conn.execute("SELECT count(*) AS n FROM jobs WHERE owner_id=%s AND status IN ('queued','running')", (owner,)).fetchone()["n"]
                if count >= 4:
                    raise ValueError("Wait for your queued operations to finish, then retry the sample")
                conn.execute("UPDATE cases SET status='starting' WHERE id=%s", (case_id,))
                conn.execute("INSERT INTO jobs(id,case_id,owner_id,kind) VALUES (%s,%s,%s,'demo')", (str(uuid4()),case_id,owner))
    return store.get_case(case_id)


def prepare_sample(case_id):
    from app.cases import sources
    case = store.get_case(case_id)
    if case["ready"]:
        return {"case_id": case_id}
    for kind, relative in FILES:
        path = BACKEND_DIR / "data" / relative
        store.save_file(case_id, kind, path.name, path.read_bytes(), sample_job=True)
    sources.build_index(case_id)
    store.sync_artifacts(case_id)
    store.mark_started(case_id)
    return {"case_id": case_id}
