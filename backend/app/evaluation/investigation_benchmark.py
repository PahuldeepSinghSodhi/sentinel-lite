"""Local performance comparison for scan-time matching and one-call briefs.

Run from backend/: python -m app.evaluation.investigation_benchmark
Ollama is optional; if unavailable, the scan comparison still runs.
"""
import json
import os
import statistics
import tempfile
import threading
import time
from unittest.mock import patch

import psutil

from app.cases import investigation, sources, store, workflow
from app.config import BACKEND_DIR


class _NoClauseMatcher:
    def __init__(self, *args):
        pass

    def suggest(self, *args):
        return {"status": "no_match", "evidence": None}


def _memory() -> dict:
    backend = psutil.Process().memory_info().rss
    ollama = 0
    for process in psutil.process_iter(["name"]):
        try:
            if "ollama" in (process.info["name"] or "").casefold():
                ollama += process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"backend_mb": round(backend / 1048576, 1),
            "ollama_mb": round(ollama / 1048576, 1)}


def _measure(action):
    stop = threading.Event()
    peaks = {"backend_mb": 0.0, "ollama_mb": 0.0}

    def sample():
        while not stop.is_set():
            now = _memory()
            for key in peaks:
                peaks[key] = max(peaks[key], now[key])
            stop.wait(0.05)

    worker = threading.Thread(target=sample, daemon=True)
    worker.start()
    started = time.perf_counter()
    try:
        result = action()
    finally:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        stop.set()
        worker.join()
    return result, {"milliseconds": elapsed, "peak_ram_mb": peaks}


def run() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        previous = os.environ.get("SENTINEL_CASES_DIR")
        os.environ["SENTINEL_CASES_DIR"] = directory
        try:
            case_id = store.create_case("Performance comparison")["id"]
            files = (("transactions", "benchmark_transactions.csv"),
                     ("rate_card", "benchmark_rate_card.csv"),
                     ("contract", "benchmark_contract.txt"))
            for kind, filename in files:
                path = BACKEND_DIR / "data" / filename
                store.save_file(case_id, kind, filename, path.read_bytes())
            _, indexing = _measure(lambda: sources.build_index(case_id))
            store.mark_started(case_id)
            baseline = []
            enhanced = []
            for _ in range(3):
                with patch("app.cases.workflow.clauses.Matcher", _NoClauseMatcher):
                    _, measured = _measure(lambda: workflow.scan_case(case_id))
                    baseline.append(measured)
                _, measured = _measure(lambda: workflow.scan_case(case_id))
                enhanced.append(measured)
            latest = store.get_case(case_id)["scans"][-1]
            finding = next((item for item in latest["findings"]
                            if item["type"] == "rate_violation"), latest["findings"][0])
            try:
                brief, generation = _measure(lambda: investigation.investigate(case_id, finding["id"]))
                generation["ollama_calls"] = 1
                generation["ollama_usage"] = brief["usage"]
                generation["model_load_observed"] = bool((brief["usage"].get("load_duration") or 0) > 0)
                cached, warm = _measure(lambda: investigation.investigate(case_id, finding["id"]))
                warm["ollama_calls"] = 0
                warm["same_saved_brief"] = cached == brief
                generation["warm_cached_request"] = warm
            except Exception as exc:
                generation = {"unavailable": str(exc), "successful_ollama_calls": 0,
                              "attempted_ollama_calls": "at most one"}
            return {"case_rows": latest["transactions_analyzed"], "indexing": indexing,
                    "baseline_scan_no_clause_matching": baseline,
                    "enhanced_scan_with_clause_matching": enhanced,
                    "baseline_median_ms": round(statistics.median(item["milliseconds"] for item in baseline), 1),
                    "enhanced_median_ms": round(statistics.median(item["milliseconds"] for item in enhanced), 1),
                    "investigation": generation,
                    "note": "Local sample measurements; order, model warmth, hardware and case size affect results. Human review time requires a separate timed study."}
        finally:
            if previous is None:
                os.environ.pop("SENTINEL_CASES_DIR", None)
            else:
                os.environ["SENTINEL_CASES_DIR"] = previous


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
