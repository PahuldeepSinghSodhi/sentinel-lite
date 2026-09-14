"""20-Question Evaluation Suite for Sentinel-Lite.

This script runs the full evaluation harness with:
- 20 benchmark RAG questions covering all sample documents
- Semantic similarity scoring (cosine similarity on MiniLM embeddings)
- Anomaly detection precision/recall/F1 evaluation

Each question has a reference answer that represents the "ideal" response.
The harness embeds both the AI's actual answer and the reference answer,
then measures how semantically similar they are (0.0 = unrelated, 1.0 = identical).

Run from the backend/ directory:
    python -m tests.test_evaluation
"""
import sys
import os

# Ensure backend dir is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from app.evaluation.harness import evaluate_rag, evaluate_anomaly_detection
from app.ingestion.pipeline import load_existing_index, ingest_documents


# =========================================================================
# 20 BENCHMARK RAG QUESTIONS
# =========================================================================
# These questions span all 5 sample documents:
#   - company_policy.txt (procurement & vendor policy)
#   - invoice_001.txt (Apex Consulting invoice)
#   - invoice_002.txt (DataFlow Inc invoice)
#   - service_agreement.txt (MSA-2023-089)
#   - rate_card.csv (approved billing rates)

RAG_TEST_CASES = [
    # --- Company Policy Questions (1-7) ---
    {
        "query": "What approval is needed for a purchase of $15,000?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "A purchase of $15,000 requires Department Director approval, as it falls in the $5,000 to $25,000 range.",
        "expected_terms": ["director"],
    },
    {
        "query": "What is the maximum hotel rate allowed per night?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "Hotel accommodations are capped at a maximum of $500 per night, excluding taxes.",
        "expected_terms": ["500"],
    },
    {
        "query": "What is the daily meal expense cap?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "Meals and incidentals are capped at $75 per meal or $150 per day total.",
        "expected_terms": ["75", "150"],
    },
    {
        "query": "Who approves purchases over $100,000?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "Purchases over $100,000 require C-Suite approval from the CFO or CEO, plus formal notification to the Board of Directors Audit Committee.",
        "expected_terms": ["cfo", "ceo"],
    },
    {
        "query": "What is required for vendor contracts exceeding $10,000?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "Vendor contracts exceeding $10,000 in annual cumulative value require comprehensive background checks, legal reviews, and financial solvency evaluations.",
        "expected_terms": ["background", "legal"],
    },
    {
        "query": "What is the maximum allowed rate variance before VP approval is required?",
        "expected_sources": ["company_policy.txt"],
        "reference_answer": "Any positive billing rate variance exceeding 5% above the approved rate card rate requires prior written justification and explicit written approval from the departmental Vice President.",
        "expected_terms": ["5%"],
    },
    {
        "query": "What are the standard payment terms for vendor invoices?",
        "expected_sources": ["company_policy.txt", "service_agreement.txt"],
        "reference_answer": "The default payment terms are Net 30 days from invoice receipt date, unless alternative terms are negotiated in an MSA or SOW.",
        "expected_terms": ["net 30"],
    },

    # --- Invoice 001 Questions (8-11) ---
    {
        "query": "What is the total amount on the Apex Consulting invoice?",
        "expected_sources": ["invoice_001.txt"],
        "reference_answer": "The total amount due on the Apex Consulting invoice INV-2024-0456 is $45,000.",
        "expected_terms": ["45,000"],
    },
    {
        "query": "What services did Apex Consulting provide in their invoice?",
        "expected_sources": ["invoice_001.txt"],
        "reference_answer": "Apex Consulting provided Cloud Architecture Assessment, Migration Planning and Design, Data Migration Execution, and Post-Migration Testing and Validation.",
        "expected_terms": ["cloud", "migration"],
    },
    {
        "query": "What is the PO reference number on the Apex Consulting invoice?",
        "expected_sources": ["invoice_001.txt"],
        "reference_answer": "The PO reference number on the Apex Consulting invoice is PO-2024-8841.",
        "expected_terms": ["po-2024-8841"],
    },
    {
        "query": "How many hours were billed for Data Migration Execution?",
        "expected_sources": ["invoice_001.txt"],
        "reference_answer": "Data Migration Execution was billed for 80 hours at $200 per hour, totaling $16,000.",
        "expected_terms": ["80"],
    },

    # --- Invoice 002 Questions (12-14) ---
    {
        "query": "What is the total amount on the DataFlow Inc invoice?",
        "expected_sources": ["invoice_002.txt"],
        "reference_answer": "The total amount due on the DataFlow Inc invoice INV-2024-0512 is $28,625.",
        "expected_terms": ["28,625"],
    },
    {
        "query": "What hourly rate did DataFlow Inc charge for ETL Pipeline Development?",
        "expected_sources": ["invoice_002.txt"],
        "reference_answer": "DataFlow Inc charged $275 per hour for ETL Pipeline Development.",
        "expected_terms": ["275"],
    },
    {
        "query": "What project was DataFlow Inc working on?",
        "expected_sources": ["invoice_002.txt"],
        "reference_answer": "DataFlow Inc was working on the Data Pipeline Development and Optimization project.",
        "expected_terms": ["data pipeline"],
    },

    # --- Service Agreement Questions (15-18) ---
    {
        "query": "What is the MSA identifier for the service agreement?",
        "expected_sources": ["service_agreement.txt"],
        "reference_answer": "The Master Service Agreement identifier is MSA-2023-089.",
        "expected_terms": ["msa-2023-089"],
    },
    {
        "query": "What is the maximum annual rate increase allowed under the MSA?",
        "expected_sources": ["service_agreement.txt"],
        "reference_answer": "Annual rate increases are strictly capped at a maximum of 3% per calendar year and require 90 days prior written notification.",
        "expected_terms": ["3"],
    },
    {
        "query": "What is the SLA response time for critical issues?",
        "expected_sources": ["service_agreement.txt"],
        "reference_answer": "The initial response time for Critical Priority 1 issues is within 4 hours, with a target resolution time of 24 hours.",
        "expected_terms": ["4 hours"],
    },
    {
        "query": "What is the system uptime guarantee in the service agreement?",
        "expected_sources": ["service_agreement.txt"],
        "reference_answer": "The managed infrastructure has a 99.9% monthly uptime commitment.",
        "expected_terms": ["99.9"],
    },

    # --- Rate Card Questions (19-20) ---
    {
        "query": "What is the approved hourly rate for a DataFlow Inc Senior Engineer?",
        "expected_sources": ["rate_card.csv"],
        "reference_answer": "The approved hourly rate for a DataFlow Inc Senior Engineer is $250.",
        "expected_terms": ["250"],
    },
    {
        "query": "What is the approved rate for a NetSecure Solutions Penetration Tester?",
        "expected_sources": ["rate_card.csv"],
        "reference_answer": "The approved hourly rate for a NetSecure Solutions Penetration Tester is $320.",
        "expected_terms": ["320"],
    },
]


