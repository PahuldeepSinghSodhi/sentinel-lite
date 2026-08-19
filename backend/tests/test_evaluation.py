import os
import pandas as pd
from app.evaluation.harness import evaluate_rag, evaluate_anomaly_detection
from app.vectorstore.faiss_store import FAISSStore

def main():
    print("========================================")
    print(" Sentinel-Lite Evaluation Harness ")
    print("========================================\n")

    # 1. Evaluate Anomaly Detection
    print("Running Anomaly Detection Evaluation...")
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    tx_file = os.path.join(data_dir, "sample_transactions.csv")
    rc_file = os.path.join(data_dir, "rate_card.csv")

    try:
        df = pd.read_csv(tx_file)
        reference_df = pd.read_csv(rc_file)
    except Exception as e:
        print(f"Error loading CSV files: {e}")
        return

    # Expected anomalies based on manual inspection of sample data:
    # - Duplicates: Row indices 0 and 8 (TXN-001 and TXN-009)
    # - Rate Violations:
    #     Row 2 (DataFlow Inc, Senior Engineer: billed 275, approved 250)
    #     Row 3 (DataFlow Inc, Senior Engineer: billed 275, approved 250)
    #     Row 7 (DataFlow Inc, QA Engineer: billed 225, approved 200)
    #     Row 11 (Apex Consulting, Architect: billed 950, approved 300)
    # - Outliers (Z-score / IQR): Row 11 (Hourly rate 950 is an extreme outlier)
    
    expected_anomalies = [
        {"type": "duplicate", "row_indices": [0, 8]},
        {"type": "rate_violation", "row_indices": [2]},
        {"type": "rate_violation", "row_indices": [3]},
        {"type": "rate_violation", "row_indices": [7]},
        {"type": "rate_violation", "row_indices": [11]},
        {"type": "outlier_zscore", "row_indices": [11]},
        {"type": "outlier_iqr", "row_indices": [11]},
    ]

    anomaly_metrics = evaluate_anomaly_detection(df, reference_df, expected_anomalies)
    
    print(f"Anomaly Detection Metrics:")
    print(f"  Precision:       {anomaly_metrics.get('precision', 0.0):.2f}")
    print(f"  Recall:          {anomaly_metrics.get('recall', 0.0):.2f}")
    print(f"  F1 Score:        {anomaly_metrics.get('f1_score', 0.0):.2f}")
    print(f"  True Positives:  {anomaly_metrics.get('true_positives', 0)}")
    print(f"  False Positives: {anomaly_metrics.get('false_positives', 0)}")
    print(f"  False Negatives: {anomaly_metrics.get('false_negatives', 0)}")
    print("\n----------------------------------------\n")

    # 2. Evaluate RAG
    print("Running RAG Evaluation...")
    # Initialize FAISS store and load the existing index if available
    store_dir = os.path.join(os.path.dirname(__file__), "..", "index_data")
    store = FAISSStore(index_dir=store_dir)
    store.load()

    rag_test_cases = [
        {
            "query": "What is the policy for meal expenses?",
            "expected_sources": ["company_policy.txt"],
            "expected_terms": ["meal", "expense"]
        },
        {
            "query": "What services did Apex Consulting provide?",
            "expected_sources": ["service_agreement.txt", "invoice_001.txt", "invoice_002.txt"],
            "expected_terms": ["apex", "consulting"]
        }
    ]

    rag_metrics = evaluate_rag(store, rag_test_cases)
    
    print(f"RAG Evaluation Metrics:")
    print(f"  Total Cases:        {rag_metrics.get('total_cases', 0)}")
    print(f"  Retrieval Recall:   {rag_metrics.get('retrieval_recall', 0.0):.2f}")
    print(f"  Grounding Accuracy: {rag_metrics.get('grounding_accuracy', 0.0):.2f}")
    print(f"  Avg Confidence:     {rag_metrics.get('avg_confidence', 0.0):.2f}")
    
    print("\nDetailed RAG Results:")
    for result in rag_metrics.get("per_case_results", []):
        print(f"  Query: {result['query']}")
        print(f"    Recall: {result['recall']:.2f}, Accuracy: {result['accuracy']:.2f}, Confidence: {result['confidence']:.2f}")
        print(f"    Answer: {result['answer'][:80]}...")
        
    print("\n========================================")
    print(" Evaluation Complete ")
    print("========================================\n")

if __name__ == "__main__":
    main()
