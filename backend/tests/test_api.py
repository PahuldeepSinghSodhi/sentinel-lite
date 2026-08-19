"""Verification script for Milestone 3 -- FastAPI REST API.

Tests the API endpoints using FastAPI's TestClient.
Run from the backend/ directory:
    python -m tests.test_api
"""
import sys
import os

# Ensure backend dir is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Removed dummy Gemini key as we are using local Ollama now

from fastapi.testclient import TestClient
from app.main import app


def run_api_tests():
    """Test all API endpoints."""
    print("\n" + "=" * 70)
    print("TESTING FASTAPI ENDPOINTS")
    print("=" * 70)
    
    all_passed = True
    
    with TestClient(app) as client:
        # -- Test 1: Health check -------------------------------------------
        print("\n" + "-" * 60)
        print("TEST 1: GET / (health check)")
        print("-" * 60)
        
        response = client.get("/")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "healthy"
        assert "documents_indexed" in data
        print(f"  [PASS] Status: {data['status']}, Docs: {data['documents_indexed']}")
        
        # -- Test 2: Empty question -----------------------------------------
        print("\n" + "-" * 60)
        print("TEST 2: POST /query with empty question (expect 400)")
        print("-" * 60)
        
        response = client.post("/query", json={"question": "", "top_k": 3})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print(f"  [PASS] Got 400: {response.json()['detail']}")
        
        # -- Test 3: Valid query --------------------------------------------
        print("\n" + "-" * 60)
        print("TEST 3: POST /query with valid question")
        print("-" * 60)
        
        response = client.post("/query", json={"question": "What is the procurement policy?", "top_k": 3})
        if response.status_code == 200:
            data = response.json()
            assert "answer" in data
            assert "sources" in data
            print(f"  [PASS] Got answer ({len(data['answer'])} chars), {len(data['sources'])} sources")
        else:
            print(f"  [FAIL] Unexpected status: {response.status_code}")
            all_passed = False
        
        # -- Test 4: POST /anomalies ----------------------------------------
        print("\n" + "-" * 60)
        print("TEST 4: POST /anomalies")
        print("-" * 60)
        
        response = client.post("/anomalies")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["total_anomalies"] > 0, "Expected at least 1 anomaly"
        assert "severity_summary" in data
        assert "anomalies" in data
        print(f"  [PASS] Found {data['total_anomalies']} anomalies across {data['transactions_analyzed']} transactions")
        print(f"         Severity: {data['severity_summary']}")
        
        # -- Test 5: POST /ingest -------------------------------------------
        print("\n" + "-" * 60)
        print("TEST 5: POST /ingest (re-index)")
        print("-" * 60)
        
        response = client.post("/ingest")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "success"
        assert data["chunks_indexed"] > 0
        print(f"  [PASS] Re-indexed: {data['chunks_indexed']} chunks")
    
    # -- Summary --------------------------------------------------------
    print("\n" + "=" * 70)
    print("API TEST SUMMARY")
    print("=" * 70)
    
    if all_passed:
        print("\n>>> ALL API TESTS PASSED -- Milestone 3 is complete!")
    else:
        print("\n[!!] SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    run_api_tests()
