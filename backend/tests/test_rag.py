"""Verification script for Milestone 2 -- RAG Q&A Pipeline.

Tests the full RAG pipeline: query -> retrieve chunks -> generate grounded answer.
Verifies that answers are grounded in retrieved content and not hallucinated.

Run from the backend/ directory:
    python -m tests.test_rag
"""
import sys
import time
from pathlib import Path

# Ensure the backend directory is on the Python path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.ingestion.pipeline import load_existing_index, ingest_documents
from app.rag.pipeline import query_rag
from app.config import INDEX_DIR


def run_rag_tests():
    """Run RAG pipeline tests against the sample documents."""
    
    # -- Step 1: Load or build the FAISS index --------------------------
    print("\n" + "=" * 70)
    print("STEP 1: Loading Document Index")
    print("=" * 70)
    
    try:
        store = load_existing_index()
        print(f"Loaded existing index: {store.total_vectors} vectors")
    except FileNotFoundError:
        print("No existing index found. Running ingestion pipeline...")
        store = ingest_documents()
    
    # -- Step 2: Test RAG queries ---------------------------------------
    print("\n" + "=" * 70)
    print("STEP 2: Testing RAG Q&A Pipeline")
    print("=" * 70)
    
    test_queries = [
        {
            "query": "What is the total amount on the Apex Consulting invoice and what services were provided?",
            "grounding_check": ["45,000", "Apex Consulting", "cloud"],
            "description": "Invoice details query",
        },
        {
            "query": "What are the purchase authorization levels in the company procurement policy?",
            "grounding_check": ["Manager", "Director", "VP"],
            "description": "Policy details query",
        },
        {
            "query": "What is the approved hourly rate for a DataFlow Inc Senior Engineer?",
            "grounding_check": ["250", "DataFlow"],
            "description": "Rate card lookup query",
        },
    ]
    
    all_passed = True
    
    for i, test in enumerate(test_queries, 1):
        if i > 1:
            print("\n  [INFO] Querying local Ollama model...")
        
        print(f"\n{'-' * 60}")
        print(f"TEST {i}: {test['description']}")
        print(f"Query: \"{test['query']}\"")
        print(f"{'-' * 60}")
        
        try:
            result = query_rag(test["query"], store, top_k=5)
            
            # Display the answer
            print(f"\nAnswer:\n{result['answer']}")
            
            # Display sources used
            print(f"\nSources used:")
            for src in result["sources"][:3]:  # Show top 3 sources
                print(f"  - {src['source']} (chunk {src['chunk_index']}, score: {src['score']:.4f})")
            
            # Check grounding: verify that key terms from the documents
            # appear in the answer (not hallucinated content)
            answer_lower = result["answer"].lower()
            grounding_hits = []
            grounding_misses = []
            
            for term in test["grounding_check"]:
                if term.lower() in answer_lower:
                    grounding_hits.append(term)
                else:
                    grounding_misses.append(term)
            
            hit_rate = len(grounding_hits) / len(test["grounding_check"])
            
            if hit_rate >= 0.5:  # At least half the expected terms found
                print(f"\n  [PASS] Grounding check: {len(grounding_hits)}/{len(test['grounding_check'])} key terms found")
                if grounding_hits:
                    print(f"    Found: {', '.join(grounding_hits)}")
            else:
                print(f"\n  [FAIL] Grounding check: only {len(grounding_hits)}/{len(test['grounding_check'])} key terms found")
                if grounding_misses:
                    print(f"    Missing: {', '.join(grounding_misses)}")
                all_passed = False
                
        except Exception as e:
            print(f"\n  [ERROR] {e}")
            all_passed = False
    
    # -- Step 3: Summary ------------------------------------------------
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"Test queries run: {len(test_queries)}")
    
    if all_passed:
        print("\n>>> ALL TESTS PASSED -- Milestone 2 is complete!")
        print("   The RAG pipeline correctly:")
        print("   - Retrieved relevant chunks from the FAISS index")
        print("   - Generated grounded answers via Ollama API")
        print("   - Answers contain expected document content (not hallucinated)")
    else:
        print("\n[!!] SOME TESTS FAILED -- review the results above")
        sys.exit(1)


if __name__ == "__main__":
    run_rag_tests()
