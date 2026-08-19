"""FAISS vector store — stores embeddings with metadata for semantic search.

FAISS (Facebook AI Similarity Search) is an efficient library for
similarity search on dense vectors. We use IndexFlatIP (inner product)
on L2-normalized vectors, which is mathematically equivalent to cosine
similarity but faster to compute.

FAISS itself only stores vectors — it has no concept of metadata.
So we maintain a parallel list of metadata dicts (source document,
chunk text, chunk index) that maps 1:1 with the FAISS index positions.
"""
import json
import faiss
import numpy as np
from pathlib import Path
from app.config import EMBEDDING_DIMENSION


class FAISSStore:
    """FAISS-backed vector store with metadata support."""
    
    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        """Initialize an empty FAISS index.
        
        Args:
            dimension: Embedding vector dimension (384 for all-MiniLM-L6-v2).
        """
        # IndexFlatIP = brute-force inner product search.
        # With L2-normalized vectors, inner product == cosine similarity.
        # For our scale (<100K chunks), brute-force is fast enough and
        # avoids the complexity of approximate search indices (IVF, HNSW).
        self.index = faiss.IndexFlatIP(dimension)
        self.dimension = dimension
        
        # Parallel metadata list: metadata[i] corresponds to vector i in the index.
        # Each entry is a dict with: {"text", "source", "chunk_index"}
        self.metadata: list[dict] = []
    
    def add(self, embeddings: np.ndarray, metadata_list: list[dict]) -> None:
        """Add vectors and their metadata to the store.
        
        Args:
            embeddings: numpy array of shape (n, dimension), must be float32.
            metadata_list: List of n dicts, one per embedding.
                Expected keys: "text", "source", "chunk_index"
                
        Raises:
            ValueError: If embeddings and metadata counts don't match.
        """
        if len(embeddings) != len(metadata_list):
            raise ValueError(
                f"Mismatch: {len(embeddings)} embeddings vs "
                f"{len(metadata_list)} metadata entries"
            )
        
        # FAISS requires float32
        embeddings = np.array(embeddings, dtype=np.float32)
        
        self.index.add(embeddings)
        self.metadata.extend(metadata_list)
    
    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[dict]:
        """Search for the most similar vectors to a query.
        
        Args:
            query_embedding: numpy array of shape (1, dimension), L2-normalized.
            top_k: Number of results to return.
            
        Returns:
            List of dicts, each with:
                - "text": the chunk's text content
                - "source": source document filename
                - "chunk_index": position of chunk in the source document
                - "score": cosine similarity score (0.0 to 1.0 for normalized vectors)
        """
        if self.index.ntotal == 0:
            return []
        
        # Clamp top_k to the number of stored vectors
        top_k = min(top_k, self.index.ntotal)
        
        query_embedding = np.array(query_embedding, dtype=np.float32)
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        
        # FAISS search returns (distances, indices) arrays
        # For IndexFlatIP, "distances" are actually inner products (= cosine sim)
        scores, indices = self.index.search(query_embedding, top_k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:  # FAISS uses -1 for empty slots
                continue
            result = {
                **self.metadata[idx],
                "score": float(score),
            }
            results.append(result)
        
        return results
    
    @property
    def total_vectors(self) -> int:
        """Number of vectors currently stored in the index."""
        return self.index.ntotal
    
    def save(self, directory: str) -> None:
        """Persist the FAISS index and metadata to disk.
        
        Creates two files:
            - faiss.index: the FAISS binary index
            - metadata.json: the parallel metadata list
            
        Args:
            directory: Directory path to save files into.
        """
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        
        # Save FAISS index (binary format)
        faiss.write_index(self.index, str(dir_path / "faiss.index"))
        
        # Save metadata as JSON (human-readable, easy to debug)
        with open(dir_path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
        
        print(f"Index saved: {self.index.ntotal} vectors -> {directory}")
    
    @classmethod
    def load(cls, directory: str) -> "FAISSStore":
        """Load a previously saved FAISS index and metadata.
        
        Args:
            directory: Directory containing faiss.index and metadata.json.
            
        Returns:
            A FAISSStore instance with the loaded index and metadata.
            
        Raises:
            FileNotFoundError: If the index files don't exist.
        """
        dir_path = Path(directory)
        index_path = dir_path / "faiss.index"
        metadata_path = dir_path / "metadata.json"
        
        if not index_path.exists():
            raise FileNotFoundError(f"No FAISS index found at {index_path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"No metadata file found at {metadata_path}")
        
        # Load the FAISS index
        index = faiss.read_index(str(index_path))
        
        # Load metadata
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # Reconstruct the store
        store = cls(dimension=index.d)  # index.d = vector dimension
        store.index = index
        store.metadata = metadata
        
        print(f"Index loaded: {store.index.ntotal} vectors from {directory}")
        return store
