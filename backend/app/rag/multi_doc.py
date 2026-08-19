"""Multi-document Reasoning -- Chain of Thought (Milestone 7).

This module implements multi-document reasoning for complex queries
that require cross-referencing information from multiple sources.

For example:
  "Is the rate billed by DataFlow Inc consistent with the approved rate card?"
  -- requires reading both invoice data AND the rate card, then comparing.

The approach:
1. Break the user's question into sub-questions (decomposition)
2. Retrieve context for each sub-question independently
3. Synthesize findings across all sub-questions into a final answer
4. Show the chain of reasoning steps so the answer is transparent

This is different from the basic RAG pipeline (pipeline.py), which
does a single retrieval pass. Multi-doc reasoning does MULTIPLE
retrieval passes and explicitly reasons across them.
"""
from app.embeddings.model import get_embedding_model
from app.vectorstore.faiss_store import FAISSStore
from app.llm.ollama_client import get_ollama_client
from app.scoring.confidence import compute_confidence
from app.config import TOP_K


# -- Prompt Templates --------------------------------------------------

DECOMPOSE_PROMPT = """You are a document analysis assistant. The user has asked a complex question that may require information from multiple documents.

Break the following question into 2-4 simple sub-questions. Each sub-question should target a specific piece of information needed to answer the main question.

Return ONLY the sub-questions, one per line, numbered. Do not add any other text.

QUESTION: {query}

SUB-QUESTIONS:"""


SYNTHESIS_PROMPT = """You are a document analysis assistant performing multi-document reasoning.

The user asked a complex question. You have gathered evidence from multiple retrieval passes. Now synthesize a final answer.

ORIGINAL QUESTION: {query}

EVIDENCE FROM EACH SUB-QUESTION:
{evidence}

INSTRUCTIONS:
- Combine the evidence from all sub-questions to answer the original question.
- Show your reasoning: explain how the pieces of evidence connect.
- Cite the source document(s) used (e.g., "According to rate_card.csv...").
- If evidence is contradictory, note the discrepancy.
- If there isn't enough evidence, say so clearly.
- Be specific and include relevant numbers, dates, or details.

SYNTHESIZED ANSWER:"""


def multi_doc_query(question: str, store: FAISSStore, top_k: int = TOP_K) -> dict:
    """Run a multi-document reasoning query using chain-of-thought.

    This function:
    1. Decomposes the question into sub-questions
    2. Retrieves context for each sub-question
    3. Synthesizes a final answer from all evidence
    4. Returns the answer with full reasoning chain

    Args:
        question: The user's complex question.
        store: The FAISSStore containing indexed document chunks.
        top_k: Number of chunks to retrieve per sub-question.

    Returns:
        A dict with:
            - answer: The final synthesized answer
            - reasoning_chain: List of steps showing the reasoning
            - sources: All source chunks used across all steps
            - confidence: Confidence score dict
            - query: The original question
    """
    model = get_embedding_model()
    llm = get_ollama_client()
    reasoning_chain = []
    all_chunks = []

    # -- Step 1: Decompose the question into sub-questions -----------------
    decompose_prompt = DECOMPOSE_PROMPT.format(query=question)
    raw_subs = llm.generate(decompose_prompt, temperature=0.2, max_output_tokens=256)

    sub_questions = _parse_sub_questions(raw_subs, question)

    reasoning_chain.append({
        "step": "decomposition",
        "description": "Broke the question into sub-questions",
        "sub_questions": sub_questions,
    })

    # -- Step 2: Retrieve evidence for each sub-question -------------------
    evidence_blocks = []

    for i, sub_q in enumerate(sub_questions):
        # Embed and search for each sub-question independently
        embedding = model.encode([sub_q])
        chunks = store.search(embedding, top_k=top_k)
        all_chunks.extend(chunks)

        # Build a summary of what was found for this sub-question
        if chunks:
            context_snippets = []
            for c in chunks[:3]:  # Top 3 per sub-question
                context_snippets.append(
                    f"  [From {c['source']}]: {c['text'][:300]}"
                )
            evidence_text = "\n".join(context_snippets)
        else:
            evidence_text = "  No relevant documents found."

        evidence_blocks.append({
            "sub_question": sub_q,
            "evidence": evidence_text,
            "chunks_found": len(chunks),
        })

        reasoning_chain.append({
            "step": f"retrieval_{i + 1}",
            "description": f"Retrieved evidence for: {sub_q}",
            "chunks_found": len(chunks),
            "top_sources": [c["source"] for c in chunks[:3]],
        })

    # -- Step 3: Synthesize a final answer ---------------------------------
    evidence_str = ""
    for j, eb in enumerate(evidence_blocks):
        evidence_str += f"\nSub-question {j + 1}: {eb['sub_question']}\n"
        evidence_str += f"Evidence:\n{eb['evidence']}\n"

    synthesis_prompt = SYNTHESIS_PROMPT.format(
        query=question,
        evidence=evidence_str,
    )

    answer = llm.generate(synthesis_prompt, temperature=0.3, max_output_tokens=1024)

    reasoning_chain.append({
        "step": "synthesis",
        "description": "Synthesized final answer from all evidence",
    })

    # -- Step 4: Compute confidence ----------------------------------------
    # Deduplicate chunks by text content
    seen_texts = set()
    unique_chunks = []
    for c in all_chunks:
        if c["text"] not in seen_texts:
            seen_texts.add(c["text"])
            unique_chunks.append(c)

    confidence = compute_confidence(question, unique_chunks, answer)

    # Build source info
    source_info = [
        {
            "source": c["source"],
            "chunk_index": c["chunk_index"],
            "score": c["score"],
            "text_preview": c["text"][:200] + "..."
                if len(c["text"]) > 200 else c["text"],
        }
        for c in unique_chunks[:10]  # Cap at 10 sources
    ]

    return {
        "answer": answer.strip(),
        "reasoning_chain": reasoning_chain,
        "sources": source_info,
        "confidence": confidence,
        "query": question,
    }


def _parse_sub_questions(raw: str, fallback_query: str) -> list[str]:
    """Parse numbered sub-questions from LLM output.

    Falls back to using the original query as a single sub-question
    if parsing fails.
    """
    lines = raw.strip().split("\n")
    sub_questions = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip numbering like "1.", "1)", "1:"
        cleaned = line.lstrip("0123456789.-) :")
        if cleaned and len(cleaned) > 5:
            sub_questions.append(cleaned)

    # Fallback: if we couldn't parse any, just use the original question
    if not sub_questions:
        sub_questions = [fallback_query]

    # Cap at 4 sub-questions to avoid excessive API calls
    return sub_questions[:4]
