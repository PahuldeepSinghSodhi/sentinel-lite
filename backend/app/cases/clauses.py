"""Conservative, model-free matching of contract passages to saved findings."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
from PyPDF2 import PdfReader

from app.cases import store
from app.embeddings.model import get_embedding_model
from app.vectorstore.faiss_store import FAISSStore


TOPICS = {
    "rate_violation": (r"\b(rate|rates|price|pricing|fee|fees|charg\w*|bill\w*)\b",
                       "approved billing rates, rate card compliance and price adjustments"),
    "missing_rate": (r"\b(rate|rates|price|pricing|fee|fees|approv\w*)\b",
                     "approved vendor rates and rate card requirements"),
    "duplicate": (r"\b(?:duplicat\w*.{0,30}(?:invoic\w*|payment\w*|bill\w*)|"
                  r"(?:invoic\w*|payment\w*|bill\w*).{0,30}duplicat\w*|"
                  r"repeated?\s+(?:invoice|bill)|multiple\s+invoices|single\s+invoice)\b",
                  "duplicate invoices, invoice submission and payment controls"),
}
MIN_SIMILARITY = 0.20  # A candidate gate, not a probability or a 99% guarantee.
HEADING = re.compile(r"^(?:SECTION\s+\d+\b|\d+(?:\.\d+)*[.)]?\s+[A-Za-z])", re.I)


def _blocks(lines: list[str], max_words: int = 170):
    """Keep each passage small while retaining exact source line boundaries."""
    start = None
    words = 0
    for index in range(len(lines) + 1):
        line = lines[index] if index < len(lines) else ""
        stripped = line.strip()
        heading = bool(HEADING.match(stripped) or
                       (stripped.isupper() and len(stripped) > 10 and len(stripped.split()) < 12))
        if start is not None and (not line.strip() or (heading and index > start) or words >= max_words):
            text = "\n".join(lines[start:index]).strip()
            if len(text.split()) >= 5:
                yield start + 1, index, text
            start = None
            words = 0
        if line.strip():
            if start is None:
                start = index
            words += len(line.split())


def contract_passages(case_id: str) -> list[dict]:
    case = store.get_case(case_id)
    info = case["files"].get("contract")
    if not info:
        return []
    path = store.file_path(case_id, "contract")
    passages = []
    if path.suffix == ".pdf":
        reader = PdfReader(str(path))
        for page_number, page in enumerate(reader.pages, 1):
            for _, _, text in _blocks((page.extract_text() or "").splitlines()):
                passages.append({"kind": "contract", "source": info["filename"], "text": text,
                                 "page": page_number, "location": f"page {page_number}"})
    else:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for first, last, text in _blocks(lines):
            passages.append({"kind": "contract", "source": info["filename"], "text": text,
                             "line_start": first, "line_end": last,
                             "location": f"lines {first}-{last}"})
    for index, passage in enumerate(passages):
        passage["chunk_index"] = index
    return passages


def index_path(case_id: str) -> Path:
    return store.root() / case_id / "contract_index"


def build_index(case_id: str) -> None:
    passages = contract_passages(case_id)
    if not passages:
        return
    vectors = get_embedding_model().embed([item["text"] for item in passages])
    save_index(case_id, passages, vectors)


def save_index(case_id: str, passages: list[dict], vectors: np.ndarray) -> None:
    if not passages:
        return
    index = FAISSStore(dimension=vectors.shape[1])
    index.add(vectors, passages)
    index.save(str(index_path(case_id)))


class Matcher:
    """Load contract vectors once per scan, with no generation model involved."""

    def __init__(self, case_id: str, vendors: set[str], roles: set[str]):
        self.vendors = {item.casefold() for item in vendors if item}
        self.roles = {item.casefold() for item in roles if item}
        self.cache = {}
        self.guidance_only = _is_procurement_guidance(case_id)
        path = index_path(case_id)
        if "contract" in store.get_case(case_id)["files"] and not (path / "faiss.index").exists():
            build_index(case_id)  # Legacy active cases can acquire the new index on first scan.
        self.index = FAISSStore.load(str(path)) if (path / "faiss.index").exists() else None
        self.vectors = (np.stack([self.index.index.reconstruct(i) for i in range(self.index.total_vectors)])
                        if self.index and self.index.total_vectors else np.empty((0, 0)))

    def suggest(self, finding: dict, row: dict | None = None) -> dict:
        if self.index is None:
            return {"status": "no_contract", "evidence": None}
        if self.guidance_only:
            return {"status": "no_match", "evidence": None}
        topic = TOPICS.get(finding["type"])
        if topic is None and finding["type"].startswith("outlier"):
            column = finding.get("details", {}).get("column", "")
            if column in {"hourly_rate", "total_amount"}:
                topic = TOPICS["rate_violation"]
        if topic is None:
            return {"status": "no_match", "evidence": None}
        pattern, query = topic
        vendor = str((row or {}).get("vendor_name") or finding.get("details", {}).get("vendor_name") or "").casefold()
        role = str((row or {}).get("role_level") or finding.get("details", {}).get("role_level") or "").casefold()
        if query not in self.cache:
            vector = get_embedding_model().embed_query(query)
            self.cache[query] = self.vectors @ np.asarray(vector, dtype=np.float32).reshape(-1)
        scores = self.cache[query]
        candidates = []
        for index, passage in enumerate(self.index.metadata):
            body = passage["text"]
            lower = body.casefold()
            if not re.search(pattern, body, re.I):
                continue
            mentioned_vendors = {name for name in self.vendors if name in lower}
            mentioned_roles = {name for name in self.roles if name in lower}
            explicit_vendor = _labelled_value(body, r"vendor|supplier|contractor")
            explicit_role = _labelled_value(body, r"role|role level|job title")
            if explicit_vendor and vendor and explicit_vendor.casefold() != vendor:
                continue
            if explicit_role and role and explicit_role.casefold() != role:
                continue
            if vendor and mentioned_vendors and vendor not in mentioned_vendors:
                continue
            if role and mentioned_roles and role not in mentioned_roles:
                continue
            if row and not _date_applies(lower, row):
                continue
            if float(scores[index]) >= MIN_SIMILARITY:
                weighted = float(scores[index])
                if finding["type"] in {"rate_violation", "missing_rate"}:
                    if "rate card" in lower or "approved rate" in lower:
                        weighted += 0.25
                    if re.search(r"calculat\w* in accordance|must.{0,45}comply|"
                                 r"based on.{0,45}rate|no greater than|exceed.{0,30}rate", lower):
                        weighted += 0.35
                    if "benchmark" in lower:
                        weighted -= 0.35
                candidates.append((weighted, index, passage))
        if not candidates:
            return {"status": "no_match", "evidence": None}
        _, selected_index, passage = max(candidates, key=lambda item: item[0])
        evidence = {key: passage[key] for key in
                    ("kind", "source", "text", "location", "page", "line_start", "line_end", "chunk_index")
                    if key in passage}
        evidence["excerpt"] = evidence.pop("text")
        evidence["score"] = round(float(scores[selected_index]), 4)
        return {"status": "suggested", "evidence": evidence}


def _labelled_value(text: str, labels: str) -> str | None:
    """Use only clearly labelled, single-line scope fields as hard constraints."""
    match = re.search(rf"(?im)^\s*(?:{labels})\s*:\s*([^\n;,]{{2,80}})\s*$", text)
    return match.group(1).strip().casefold() if match else None


def _is_procurement_guidance(case_id: str) -> bool:
    if "contract" not in store.get_case(case_id)["files"]:
        return False
    path = store.file_path(case_id, "contract")
    if path.suffix == ".pdf":
        reader = PdfReader(str(path))
        first_page = (reader.pages[0].extract_text() or "") if reader.pages else ""
    else:
        first_page = path.read_text(encoding="utf-8-sig")[:4000]
    heading = first_page[:4000].casefold()
    return any(phrase in heading for phrase in
               ("invitation to tender information for applicants", "procurement process ifa",
                "supplemental procurement process"))


def _date_applies(text: str, row: dict) -> bool:
    transaction_date = next((str(row[key]) for key in ("transaction_date", "invoice_date", "date")
                             if row.get(key)), None)
    if not transaction_date:
        return True
    try:
        when = date.fromisoformat(transaction_date[:10])
    except ValueError:
        return True
    for phrase, comparison in (("effective from", lambda d: when >= d),
                               ("valid from", lambda d: when >= d),
                               ("valid until", lambda d: when <= d),
                               ("expires on", lambda d: when <= d)):
        match = re.search(re.escape(phrase) + r"\s+(\d{4}-\d{2}-\d{2})", text)
        if match:
            try:
                if not comparison(date.fromisoformat(match.group(1))):
                    return False
            except ValueError:
                pass
    return True
