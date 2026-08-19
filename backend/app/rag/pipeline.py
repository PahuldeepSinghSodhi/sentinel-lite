"""RAG (Retrieval-Augmented Generation) pipeline.

This is the core Q&A engine of Sentinel-Lite. Given a user's natural-language
question, it:
1. Embeds the query using the shared embedding model (Milestone 1)
2. Retrieves the top-k most relevant chunks from the FAISS index (Milestone 1)
3. Constructs a grounded prompt with the retrieved context
4. Sends it to Gemini for answer generation
5. Returns the answer along with the source chunks used

The key idea behind RAG: instead of relying on the LLM's training data
(which may be outdated or hallucinated), we ground every answer in
actual retrieved documents. The LLM acts as a "reader" that synthesizes
information from the retrieved passages, not as a knowledge source itself.
"""
from app.embeddings.model import get_embedding_model
from app.vectorstore.faiss_store import FAISSStore
from app.llm.ollama_client import get_ollama_client
from app.scoring.confidence import compute_confidence
from app.config import TOP_K


# -- Prompt template ---------------------------------------------------
# This template instructs the LLM to:
# 1. Only use the provided context to answer
# 2. Cite which source documents it used
# 3. Explicitly say "I don't have enough information" if the context
#    doesn't contain the answer (instead of hallucinating)

RAG_PROMPT_TEMPLATE = """You are a helpful document analysis assistant. Answer the user's question using ONLY the context provided below. Do not use any outside knowledge.

INSTRUCTIONS:
- Base your answer strictly on the provided context passages.
- If the context does not contain enough information to answer the question, say "I don't have enough information in the provided documents to answer this question."
- Cite the source document(s) you used in your answer (e.g., "According to invoice_001.txt...").
- Be specific and include relevant numbers, dates, or details from the context.
- Keep your answer concise but complete.

CONTEXT:
{context}

USER QUESTION: {query}

ANSWER:"""


def build_context_string(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string for the LLM prompt.
    
    Each chunk is labeled with its source and similarity score so the
    LLM can weigh more relevant passages higher.
    
    Args:
        chunks: List of chunk dicts from FAISSStore.search(), each with
                "text", "source", "chunk_index", "score".
                
    Returns:
        Formatted context string with source attribution.
    """
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"--- Passage {i} (Source: {chunk['source']}, "
            f"Relevance: {chunk['score']:.2f}) ---\n"
            f"{chunk['text']}"
        )
    return "\n\n".join(context_parts)


def query_rag(
    question: str,
    store: FAISSStore,
    top_k: int = TOP_K,
) -> dict:
    """Run the full RAG pipeline: retrieve context, then generate an answer.
    
    This is the main entry point for Q&A. It coordinates the embedding
    model, FAISS store, and Gemini client to produce a grounded answer.
    
    Args:
        question: The user's natural-language question.
        store: The FAISS vector store containing indexed document chunks.
        top_k: Number of chunks to retrieve for context.
        
    Returns:
        dict with:
            - "answer": the generated answer string
            - "sources": list of source chunk dicts used as context
            - "query": the original question (for reference)
            
    Raises:
        ValueError: If the question is empty.
        RuntimeError: If the Gemini API call fails.
    """
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")
    
    # -- Step 1: Embed the query ----------------------------------------
    model = get_embedding_model()
    query_embedding = model.embed_query(question)
    
    # -- Step 2: Retrieve relevant chunks from FAISS --------------------
    chunks = store.search(query_embedding, top_k=top_k)
    
    if not chunks:
        return {
            "answer": "No documents have been indexed yet. Please upload documents first.",
            "sources": [],
            "query": question,
        }
    
    # -- Step 3: Build the grounded prompt ------------------------------
    context_str = build_context_string(chunks)
    prompt = RAG_PROMPT_TEMPLATE.format(context=context_str, query=question)
    
    # -- Step 4: Generate answer via Ollama -----------------------------
    llm = get_ollama_client()
    answer = llm.generate(prompt, temperature=0.3)
    
    # -- Step 5: Compute confidence score --------------------------------
    confidence = compute_confidence(question, chunks, answer)
    
    # -- Step 6: Return answer with source attribution ------------------
    # Strip chunk text from sources to keep response size manageable
    # but preserve source metadata for the frontend
    source_info = [
        {
            "source": chunk["source"],
            "chunk_index": chunk["chunk_index"],
            "score": chunk["score"],
            "text_preview": chunk["text"][:200] + "..."
                if len(chunk["text"]) > 200 else chunk["text"],
        }
        for chunk in chunks
    ]
    
    return {
        "answer": answer,
        "sources": source_info,
        "confidence": confidence,
        "query": question,
    }
