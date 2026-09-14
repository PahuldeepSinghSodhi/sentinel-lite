"""Evaluation Harness -- Automated benchmarking for RAG and anomaly detection.

This module provides two evaluation functions:

1. evaluate_rag(): Tests the RAG pipeline with semantic similarity scoring.
   Instead of checking for exact keyword matches (brittle), it uses the
   same embedding model (MiniLM) to compute cosine similarity between
   the AI's answer and the expected reference answer. This measures
   whether the answer MEANS the right thing, even if the words differ.

2. evaluate_anomaly_detection(): Tests the anomaly detector using standard
   precision/recall/F1 metrics.

Usage:
    python -m tests.test_evaluation
"""
import math
import numpy as np
from typing import Dict, Any, List

from app.rag.pipeline import query_rag
from app.anomaly.detector import detect_anomalies
from app.embeddings.model import get_embedding_model


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Returns a float in [-1, 1] where 1 means identical direction
    (semantically identical) and 0 means orthogonal (unrelated).
    """
    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def evaluate_rag(store, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate the RAG pipeline using semantic similarity scoring.

    For each test case:
    1. Runs query_rag() with the query
    2. Checks if expected sources appear in retrieved results (retrieval recall)
    3. Computes SEMANTIC SIMILARITY between the AI answer and the
       expected reference answer using the MiniLM embedding model
    4. Records the confidence score from the pipeline

    Args:
        store: The FAISSStore containing indexed document chunks.
        test_cases: A list of dicts, each with:
            - 'query': str -- the question to ask
            - 'expected_sources': list[str] -- filenames that should be retrieved
            - 'reference_answer': str -- what a correct answer should say
            - 'expected_terms': list[str] -- (optional) keyword fallback

    Returns:
        dict with aggregate metrics and per-case results:
            - total_cases: int
            - retrieval_recall: float (avg fraction of expected sources found)
            - semantic_similarity: float (avg cosine similarity to reference)
            - grounding_accuracy: float (avg keyword match rate, for backward compat)
            - avg_confidence: float
            - per_case_results: list[dict]
    """
    total_cases = len(test_cases)
    if total_cases == 0:
        return {
            "total_cases": 0,
            "retrieval_recall": 0.0,
            "semantic_similarity": 0.0,
            "grounding_accuracy": 0.0,
            "avg_confidence": 0.0,
            "per_case_results": []
        }

    # Load the embedding model for semantic similarity scoring
    embed_model = get_embedding_model()

    total_recall = 0.0
    total_similarity = 0.0
    total_accuracy = 0.0
    total_confidence = 0.0
    per_case_results = []

    for case in test_cases:
        query = case.get("query", "")
        expected_sources = case.get("expected_sources", [])
        reference_answer = case.get("reference_answer", "")
        expected_terms = case.get("expected_terms", [])

        try:
            rag_result = query_rag(query, store)
            answer = rag_result.get("answer", "")
            retrieved_sources = [
                src.get("source", "") for src in rag_result.get("sources", [])
            ]
            confidence_score = rag_result.get("confidence", {}).get(
                "overall_confidence", 0.0
            )
        except Exception as e:
            print(f"  [WARN] LLM query failed for '{query[:50]}...': {e}")
            print("         Falling back to retrieval-only evaluation.")

            # Fallback: test retrieval without LLM
            query_embedding = embed_model.embed_query(query)
            chunks = store.search(query_embedding, top_k=5)

            answer = ""
            retrieved_sources = [c.get("source", "") for c in chunks]
            confidence_score = 0.0

        # -- Metric 1: Retrieval Recall ------------------------------------
        found_sources = sum(
            1 for exp in expected_sources
            if any(exp in r for r in retrieved_sources)
        )
        recall = (
            found_sources / len(expected_sources) if expected_sources else 1.0
        )

        # -- Metric 2: Semantic Similarity ---------------------------------
        # Embed both the reference answer and the actual answer, then
        # compute cosine similarity. This is much more robust than keyword
        # matching because it captures meaning, not just exact words.
        if answer and reference_answer:
            answer_vec = embed_model.embed([answer])[0]
            reference_vec = embed_model.embed([reference_answer])[0]
            similarity = cosine_similarity(answer_vec, reference_vec)
        else:
            similarity = 0.0

        # -- Metric 3: Keyword Grounding (backward compatibility) ----------
        if answer and expected_terms:
            answer_lower = answer.lower()
            found_terms = sum(
                1 for t in expected_terms if t.lower() in answer_lower
            )
            accuracy = found_terms / len(expected_terms)
        else:
            accuracy = 0.0

        total_recall += recall
        total_similarity += similarity
        total_accuracy += accuracy
        total_confidence += confidence_score

        per_case_results.append({
            "query": query,
            "expected_sources": expected_sources,
            "reference_answer": reference_answer[:100] + "..."
                if len(reference_answer) > 100 else reference_answer,
            "retrieved_sources": retrieved_sources,
            "answer_preview": answer[:120] + "..."
                if len(answer) > 120 else answer,
            "recall": round(recall, 3),
            "semantic_similarity": round(similarity, 3),
            "keyword_accuracy": round(accuracy, 3),
            "confidence": round(confidence_score, 3),
        })

    return {
        "total_cases": total_cases,
        "retrieval_recall": round(total_recall / total_cases, 3),
        "semantic_similarity": round(total_similarity / total_cases, 3),
        "grounding_accuracy": round(total_accuracy / total_cases, 3),
        "avg_confidence": round(total_confidence / total_cases, 3),
        "per_case_results": per_case_results,
    }


def evaluate_anomaly_detection(
    df, reference_df, expected_anomalies: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Evaluate the anomaly detection system with precision/recall/F1.

    Args:
        df: The DataFrame of transactions to analyze.
        reference_df: Optional reference DataFrame (e.g., rate card).
        expected_anomalies: List of expected anomalies, each dict has:
            - 'type': str (e.g., "duplicate")
            - 'row_indices': list of int

    Returns:
        dict with precision, recall, f1_score, and detailed counts.
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

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )
    f1_score = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1_score": round(f1_score, 3),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "details": detected_anomalies,
    }
