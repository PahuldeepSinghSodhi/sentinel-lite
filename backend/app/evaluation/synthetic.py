"""Reproducible 240-transaction benchmark and labelled injected issues.

Run ``python -m app.evaluation.synthetic`` to refresh the three benchmark files.
The labels are authored from the injections, not copied from detector output.
"""
import json
import time
from pathlib import Path

import pandas as pd

from app.config import BACKEND_DIR
from app.evaluation.harness import evaluate_anomaly_detection

KNOWN_APPROVED_EXCEPTIONS = [230]


def benchmark():
    rates = pd.DataFrame([
        {"vendor_name": "Apex Consulting", "role_level": "Engineer", "approved_rate": 150},
        {"vendor_name": "DataFlow Inc", "role_level": "Engineer", "approved_rate": 175},
        {"vendor_name": "NetSecure Solutions", "role_level": "Analyst", "approved_rate": 190},
        {"vendor_name": "CloudBase Partners", "role_level": "Engineer", "approved_rate": 165},
    ])
    rows = []
    for index in range(240):
        rate = rates.iloc[index % len(rates)]
        hours = 20 + (index % 7)
        rows.append({
            "transaction_id": f"SYN-{index + 1:04d}", "date": f"2026-03-{index % 28 + 1:02d}",
            "vendor_name": rate["vendor_name"], "role_level": rate["role_level"],
            "hours": hours, "hourly_rate": int(rate["approved_rate"]),
            "total_amount": hours * int(rate["approved_rate"]),
            "invoice_ref": f"INV-SYN-{index + 1:04d}",
            "description": f"Work package {index + 1:04d}",
        })
    transactions = pd.DataFrame(rows)
    labelled = []
    for index in (40, 80, 120, 160, 200):
        transactions.loc[index, "hourly_rate"] = int(transactions.loc[index, "hourly_rate"] * 1.20)
        transactions.loc[index, "total_amount"] = (
            transactions.loc[index, "hours"] * transactions.loc[index, "hourly_rate"]
        )
        labelled.append({"type": "rate_violation", "row_indices": [index]})
    for column in ("vendor_name", "role_level", "hours", "hourly_rate", "total_amount", "description"):
        transactions.loc[210, column] = transactions.loc[0, column]
    labelled.append({"type": "duplicate", "row_indices": [0, 210]})
    transactions.loc[220, "hours"] = 450
    transactions.loc[220, "total_amount"] = 450 * transactions.loc[220, "hourly_rate"]
    # This rate has an external approval. The detector should still surface it
    # for a reviewer; the benchmark counts the flag as a business false positive.
    transactions.loc[230, "hourly_rate"] = int(transactions.loc[230, "hourly_rate"] * 1.20)
    transactions.loc[230, "total_amount"] = (
        transactions.loc[230, "hours"] * transactions.loc[230, "hourly_rate"]
    )
    labelled.extend([
        {"type": "outlier_zscore", "row_indices": [220]},
        {"type": "outlier_iqr", "row_indices": [220]},
    ])
    return transactions, rates, labelled


def run() -> dict:
    transactions, rates, labelled = benchmark()
    started = time.perf_counter()
    metrics = evaluate_anomaly_detection(transactions, rates, labelled)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {key: value for key, value in metrics.items() if key != "details"} | {
        "transactions": len(transactions), "labelled_type_row_pairs": sum(len(x["row_indices"]) for x in labelled),
        "known_approved_exceptions": len(KNOWN_APPROVED_EXCEPTIONS),
        "scan_duration_ms": elapsed_ms,
    }


if __name__ == "__main__":
    transactions, rates, labelled = benchmark()
    data_dir = BACKEND_DIR / "data"
    transactions.to_csv(data_dir / "benchmark_transactions.csv", index=False)
    rates.to_csv(data_dir / "benchmark_rate_card.csv", index=False)
    (data_dir / "benchmark_contract.txt").write_text(
        "Synthetic vendor exception approval\n\n"
        "Transaction SYN-0231 for NetSecure Solutions, Analyst has prior approval "
        "to bill 228 per hour. Reviewers should mark the rate-card flag as an "
        "approved exception and cite this note.\n",
        encoding="utf-8",
    )
    (data_dir / "benchmark_labels.json").write_text(json.dumps({
        "expected_anomalies": labelled,
        "known_approved_exceptions": [{"row_index": index, "reason": "Approved contract exception"}
                                      for index in KNOWN_APPROVED_EXCEPTIONS],
    }, indent=2), encoding="utf-8")
    print(json.dumps(run(), indent=2))
