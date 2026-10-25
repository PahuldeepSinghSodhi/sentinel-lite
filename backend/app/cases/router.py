"""Case-scoped upload, review, question, source, and report API."""
from fastapi import APIRouter, File, HTTPException, UploadFile, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field

from app.cases import investigation, questions, report, sources, store, workflow
from app.config import BACKEND_DIR
from app.config import SENTINEL_MODE


def aws_mode():
    if SENTINEL_MODE != "cloud":
        return False
    from app.cloud.settings import PROVIDER
    return PROVIDER == "aws"


def queued(request, case_id, kind, payload=None):
    from app.cloud.aws_jobs import queue
    return JSONResponse(queue(case_id,kind,payload,request.headers.get("idempotency-key")),status_code=202)


router = APIRouter(prefix="/cases", tags=["Review cases"])


def _error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise exc


class CreateCase(BaseModel):
    name: str = Field(default="New review", max_length=100)


class AskCase(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class Decision(BaseModel):
    decision: str
    note: str = Field(default="", max_length=1000)


@router.get("")
def cases_list():
    return store.list_cases()


@router.post("", status_code=201)
def cases_create(payload: CreateCase):
    try:
        return store.create_case(payload.name)
    except Exception as exc:
        _error(exc)


@router.post("/demo", status_code=201)
def cases_demo():
    """Create an independent review with the repository's sample files."""
    if aws_mode():
        try:
            from app.cloud.samples import open_sample
            return open_sample()
        except Exception as exc:
            _error(exc)
    case = store.create_case("Sample procurement review")
    case_id = case["id"]
    data_dir = BACKEND_DIR / "data"
    for kind, path in (
        ("transactions", data_dir / "sample_transactions.csv"),
        ("rate_card", data_dir / "rate_card.csv"),
        ("contract", data_dir / "sample_docs" / "service_agreement.txt"),
    ):
        store.save_file(case_id, kind, path.name, path.read_bytes())
    try:
        if SENTINEL_MODE == "cloud":
            from app.cloud.dispatch import queue_and_dispatch
            queue_and_dispatch(case_id, "start")
        else:
            sources.build_index(case_id)
            store.mark_started(case_id)
    except Exception as exc:
        _error(exc)
    return store.get_case(case_id)


@router.get("/{case_id}")
def cases_get(case_id: str):
    try:
        return store.get_case(case_id)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/files/{kind}")
async def cases_upload(case_id: str, kind: str, file: UploadFile = File(...)):
    if aws_mode():
        await file.close()
        raise HTTPException(409,"Use an authorized direct upload")
    if kind not in store.FILE_RULES:
        raise HTTPException(status_code=400, detail="Unknown upload section")
    data = await file.read(store.MAX_FILE_BYTES + 1)
    await file.close()
    try:
        store.save_file(case_id, kind, file.filename or "", data)
        return store.get_case(case_id)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/start")
def cases_start(case_id: str):
    try:
        if SENTINEL_MODE == "cloud":
            from app.cloud.dispatch import queue_and_dispatch
            return queue_and_dispatch(case_id, "start")
        case = store.get_case(case_id)
        if not case["can_start"]:
            raise ValueError("Upload valid transactions and rate card before starting")
        sources.build_index(case_id)
        store.mark_started(case_id)
        return store.get_case(case_id)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/scans")
def cases_scan(case_id: str):
    try:
        if SENTINEL_MODE == "cloud":
            from app.cloud.dispatch import queue_and_dispatch
            return queue_and_dispatch(case_id, "scan")
        scan_id = workflow.scan_case(case_id)
        case = store.get_case(case_id)
        return next(scan for scan in case["scans"] if scan["id"] == scan_id)
    except Exception as exc:
        _error(exc)


@router.patch("/{case_id}/findings/{finding_id}")
def cases_decide(case_id: str, finding_id: str, payload: Decision):
    try:
        return store.decide(case_id, finding_id, payload.decision, payload.note)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/findings/{finding_id}/investigate")
def cases_investigate(case_id: str, finding_id: str, request: Request):
    try:
        if aws_mode():
            store.get_finding(case_id,finding_id)
            return queued(request,case_id,"investigate",{"finding_id":finding_id})
        return investigation.investigate(case_id, finding_id)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/questions")
def cases_ask(case_id: str, payload: AskCase, request: Request):
    try:
        store.require_active(case_id)
        question = payload.question.strip()
        if not question:
            raise ValueError("Question cannot be empty")
        if aws_mode():
            return queued(request,case_id,"question",{"question":question,"top_k":payload.top_k})
        result = questions.answer_case_question(case_id, question, top_k=payload.top_k)
        item_id = store.add_question(case_id, question, result["answer"],
                                     result["sources"], result.get("confidence", {}),
                                     result.get("presentation"))
        return next(item for item in store.get_case(case_id)["questions"] if item["id"] == item_id)
    except Exception as exc:
        _error(exc)


@router.get("/{case_id}/source/{kind}")
def cases_source(case_id: str, kind: str, page: int | None = None, row: int | None = None,
                 line_start: int | None = None, line_end: int | None = None):
    try:
        return sources.excerpt(case_id, kind, page=page, row=row,
                               line_start=line_start, line_end=line_end)
    except Exception as exc:
        _error(exc)


@router.get("/{case_id}/files/contract/original")
def cases_original_contract(case_id: str):
    try:
        if aws_mode():
            from app.cloud import db, store as cloud_store
            from app.cloud.aws_objects import signed_download
            with db.connect() as conn:
                cloud_store._owner(conn,case_id)
                row=conn.execute("SELECT path,extension FROM case_files WHERE case_id=%s AND kind='contract'",(case_id,)).fetchone()
            if not row or row["extension"] != ".pdf":
                raise ValueError("The uploaded contract is not a PDF")
            return {"url":signed_download(row["path"],"contract.pdf",inline=True)}
        path = store.file_path(case_id, "contract")
        if path.suffix.lower() != ".pdf":
            raise ValueError("The uploaded contract is not a PDF")
        return Response(path.read_bytes(), media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})
    except Exception as exc:
        _error(exc)


