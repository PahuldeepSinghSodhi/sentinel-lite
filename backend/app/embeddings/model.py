"""Singleton embedding model — loads once, reused everywhere.

This module wraps sentence-transformers so the heavy model loading
(~80 MB for all-MiniLM-L6-v2) happens exactly once. Every part of
the system that needs embeddings — ingestion, retrieval, evaluation —
imports get_embedding_model() and gets the same instance.

Why a singleton? Loading the model takes 2-3 seconds and ~200 MB RAM.
Reloading it per-request would make the API unusably slow.
"""
import numpy as np
from sentence_transformers import SentenceTransformer
from app.config import EMBEDDING_MODEL_NAME


class EmbeddingModel:
    """Wrapper around SentenceTransformer with convenient batch/query methods."""
    
    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        """Load the sentence-transformer model.
        
        Args:
            model_name: HuggingFace model identifier.
        """
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_embedding_dimension()
        print(f"Model loaded. Embedding dimension: {self.dimension}")
    
    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode a batch of texts into normalized embedding vectors.
        
        Args:
            texts: List of strings to embed.
            
        Returns:
            numpy array of shape (len(texts), dimension), L2-normalized.
            Normalization means we can use inner product as cosine similarity,
            which is what FAISS IndexFlatIP does.
        """
        # normalize_embeddings=True ensures unit vectors, so
        # dot product == cosine similarity (saves a step later)
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 50,  # only show bar for large batches
            batch_size=64,
        )
        return np.array(embeddings, dtype=np.float32)
    
    def embed_query(self, query: str) -> np.ndarray:
        """Encode a single query string.
        
        Convenience wrapper around embed() for single-query use cases
        (e.g., search-time encoding).
        
        Args:
            query: The search query to encode.
            
        Returns:
            numpy array of shape (1, dimension), L2-normalized.
        """
        return self.embed([query])


# ── Singleton instance ────────────────────────────────────────────
# The model is loaded lazily on first access, then cached.
_model_instance: EmbeddingModel | None = None


def get_embedding_model() -> EmbeddingModel:
    """Get the shared embedding model instance (lazy singleton).
    
    First call loads the model (~2-3 sec). All subsequent calls
    return the same instance instantly.
    """
    global _model_instance
    if _model_instance is None:
        _model_instance = EmbeddingModel()
    return _model_instance
