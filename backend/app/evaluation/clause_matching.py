"""Offline, human-labelled clause evaluation on public PDFs and synthetic rows.

Run from backend/: python -m app.evaluation.clause_matching --download
Downloaded source PDFs remain local and ignored by Git. No case data is uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

import requests
from PyPDF2 import PdfReader

from app.cases import clauses, store
from app.config import BACKEND_DIR


SOURCES = BACKEND_DIR / "data" / "clause_evaluation_sources.json"
LABELS = BACKEND_DIR / "data" / "clause_evaluation_labels.json"
CACHE = BACKEND_DIR / "data" / "evaluation_public"


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    """Two-sided 95% Wilson interval for a binomial proportion."""
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0, center - margin), 4), round(min(1, center + margin), 4)]


def download_public() -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    results = {}
    for item in json.loads(SOURCES.read_text(encoding="utf-8")):
        target = CACHE / f"{item['id']}.pdf"
        if not target.exists():
            try:
                response = requests.get(item["url"], timeout=50,
                                        headers={"User-Agent": "Sentinel-Lite evaluation/1.0"})
                response.raise_for_status()
                if not response.content.startswith(b"%PDF") or len(response.content) > store.MAX_FILE_BYTES:
                    raise ValueError("not a supported text PDF under 10 MB")
                target.write_bytes(response.content)
            except (requests.RequestException, ValueError) as exc:
                results[item["id"]] = {"status": "unavailable", "reason": str(exc)}
                continue
        data = target.read_bytes()
        try:
            reader = PdfReader(target)
            if not any((page.extract_text() or "").strip() for page in reader.pages):
                raise ValueError("no selectable text")
        except Exception as exc:
            results[item["id"]] = {"status": "unsupported", "reason": str(exc)}
            continue
        results[item["id"]] = {"status": "ready", "bytes": len(data),
                                "sha256": hashlib.sha256(data).hexdigest(), "pages": len(reader.pages)}
    return results


def _case_for_pdf(document: dict, path: Path) -> str:
    case = store.create_case(f"Evaluation {document['id']}")
    case_id = case["id"]
    # Constructed rows are only search probes, never represented as real invoices.
    store.save_file(case_id, "transactions", "synthetic_transactions.csv",
                    b"vendor_name,role_level,hourly_rate,transaction_id\n"
                    b"Example Supplier,Consultant,125,SYN-1\n")
    store.save_file(case_id, "rate_card", "synthetic_rate_card.csv",
                    b"vendor_name,role_level,approved_rate\nExample Supplier,Consultant,100\n")
    store.save_file(case_id, "contract", path.name, path.read_bytes())
    clauses.build_index(case_id)
    store.mark_started(case_id)
    return case_id


def _score(rows: list[dict]) -> dict:
    shown = [row for row in rows if row["suggested"]]
    applicable = [row for row in rows if row["expected_phrase"]]
    correct = [row for row in shown if row["correct"]]
    found = [row for row in applicable if row["correct"]]
    return {"tests": len(rows), "shown": len(shown), "correct_shown": len(correct),
            "wrong_clause": len(shown) - len(correct), "applicable": len(applicable),
            "applicable_found": len(found), "abstained": len(rows) - len(shown),
            "displayed_precision": round(len(correct) / len(shown), 4) if shown else None,
            "displayed_precision_95pct_wilson": wilson(len(correct), len(shown)),
            "applicable_recall": round(len(found) / len(applicable), 4) if applicable else None,
            "applicable_recall_95pct_wilson": wilson(len(found), len(applicable)),
            "abstention_rate": round((len(rows) - len(shown)) / len(rows), 4) if rows else None}


def evaluate() -> dict:
    documents = {item["id"]: item for item in json.loads(SOURCES.read_text(encoding="utf-8"))}
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        previous = os.environ.get("SENTINEL_CASES_DIR")
        os.environ["SENTINEL_CASES_DIR"] = directory
        try:
            for document_id, document in documents.items():
                path = CACHE / f"{document_id}.pdf"
                if not path.exists():
                    continue
                try:
                    case_id = _case_for_pdf(document, path)
                    matcher = clauses.Matcher(case_id, {"Example Supplier"}, {"Consultant"})
                except Exception as exc:
                    results.append({"document": document_id, "error": str(exc)})
                    continue
                for label in (item for item in labels if item["document"] == document_id):
                    finding = {"type": label["finding_type"], "details": label.get("details", {})}
                    started = time.perf_counter()
                    suggestion = matcher.suggest(finding, {"vendor_name": "Example Supplier",
                                                           "role_level": "Consultant"})
                    elapsed = round((time.perf_counter() - started) * 1000, 2)
                    evidence = suggestion.get("evidence") or {}
                    expected = label.get("acceptable") or (
                        [{"page": label["expected_page"], "phrase": label["expected_phrase"]}]
                        if label.get("expected_phrase") else [])
                    normal = lambda text: re.sub(r"\s+", " ", text.casefold())
                    correct = ((suggestion["status"] != "suggested") if not expected else
                               suggestion["status"] == "suggested" and any(
                                   normal(option["phrase"]) in normal(evidence.get("excerpt", "")) and
                                   evidence.get("page") == option["page"] for option in expected))
                    results.append({"document": document_id, "split": document["split"],
                                    "finding_type": label["finding_type"], "expected_phrase": expected,
                                    "expected_page": label.get("expected_page"),
                                    "suggested": suggestion["status"] == "suggested",
                                    "suggested_page": evidence.get("page"),
                                    "suggested_excerpt": evidence.get("excerpt", "")[:240],
                                    "correct": bool(correct),
                                    "milliseconds": elapsed})
        finally:
            if previous is None:
                os.environ.pop("SENTINEL_CASES_DIR", None)
            else:
                os.environ["SENTINEL_CASES_DIR"] = previous
    scored = [item for item in results if "error" not in item]
    by_split = {split: _score([item for item in scored if item["split"] == split])
                for split in ("development", "held_out")}
    by_type = {kind: _score([item for item in scored if item["finding_type"] == kind])
               for kind in sorted({item["finding_type"] for item in scored})}
    by_source = {doc: _score([item for item in scored if item["document"] == doc])
                 for doc in documents}
    return {"disclaimer": "Preliminary public/synthetic probes, not representative company-contract accuracy. Labels within one PDF are correlated, so binomial intervals are descriptive only.",
            "overall": _score(scored), "by_split": by_split, "by_type": by_type,
            "by_source": by_source, "results": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Fetch public PDFs into an ignored local cache")
    arguments = parser.parse_args()
    if arguments.download:
        print(json.dumps({"downloads": download_public()}, indent=2))
    print(json.dumps(evaluate(), indent=2))


if __name__ == "__main__":
    main()
