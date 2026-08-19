"""Centralized configuration for Sentinel-Lite.

All tunable parameters and shared paths live here so every module
imports from one place. This avoids magic numbers scattered through
the codebase and makes it easy to adjust settings later.
"""
import os
from pathlib import Path

# ── Project Paths ──────────────────────────────────────────────────
# All paths are relative to the backend/ directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent  # sentinel-lite/backend/
SAMPLE_DOCS_DIR = BACKEND_DIR / "data" / "sample_docs"
INDEX_DIR = BACKEND_DIR / "index_data"

# ── Embedding Model ────────────────────────────────────────────────
# all-MiniLM-L6-v2 produces 384-dimensional embeddings.
# It's small (~80 MB), fast, and good enough for semantic search.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# ── Chunking Parameters ───────────────────────────────────────────
# Target ~300-500 tokens per chunk with 50-token overlap.
# Using word count as a proxy for token count (roughly 1:1 for English).
CHUNK_SIZE = 400       # words per chunk
CHUNK_OVERLAP = 50     # words of overlap between consecutive chunks

# ── Retrieval ─────────────────────────────────────────────────────
TOP_K = 5              # default number of chunks to retrieve per query

# -- Ollama Local LLM --------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# Ensure index directory exists
INDEX_DIR.mkdir(parents=True, exist_ok=True)
