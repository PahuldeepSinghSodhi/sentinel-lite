"""Ingestion pipeline — orchestrates document loading, chunking, and indexing.

This is the top-level module that ties together the file loader, chunker,
embedding model, and FAISS store into a single ingest_documents() call.
It's used at startup to build the index and can be re-run to add new documents.
"""
from pathlib import Path
from app.config import SAMPLE_DOCS_DIR, INDEX_DIR, CHUNK_SIZE, CHUNK_OVERLAP
from app.ingestion.file_loader import load_document, SUPPORTED_EXTENSIONS
from app.ingestion.chunker import chunk_text
from app.embeddings.model import get_embedding_model
from app.vectorstore.faiss_store import FAISSStore


def ingest_documents(
    doc_dir: str | None = None,
    index_dir: str | None = None,
) -> FAISSStore:
    """Run the full ingestion pipeline: load → chunk → embed → index.
    
    Scans a directory for supported documents, processes each one,
    and builds a FAISS index that's saved to disk for later use.
    
    Args:
        doc_dir: Directory containing documents to ingest.
                 Defaults to SAMPLE_DOCS_DIR from config.
        index_dir: Directory to save the FAISS index to.
                   Defaults to INDEX_DIR from config.
                   
    Returns:
        The populated FAISSStore, ready for querying.
    """
    doc_dir = Path(doc_dir or SAMPLE_DOCS_DIR)
    index_dir = str(index_dir or INDEX_DIR)
    
    # ── Step 1: Discover documents ────────────────────────────────
    doc_files = [
        f for f in sorted(doc_dir.iterdir())
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    
    if not doc_files:
        raise FileNotFoundError(
            f"No supported documents found in {doc_dir}. "
            f"Supported types: {SUPPORTED_EXTENSIONS}"
        )
    
    print(f"\n{'='*60}")
    print(f"INGESTION PIPELINE: Processing {len(doc_files)} documents")
    print(f"{'='*60}")
    
    # ── Step 2: Load and chunk each document ──────────────────────
    all_chunks = []      # flat list of chunk texts for batch embedding
    all_metadata = []    # parallel list of metadata dicts
    
    for doc_file in doc_files:
        print(f"\n[*] Loading: {doc_file.name}")
        
        # Load raw text
        doc = load_document(str(doc_file))
        print(f"   File type: {doc['file_type']}, Text length: {len(doc['text'])} chars")
        
        # Chunk the text
        chunks = chunk_text(
            text=doc["text"],
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        print(f"   Chunks created: {len(chunks)}")
        
        # Collect chunks and metadata
        for chunk in chunks:
            all_chunks.append(chunk["text"])
            all_metadata.append({
                "text": chunk["text"],
                "source": doc["source"],
                "chunk_index": chunk["chunk_index"],
            })
    
    print(f"\n[i] Total chunks across all documents: {len(all_chunks)}")
    
    # ── Step 3: Embed all chunks ──────────────────────────────────
    print("\n[>] Generating embeddings...")
    model = get_embedding_model()
    embeddings = model.embed(all_chunks)
    print(f"   Embeddings shape: {embeddings.shape}")
    
    # ── Step 4: Build FAISS index ─────────────────────────────────
    print("\n[>] Building FAISS index...")
    store = FAISSStore(dimension=embeddings.shape[1])
    store.add(embeddings, all_metadata)
    print(f"   Index contains {store.total_vectors} vectors")
    
    # ── Step 5: Save to disk ──────────────────────────────────────
    store.save(index_dir)
    
    print(f"\n{'='*60}")
    print(f"INGESTION COMPLETE: {store.total_vectors} chunks indexed")
    print(f"{'='*60}\n")
    
    return store


def load_existing_index(index_dir: str | None = None) -> FAISSStore:
    """Load a previously built FAISS index from disk.
    
    Use this at API startup to avoid re-running the full ingestion
    pipeline every time the server restarts.
    
    Args:
        index_dir: Directory containing the saved index.
                   Defaults to INDEX_DIR from config.
                   
    Returns:
        The loaded FAISSStore, ready for querying.
    """
    index_dir = str(index_dir or INDEX_DIR)
    return FAISSStore.load(index_dir)