@router.get("/{case_id}/report")
def cases_report(case_id: str, request: Request):
    try:
        case = store.get_case(case_id)
        if not case["can_report"]:
            raise ValueError("Run a scan or ask a question before downloading a report")
        if aws_mode():
            from app.cloud import db
            from app.cloud.aws_objects import signed_download
            with db.connect() as conn:
                item=conn.execute("SELECT path FROM case_artifacts WHERE case_id=%s AND name='report.pdf' AND revision=%s",(case_id,case["revision"])).fetchone()
            if item:
                return {"url":signed_download(item["path"],f"sentinel-review-{case_id[:8]}.pdf")}
            return queued(request,case_id,"report")
        pdf = report.make_pdf(case)
        if SENTINEL_MODE == "cloud":
            from app.cloud import store as cloud_store
            cloud_store.save_report(case_id, pdf)
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="sentinel-review-{case_id[:8]}.pdf"'
        })
    except Exception as exc:
        _error(exc)


class UploadTicket(BaseModel):
    filename: str = Field(min_length=1,max_length=200)
    size: int = Field(gt=0,le=10*1024*1024)


@router.post("/{case_id}/uploads/{kind}")
def upload_authorization(case_id: str,kind: str,payload: UploadTicket):
    if not aws_mode():
        raise HTTPException(404)
    try:
        from app.cloud.uploads import authorize
        return authorize(case_id,kind,payload.filename,payload.size)
    except Exception as exc:
        _error(exc)


@router.post("/{case_id}/uploads/{upload_id}/confirm")
def upload_confirmation(case_id: str,upload_id: str,request: Request):
    if not aws_mode():
        raise HTTPException(404)
    try:
        from app.cloud.uploads import confirm
        return JSONResponse(confirm(case_id,upload_id,request.headers.get("idempotency-key")),status_code=202)
    except Exception as exc:
        _error(exc)


@router.delete("/{case_id}/uploads/{upload_id}", status_code=204)
def upload_cancel(case_id: str, upload_id: str):
    if not aws_mode():
        raise HTTPException(404)
    try:
        from app.cloud.uploads import cancel
        cancel(case_id, upload_id)
    except Exception as exc:
        _error(exc)


@router.delete("/{case_id}", status_code=204)
def cases_delete(case_id: str):
    if SENTINEL_MODE != "cloud":
        raise HTTPException(404, "Case deletion is not available in local mode")
    try:
        from app.cloud import store as cloud_store
        cloud_store.delete_case(case_id)
    except Exception as exc:
        _error(exc)
