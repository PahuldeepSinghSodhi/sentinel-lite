import math
from typing import Dict, Any, List

from app.rag.pipeline import query_rag
from app.anomaly.detector import detect_anomalies

def evaluate_rag(store, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates the RAG pipeline by running a set of test cases against it.

    Args:
        store: The FAISS vector store to query against.
        test_cases: A list of dicts, each with:
            - 'query': str
            - 'expected_sources': list[str] (filenames)
            - 'expected_terms': list[str] (terms that should appear in answer)

    Returns:
        dict containing aggregate metrics and per-case results.
    """
    total_cases = len(test_cases)
    if total_cases == 0:
        return {
            "total_cases": 0,
            "retrieval_recall": 0.0,
            "grounding_accuracy": 0.0,
            "avg_confidence": 0.0,
            "per_case_results": []
        }

    total_recall = 0.0
    total_accuracy = 0.0
    total_confidence = 0.0
    per_case_results = []

    for case in test_cases:
        query = case.get("query", "")
        expected_sources = case.get("expected_sources", [])
        expected_terms = case.get("expected_terms", [])

        try:
            # query_rag returns {"answer": str, "sources": list[dict], "confidence": dict, "query": str}
            rag_result = query_rag(query, store)
            answer = rag_result.get("answer", "")
            # extract filenames from sources list of dicts
            retrieved_sources = [src.get("source", "") for src in rag_result.get("sources", [])]
            confidence_score = rag_result.get("confidence", {}).get("overall_confidence", 0.0)
        except Exception as e:
            print(f"Error querying RAG for '{query}': {e}")
            print("Skipping grounding check and testing retrieval recall only.")
            
            # Fallback to manual retrieval if LLM fails
            from app.embeddings.model import get_embedding_model
            model = get_embedding_model()
            query_embedding = model.embed_query(query)
            # Default top_k is 3 from config
            chunks = store.search(query_embedding, top_k=3)
            
            answer = ""
            retrieved_sources = [chunk.get("source", "") for chunk in chunks]
            confidence_score = 0.0

        # Compute retrieval recall: fraction of expected sources found in retrieved top-k
        found_sources = 0
        for exp_src in expected_sources:
            if any(exp_src in r_src for r_src in retrieved_sources):
                found_sources += 1
        recall = found_sources / len(expected_sources) if expected_sources else 1.0

        # Compute grounding accuracy: fraction of expected terms in the answer
        # If answer is empty (LLM failed), accuracy is not meaningful, but we record 0.
        found_terms = 0
        answer_lower = answer.lower()
        if answer:
            for term in expected_terms:
                if term.lower() in answer_lower:
                    found_terms += 1
            accuracy = found_terms / len(expected_terms) if expected_terms else 1.0
        else:
            accuracy = 0.0

        total_recall += recall
        total_accuracy += accuracy
        total_confidence += confidence_score

        per_case_results.append({
            "query": query,
            "expected_sources": expected_sources,
            "expected_terms": expected_terms,
            "retrieved_sources": retrieved_sources,
            "answer": answer,
            "recall": recall,
            "accuracy": accuracy,
            "confidence": confidence_score
        })

    return {
        "total_cases": total_cases,
        "retrieval_recall": total_recall / total_cases,
        "grounding_accuracy": total_accuracy / total_cases,
        "avg_confidence": total_confidence / total_cases,
        "per_case_results": per_case_results,
    }


def evaluate_anomaly_detection(df, reference_df, expected_anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates the anomaly detection system.

    Args:
        df: The dataframe to analyze.
        reference_df: Optional reference dataframe.
        expected_anomalies: list of expected anomalies, each dict has:
            - 'type': str (e.g., "duplicate")
            - 'row_indices': list of int

    Returns:
        dict containing precision, recall, f1_score, and detailed counts.
    """
    try:
        detected_anomalies = detect_anomalies(df, reference_df)
    except Exception as e:
        print(f"Error detecting anomalies: {e}")
        detected_anomalies = []

    # Map expected anomalies into a set of (type, row_index)
    expected_set = set()
    for exp in expected_anomalies:
        a_type = exp.get("type", "")
        for idx in exp.get("row_indices", []):
            expected_set.add((a_type, idx))

    # Map detected anomalies into a set of (type, row_index)
    detected_set = set()
    for det in detected_anomalies:
        a_type = det.get("type", "")
        for idx in det.get("row_indices", []):
            detected_set.add((a_type, idx))

    true_positives = len(expected_set.intersection(detected_set))
    false_positives = len(detected_set - expected_set)
    false_negatives = len(expected_set - detected_set)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0

    if precision + recall > 0:
        f1_score = 2 * (precision * recall) / (precision + recall)
    else:
        f1_score = 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "details": detected_anomalies
    }
