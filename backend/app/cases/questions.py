"""Answer case questions using saved scan facts and uploaded-document retrieval."""
import re
from csv import DictReader

from app.cases import sources, store
from app.rag.pipeline import query_rag


ANOMALY_TERMS = re.compile(
    r"\b(duplicat(?:e|es|ed|ion)|anomal(?:y|ies)|findings?|flags?|flagged|"
    r"violations?|overcharg(?:e|ed|ing)|discrepanc(?:y|ies)|outliers?|"
    r"exceptions?|investigat(?:e|ion)|false alarms?|scans?|suspicious)\b",
    re.IGNORECASE,
)
DOCUMENT_TERMS = re.compile(r"\b(contract|agreement|payment terms|policy|document)\b", re.IGNORECASE)
TYPE_TERMS = {
    "duplicate": re.compile(r"\bduplicat(?:e|es|ed|ion)\b", re.IGNORECASE),
    "rate_violation": re.compile(r"\b(rate violations?|overcharg(?:e|ed|ing)|rate discrepancies)\b", re.IGNORECASE),
    "missing_rate": re.compile(r"\b(missing rates?|no approved rates?|unlisted vendors?)\b", re.IGNORECASE),
    "outlier": re.compile(r"\b(outliers?|unusual values?)\b", re.IGNORECASE),
}
MAX_LISTED_FINDINGS = 100


def _vendor(finding: dict) -> str:
    details = finding.get("details") or {}
    if details.get("vendor_name"):
        return str(details["vendor_name"])
    for evidence in finding.get("evidence", []):
        if evidence.get("kind") == "transactions":
            return str((evidence.get("excerpt") or {}).get("vendor_name") or "Unknown vendor")
    return "Unknown vendor"


def _matching_types(question: str) -> set[str]:
    requested = {kind for kind, pattern in TYPE_TERMS.items() if pattern.search(question)}
    if "outlier" in requested:
        requested.remove("outlier")
        requested.update(("outlier_zscore", "outlier_iqr"))
    return requested


def _cited_rows(findings: list[dict]) -> list[dict]:
    cited = []
    seen = set()
    for finding in findings:
        for evidence in finding.get("evidence", []):
            key = (evidence.get("kind"), evidence.get("row_number"),
                   evidence.get("page"), evidence.get("line_start"))
            if key in seen:
                continue
            seen.add(key)
            cited.append({**evidence, "text_preview": str(evidence.get("excerpt", ""))[:300]})
    return cited


def _presentation(scan: dict, findings: list[dict], duplicate_only: bool) -> dict:
    """Keep exact scan facts separate from the prose saved in the case report."""
    transaction_rows = {evidence["row_number"] for finding in findings
                        for evidence in finding.get("evidence", [])
                        if evidence.get("kind") == "transactions" and evidence.get("row_number")}
    groups = {}
    for finding in findings[:MAX_LISTED_FINDINGS]:
        vendor = _vendor(finding)
        group = groups.setdefault(vendor, {"vendor": vendor, "finding_count": 0,
                                           "rows": [], "findings": []})
        rows = sorted({evidence["row_number"] for evidence in finding.get("evidence", [])
                       if evidence.get("kind") == "transactions" and evidence.get("row_number")})
        group["finding_count"] += 1
        group["rows"] = sorted(set(group["rows"]) | set(rows))
        group["findings"].append({
            "type": finding["type"],
            "label": finding["type"].replace("_", " ").title(),
            "description": finding["description"],
            "rows": rows,
            "calculation": finding.get("calculation"),
            "rule": finding.get("rule"),
            "decision": finding.get("decision"),
            "note": finding.get("note"),
            "details": {key: value for key, value in (finding.get("details") or {}).items()
                        if key in {"role_level", "billed_rate", "approved_rate", "difference_percentage"}},
        })
    vendor_count = len({_vendor(finding) for finding in findings})
    if duplicate_only:
        extra_copies = sum(max(0, sum(e.get("kind") == "transactions" for e in finding.get("evidence", [])) - 1)
                           for finding in findings)
        summary = (f"{len(findings)} duplicate group{'s' if len(findings) != 1 else ''} "
                   f"across {vendor_count} vendor{'s' if vendor_count != 1 else ''}.")
        metrics = [
            {"label": "Duplicate groups", "value": len(findings)},
            {"label": "Rows involved", "value": len(transaction_rows)},
            {"label": "Extra copies", "value": extra_copies},
        ]
        caveat = "Matching content is a possible duplicate, not proof of duplicate payment. Review the source rows."
    else:
        summary = (f"{len(findings)} matching finding{'s' if len(findings) != 1 else ''} "
                   f"across {vendor_count} vendor{'s' if vendor_count != 1 else ''}.")
        metrics = [
            {"label": "Findings", "value": len(findings)},
            {"label": "Vendors", "value": vendor_count},
            {"label": "Rows involved", "value": len(transaction_rows)},
        ]
        caveat = "Findings are review signals. Check the linked source rows before making a decision."
    return {"kind": "scan", "summary": summary, "metrics": metrics,
            "groups": list(groups.values()), "caveat": caveat,
            "scan_created_at": scan["created_at"], "scan_id": scan["id"],
            "truncated": len(findings) > MAX_LISTED_FINDINGS}


