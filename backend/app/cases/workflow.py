"""Case scans with deterministic, inspectable transaction evidence."""
import time

import pandas as pd

from app.anomaly.detector import detect_anomalies
from app.cases import store


RULES = {
    "duplicate": "Identical transaction content appears more than once.",
    "outlier_zscore": "Absolute Z-score is greater than 2.",
    "outlier_iqr": "Value lies outside Q1 - 1.5×IQR to Q3 + 1.5×IQR.",
    "rate_violation": "Billed hourly rate exceeds the approved rate by more than 5%.",
    "missing_rate": "No approved rate exists for this vendor and role in the uploaded rate card.",
}


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def scan_case(case_id: str) -> str:
    store.require_active(case_id)
    started = time.perf_counter()
    transactions = pd.read_csv(store.file_path(case_id, "transactions"))
    rates = pd.read_csv(store.file_path(case_id, "rate_card"))
    anomalies = detect_anomalies(transactions, rates)
    case = store.get_case(case_id)
    findings = []
    for anomaly in anomalies:
        item = plain(anomaly)
        item["rule"] = RULES.get(item["type"], item["type"])
        evidence = []
        relevant_column = item.get("details", {}).get("column")
        for index in item["row_indices"]:
            row = plain(transactions.iloc[index].to_dict())
            row_number = index + 2
            evidence.append({
                "kind": "transactions", "source": case["files"]["transactions"]["filename"],
                "location": f"CSV row {row_number}", "row_number": row_number,
                "columns": [relevant_column] if relevant_column else list(transactions.columns),
                "excerpt": row,
            })
        if item["type"] == "rate_violation":
            details = item["details"]
            match = rates[(rates["vendor_name"] == details["vendor_name"]) &
                          (rates["role_level"] == details["role_level"])]
            if not match.empty:
                rate_row = int(match.index[0]) + 2
                evidence.append({
                    "kind": "rate_card", "source": case["files"]["rate_card"]["filename"],
                    "location": f"CSV row {rate_row}, approved_rate column",
                    "row_number": rate_row, "columns": ["approved_rate"],
                    "excerpt": plain(match.iloc[0].to_dict()),
                })
            item["calculation"] = (
                f"({details['billed_rate']:g} - {details['approved_rate']:g}) / "
                f"{details['approved_rate']:g} × 100 = {details['difference_percentage']:.1f}%"
            )
        elif item["type"] == "outlier_zscore":
            item["calculation"] = f"|Z-score| = {abs(item['details']['z_score']):.2f} > 2"
        elif item["type"] == "outlier_iqr":
            details = item["details"]
            item["calculation"] = (
                f"{details['value']:g} is outside {details['lower_bound']:g}–{details['upper_bound']:g}"
            )
        elif item["type"] == "missing_rate":
            item["calculation"] = "No matching vendor and role in the approved rate card"
        else:
            item["calculation"] = f"{len(item['row_indices'])} matching rows"
        item["evidence"] = evidence
        findings.append(item)
    elapsed = round((time.perf_counter() - started) * 1000)
    return store.add_scan(case_id, findings, len(transactions), elapsed)
