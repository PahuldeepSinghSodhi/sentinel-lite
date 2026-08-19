"""Verification script for Milestone 5 -- Anomaly Explanation.

Tests the explainer module that uses the local Ollama LLM to generate
human-readable explanations for detected anomalies.

Run from the backend/ directory:
    python -m tests.test_explainer
"""
import sys
from pathlib import Path

# Ensure the backend directory is on the Python path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.anomaly.explainer import explain_anomaly


def run_explainer_tests():
    """Test the anomaly explainer with sample anomaly data."""
    
    print("\n" + "=" * 70)
    print("TESTING ANOMALY EXPLAINER (Milestone 5)")
    print("=" * 70)
    
    all_passed = True
    
    # -- Test 1: Rate violation explanation --------------------------------
    print("\n" + "-" * 60)
    print("TEST 1: Explain a rate violation anomaly")
    print("-" * 60)
    
    rate_anomaly = {
        "type": "rate_violation",
        "severity": "high",
        "description": "Apex Consulting billed $950/hr for Architect role, but approved rate is $300/hr (217% over approved rate).",
        "details": {
            "vendor": "Apex Consulting",
            "role": "Architect",
            "billed_rate": 950,
            "approved_rate": 300,
            "overcharge_pct": 216.67,
        },
        "row_indices": [11],
    }
    
    result = explain_anomaly(rate_anomaly)
    print(f"  Status: {result['status']}")
    print(f"  Type: {result['anomaly_type']}")
    print(f"  Explanation:\n{result['explanation']}")
    
    if result["status"] == "success" and len(result["explanation"]) > 50:
        print("\n  [PASS] Generated a substantive explanation")
    else:
        print("\n  [FAIL] Explanation was missing or too short")
        all_passed = False
    
    # -- Test 2: Duplicate explanation ------------------------------------
    print("\n" + "-" * 60)
    print("TEST 2: Explain a duplicate anomaly")
    print("-" * 60)
    
    dup_anomaly = {
        "type": "duplicate",
        "severity": "high",
        "description": "Found 2 rows with identical content (possible duplicate billing).",
        "details": {
            "duplicate_count": 2,
            "sample_row": {
                "vendor_name": "Apex Consulting",
                "service_category": "Cloud Services",
                "role_level": "Senior Engineer",
                "hours": 40,
                "hourly_rate": 250,
                "total_amount": 10000,
                "description": "Cloud Architecture Assessment",
            },
        },
        "row_indices": [0, 8],
    }
    
    result = explain_anomaly(dup_anomaly)
    print(f"  Status: {result['status']}")
    print(f"  Explanation:\n{result['explanation']}")
    
    if result["status"] == "success" and len(result["explanation"]) > 50:
        print("\n  [PASS] Generated a substantive explanation")
    else:
        print("\n  [FAIL] Explanation was missing or too short")
        all_passed = False
    
    # -- Test 3: Outlier explanation --------------------------------------
    print("\n" + "-" * 60)
    print("TEST 3: Explain a statistical outlier")
    print("-" * 60)
    
    outlier_anomaly = {
        "type": "outlier_zscore",
        "severity": "medium",
        "description": "Value 950 in column 'hourly_rate' is a statistical outlier (Z-score > 2).",
        "details": {
            "column": "hourly_rate",
            "value": 950,
            "z_score": 3.41,
        },
        "row_indices": [11],
    }
    
    result = explain_anomaly(outlier_anomaly)
    print(f"  Status: {result['status']}")
    print(f"  Explanation:\n{result['explanation']}")
    
    if result["status"] == "success" and len(result["explanation"]) > 50:
        print("\n  [PASS] Generated a substantive explanation")
    else:
        print("\n  [FAIL] Explanation was missing or too short")
        all_passed = False
    
    # -- Summary ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("EXPLAINER TEST SUMMARY")
    print("=" * 70)
    
    if all_passed:
        print("\n>>> ALL EXPLAINER TESTS PASSED -- Milestone 5 is complete!")
    else:
        print("\n[!!] SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    run_explainer_tests()