def _scan_answer(case: dict, question: str) -> dict:
    if not case["scans"]:
        return {"answer": "No anomaly scan has been run for this case yet. Run a scan in Anomaly review first.",
                "sources": [], "confidence": {"basis": "scan_not_run"}}

    scan = case["scans"][-1]
    findings = scan["findings"]
    types = _matching_types(question)
    if types:
        findings = [finding for finding in findings if finding["type"] in types]

    with store.file_path(case["id"], "transactions").open(encoding="utf-8-sig", newline="") as stream:
        vendors = sorted({row["vendor_name"] for row in DictReader(stream)}, key=len, reverse=True)
    named = [vendor for vendor in vendors if re.search(rf"(?<!\w){re.escape(vendor)}(?!\w)", question, re.I)]
    if named:
        findings = [finding for finding in findings if _vendor(finding).casefold() in
                    {vendor.casefold() for vendor in named}]

    decision_terms = {
        "approved_exception": r"\bapproved exceptions?\b",
        "false_alarm": r"\bfalse alarms?\b",
    }
    requested_decisions = {decision for decision, pattern in decision_terms.items()
                           if re.search(pattern, question, re.I)}
    if requested_decisions:
        findings = [finding for finding in findings if finding.get("decision") in requested_decisions]

    duplicate_only = types == {"duplicate"}
    heading = f"Latest scan ({scan['created_at']}; {scan['transactions_analyzed']} transactions): "
    if duplicate_only:
        rows = {evidence["row_number"] for finding in findings
                for evidence in finding.get("evidence", [])
                if evidence.get("kind") == "transactions" and evidence.get("row_number")}
        additional = sum(max(0, sum(e.get("kind") == "transactions" for e in finding.get("evidence", [])) - 1)
                         for finding in findings)
        heading += (f"{len(findings)} duplicate group(s), {len(rows)} transaction row(s) involved, "
                    f"and {additional} additional copy/copies.")
    else:
        heading += f"{len(findings)} matching finding(s)."

    lines = [heading]
    for finding in findings[:MAX_LISTED_FINDINGS]:
        transaction_rows = [e["location"] for e in finding.get("evidence", [])
                            if e.get("kind") == "transactions"]
        other_sources = [f"{e['source']} {e['location']}" for e in finding.get("evidence", [])
                         if e.get("kind") != "transactions"]
        locations = ", ".join(transaction_rows) or "no transaction row available"
        line = (f"{_vendor(finding)} — {finding['type'].replace('_', ' ')}: "
                f"{case['files']['transactions']['filename']} {locations}.")
        if finding["type"] != "duplicate":
            line += f" {finding['description']}"
        if finding.get("calculation") and finding["type"] != "duplicate":
            line += f" Calculation: {finding['calculation']}."
        if other_sources:
            line += " Also: " + ", ".join(other_sources) + "."
        if finding.get("decision"):
            line += f" Review decision: {finding['decision'].replace('_', ' ')}."
            if finding.get("note"):
                line += f" Note: {finding['note']}."
        lines.append(line)
    if len(findings) > MAX_LISTED_FINDINGS:
        lines.append(f"Showing the first {MAX_LISTED_FINDINGS} of {len(findings)} findings. "
                     "The case report includes the complete scan.")
    return {"answer": "\n".join(lines), "sources": _cited_rows(findings[:MAX_LISTED_FINDINGS]),
            "presentation": _presentation(scan, findings, duplicate_only),
            "confidence": {"basis": "latest_scan", "scan_id": scan["id"],
                           "scan_created_at": scan["created_at"]}}


def answer_case_question(case_id: str, question: str, top_k: int = 5) -> dict:
    """Use exact saved findings for anomaly questions; add RAG for document context."""
    case = store.get_case(case_id)
    if not ANOMALY_TERMS.search(question):
        return query_rag(question, sources.load_index(case_id), top_k=top_k)

    result = _scan_answer(case, question)
    if DOCUMENT_TERMS.search(question) and case["scans"]:
        document = query_rag(question, sources.load_index(case_id), top_k=top_k)
        result["answer"] += "\n\nUploaded-document context (AI-generated; verify against the passages below):\n"
        result["answer"] += document["answer"]
        result["sources"].extend(document["sources"])
        result["confidence"]["document_confidence"] = document.get("confidence", {})
        result["presentation"]["document_answer"] = document["answer"]
    return result