# =========================================================================
# EXPECTED ANOMALIES (for anomaly detection evaluation)
# =========================================================================
EXPECTED_ANOMALIES = [
    {"type": "duplicate", "row_indices": [0, 8]},
    {"type": "rate_violation", "row_indices": [2]},
    {"type": "rate_violation", "row_indices": [3]},
    {"type": "rate_violation", "row_indices": [7]},
    {"type": "rate_violation", "row_indices": [11]},
    {"type": "outlier_zscore", "row_indices": [11]},
    {"type": "outlier_iqr", "row_indices": [11]},
]


def main():
    print("\n" + "=" * 70)
    print("  SENTINEL-LITE EVALUATION HARNESS")
    print("  20-Question Benchmark with Semantic Similarity Scoring")
    print("=" * 70)

    # -- Load or build the document index ----------------------------------
    print("\n[1/3] Loading document index...")
    try:
        store = load_existing_index()
        print(f"      Loaded existing index: {store.total_vectors} vectors")
    except FileNotFoundError:
        print("      No existing index. Running ingestion...")
        store = ingest_documents()

    # -- RAG Evaluation ----------------------------------------------------
    print(f"\n[2/3] Running RAG evaluation ({len(RAG_TEST_CASES)} questions)...")
    print("-" * 70)

    rag_metrics = evaluate_rag(store, RAG_TEST_CASES)

    for i, result in enumerate(rag_metrics["per_case_results"], 1):
        sim_pct = result["semantic_similarity"] * 100
        status = "PASS" if sim_pct >= 50 else "FAIL"
        print(f"  Q{i:02d} [{status}] Similarity: {sim_pct:5.1f}% | "
              f"Recall: {result['recall']:.0%} | "
              f"Query: {result['query'][:50]}...")

    print("-" * 70)
    print(f"\n  RAG RESULTS:")
    print(f"    Retrieval Recall:      {rag_metrics['retrieval_recall']:.1%}")
    print(f"    Semantic Similarity:   {rag_metrics['semantic_similarity']:.1%}")
    print(f"    Keyword Grounding:     {rag_metrics['grounding_accuracy']:.1%}")
    print(f"    Avg Confidence:        {rag_metrics['avg_confidence']:.1%}")

    passed = sum(
        1 for r in rag_metrics["per_case_results"]
        if r["semantic_similarity"] >= 0.5
    )
    print(f"    Questions Passed:      {passed}/{rag_metrics['total_cases']}")

    # -- Anomaly Detection Evaluation --------------------------------------
    print(f"\n[3/3] Running anomaly detection evaluation...")
    print("-" * 70)

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    tx_file = os.path.join(data_dir, "sample_transactions.csv")
    rc_file = os.path.join(data_dir, "rate_card.csv")

    df = pd.read_csv(tx_file)
    reference_df = pd.read_csv(rc_file)

    anomaly_metrics = evaluate_anomaly_detection(df, reference_df, EXPECTED_ANOMALIES)

    print(f"  Precision:       {anomaly_metrics['precision']:.1%}")
    print(f"  Recall:          {anomaly_metrics['recall']:.1%}")
    print(f"  F1 Score:        {anomaly_metrics['f1_score']:.1%}")
    print(f"  True Positives:  {anomaly_metrics['true_positives']}")
    print(f"  False Positives: {anomaly_metrics['false_positives']}")
    print(f"  False Negatives: {anomaly_metrics['false_negatives']}")

    # -- Final Summary -----------------------------------------------------
    print("\n" + "=" * 70)
    print("  EVALUATION SUMMARY")
    print("=" * 70)
    print(f"  RAG: {passed}/{rag_metrics['total_cases']} questions passed "
          f"(>= 50% semantic similarity)")
    print(f"  Anomaly Detection: F1 = {anomaly_metrics['f1_score']:.1%}")

    # Exit with non-zero if too many RAG questions fail (for CI)
    # In GitHub Actions (CI=true), Ollama isn't available, so we only check retrieval recall.
    is_ci = os.environ.get("CI") == "true"
    
    if is_ci:
        if rag_metrics['retrieval_recall'] < 0.8:
            print(f"\n  [FAIL] Retrieval recall too low ({rag_metrics['retrieval_recall']:.1%})")
            sys.exit(1)
        else:
            print("\n  [PASS] CI Evaluation complete (retrieval-only).")
    else:
        if passed < 10:  # At least half should pass when LLM is available
            print("\n  [FAIL] Too many RAG questions failed.")
            sys.exit(1)
        else:
            print("\n  [PASS] Evaluation complete.")


if __name__ == "__main__":
    main()
