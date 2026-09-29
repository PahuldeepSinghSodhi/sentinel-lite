"""SQLite records and validated local files for independent review cases."""
import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from PyPDF2 import PdfReader

from app.config import BACKEND_DIR


FILE_RULES = {
    "transactions": {"extensions": {".csv"}, "columns": {"vendor_name", "role_level", "hourly_rate"}},
    "rate_card": {"extensions": {".csv"}, "columns": {"vendor_name", "role_level", "approved_rate"}},
    "contract": {"extensions": {".pdf", ".txt"}, "columns": set()},
}
MAX_FILE_BYTES = 10 * 1024 * 1024
DECISIONS = {"investigate", "approved_exception", "false_alarm"}


def root() -> Path:
    return Path(os.getenv("SENTINEL_CASES_DIR", str(BACKEND_DIR / "data" / "cases")))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "cases.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, started_at TEXT
        );
        CREATE TABLE IF NOT EXISTS files (
            case_id TEXT NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
            extension TEXT NOT NULL, size INTEGER NOT NULL, uploaded_at TEXT NOT NULL,
            PRIMARY KEY(case_id, kind), FOREIGN KEY(case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS scans (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, created_at TEXT NOT NULL,
            transactions_analyzed INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
            FOREIGN KEY(case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, data_json TEXT NOT NULL,
            decision TEXT, note TEXT NOT NULL DEFAULT '', decided_at TEXT,
            FOREIGN KEY(scan_id) REFERENCES scans(id)
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, created_at TEXT NOT NULL,
            question TEXT NOT NULL, answer TEXT NOT NULL, sources_json TEXT NOT NULL,
            confidence_json TEXT NOT NULL, presentation_json TEXT,
            FOREIGN KEY(case_id) REFERENCES cases(id)
        );
    """)
    # Existing local cases predate the structured answer display. Keep their history intact.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(questions)")}
    if "presentation_json" not in columns:
        db.execute("ALTER TABLE questions ADD COLUMN presentation_json TEXT")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_case(name: str = "New review") -> dict:
    clean_name = name.strip()[:100] or "New review"
    case_id = str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO cases (id, name, status, created_at) VALUES (?, ?, 'draft', ?)",
                   (case_id, clean_name, utc_now()))
    return get_case(case_id)


def _case_row(db, case_id: str):
    row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise KeyError("Review case not found")
    return row


def get_case(case_id: str) -> dict:
    with connect() as db:
        case = dict(_case_row(db, case_id))
        files = {row["kind"]: dict(row) for row in db.execute(
            "SELECT kind, filename, extension, size, uploaded_at FROM files WHERE case_id = ?", (case_id,)
        )}
        scans = []
        for scan in db.execute("SELECT * FROM scans WHERE case_id = ? ORDER BY created_at, rowid", (case_id,)):
            item = dict(scan)
            item["findings"] = []
            for finding in db.execute("SELECT * FROM findings WHERE scan_id = ? ORDER BY rowid", (scan["id"],)):
                data = json.loads(finding["data_json"])
                data.update(id=finding["id"], decision=finding["decision"], note=finding["note"],
                            decided_at=finding["decided_at"])
                item["findings"].append(data)
            scans.append(item)
        questions = []
        for row in db.execute("SELECT * FROM questions WHERE case_id = ? ORDER BY created_at, rowid", (case_id,)):
            item = dict(row)
            item["sources"] = json.loads(item.pop("sources_json"))
            item["confidence"] = json.loads(item.pop("confidence_json"))
            presentation = item.pop("presentation_json")
            item["presentation"] = json.loads(presentation) if presentation else None
            questions.append(item)
    case.update(files=files, scans=scans, questions=questions,
                ready=case["status"] == "active",
                can_start=case["status"] == "draft" and "transactions" in files and "rate_card" in files,
                can_report=bool(scans or questions))
    return case


def list_cases() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT id, name, status, created_at, started_at FROM cases ORDER BY created_at DESC, rowid DESC"
        )]


def _read_csv(data: bytes, kind: str) -> pd.DataFrame:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV files must be UTF-8 encoded") from exc
    try:
        headers = next(csv.reader(io.StringIO(text)))
    except (StopIteration, csv.Error) as exc:
        raise ValueError("CSV has no header row") from exc
    if len(headers) != len(set(headers)) or any(not h.strip() for h in headers):
        raise ValueError("CSV column names must be nonempty and unique")
    try:
        frame = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Invalid CSV: {exc}") from exc
    missing = FILE_RULES[kind]["columns"] - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError("CSV must contain at least one data row")
    for column in ("vendor_name", "role_level"):
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} cannot be blank")
    numeric_column = "hourly_rate" if kind == "transactions" else "approved_rate"
    amounts = pd.to_numeric(frame[numeric_column], errors="coerce")
    if amounts.isna().any() or (amounts <= 0).any():
        raise ValueError(f"{numeric_column} must contain valid positive rates")
    if kind == "transactions":
        for optional in ("hours", "total_amount"):
            if optional in frame.columns:
                values = pd.to_numeric(frame[optional], errors="coerce")
                if values.isna().any() or (values < 0).any():
                    raise ValueError(f"{optional} must contain valid nonnegative numbers")
    if kind == "rate_card" and frame.duplicated(["vendor_name", "role_level"]).any():
        raise ValueError("Rate card must have one approved rate per vendor and role")
    return frame


def validate_file(kind: str, filename: str, data: bytes) -> tuple[str, int]:
    if kind not in FILE_RULES:
        raise ValueError("Unknown upload section")
    extension = Path(filename).suffix.lower()
    if extension not in FILE_RULES[kind]["extensions"]:
        allowed = ", ".join(sorted(FILE_RULES[kind]["extensions"]))
        raise ValueError(f"{kind} supports {allowed} files")
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("File must be nonempty and no larger than 10 MB")
    if extension == ".csv":
        rows = len(_read_csv(data, kind))
    elif extension == ".txt":
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TXT files must be UTF-8 encoded") from exc
        if not content.strip():
            raise ValueError("Contract contains no text")
        rows = len(content.splitlines())
    else:
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ValueError("Could not read the PDF") from exc
        if not any(page.strip() for page in pages):
            raise ValueError("This PDF has no selectable text; scanned PDFs require OCR")
        rows = len(pages)
    return extension, rows


def save_file(case_id: str, kind: str, filename: str, data: bytes) -> dict:
    extension, count = validate_file(kind, filename, data)
    with connect() as db:
        case = _case_row(db, case_id)
        if case["status"] != "draft":
            raise ValueError("Files are locked after a review starts. Create a new case for new uploads")
        folder = root() / case_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{kind}{extension}"
        target.write_bytes(data)
        db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)",
                   (case_id, kind, Path(filename).name[:200], extension, len(data), utc_now()))
    return {"kind": kind, "filename": Path(filename).name, "extension": extension,
            "size": len(data), "items": count}


def file_path(case_id: str, kind: str) -> Path:
    with connect() as db:
        _case_row(db, case_id)
        row = db.execute("SELECT extension FROM files WHERE case_id = ? AND kind = ?", (case_id, kind)).fetchone()
    if row is None:
        raise KeyError(f"{kind} file not found")
    return root() / case_id / f"{kind}{row['extension']}"


def mark_started(case_id: str) -> None:
    with connect() as db:
        case = _case_row(db, case_id)
        if case["status"] != "draft":
            raise ValueError("Review case has already started")
        kinds = {row[0] for row in db.execute("SELECT kind FROM files WHERE case_id = ?", (case_id,))}
        if not {"transactions", "rate_card"}.issubset(kinds):
            raise ValueError("Transactions and approved rate card are required")
        db.execute("UPDATE cases SET status = 'active', started_at = ? WHERE id = ?", (utc_now(), case_id))


def require_active(case_id: str) -> None:
    with connect() as db:
        if _case_row(db, case_id)["status"] != "active":
            raise ValueError("Start the review after uploading transactions and rate card")


def add_scan(case_id: str, items: list[dict], transactions: int, duration_ms: int) -> str:
    scan_id = str(uuid4())
    with connect() as db:
        _case_row(db, case_id)
        db.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?)",
                   (scan_id, case_id, utc_now(), transactions, duration_ms))
        for item in items:
            db.execute("INSERT INTO findings (id, scan_id, data_json) VALUES (?, ?, ?)",
                       (str(uuid4()), scan_id, json.dumps(item, allow_nan=False)))
    return scan_id


def decide(case_id: str, finding_id: str, decision: str, note: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError("Choose Investigate, Approved exception, or False alarm")
    note = note.strip()[:1000]
    if decision == "approved_exception" and not note:
        raise ValueError("An approved exception requires a reason")
    with connect() as db:
        _case_row(db, case_id)
        row = db.execute("""SELECT findings.id FROM findings JOIN scans ON findings.scan_id = scans.id
                            WHERE findings.id = ? AND scans.case_id = ?""", (finding_id, case_id)).fetchone()
        if row is None:
            raise KeyError("Finding not found in this review case")
        when = utc_now()
        db.execute("UPDATE findings SET decision = ?, note = ?, decided_at = ? WHERE id = ?",
                   (decision, note, when, finding_id))
    return {"id": finding_id, "decision": decision, "note": note, "decided_at": when}


def add_question(case_id: str, question: str, answer: str, sources: list,
                 confidence: dict, presentation: dict | None = None) -> str:
    item_id = str(uuid4())
    with connect() as db:
        _case_row(db, case_id)
        db.execute("""INSERT INTO questions
                      (id, case_id, created_at, question, answer, sources_json,
                       confidence_json, presentation_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (item_id, case_id, utc_now(), question, answer,
                    json.dumps(sources, allow_nan=False), json.dumps(confidence, allow_nan=False),
                    json.dumps(presentation, allow_nan=False) if presentation else None))
    return item_id
