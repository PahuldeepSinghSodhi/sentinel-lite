"""FastAPI application -- REST API for Sentinel-Lite.

This is the main entry point for the backend. It wraps the RAG pipeline
(Milestone 2) and anomaly detection (Milestone 4) behind REST endpoints.

Endpoints:
    GET  /                - Health check
    POST /query           - Ask a question (auto-routes to RAG or anomaly detection)
    POST /reason          - Multi-document reasoning with chain-of-thought
    POST /ingest          - Re-run document ingestion
    POST /anomalies       - Run anomaly detection on transaction data
    POST /explain_anomaly - Get AI explanation for a specific anomaly

Run with:
    uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any

from app.ingestion.pipeline import ingest_documents, load_existing_index
from app.rag.pipeline import query_rag
from app.rag.multi_doc import multi_doc_query
from app.anomaly.detector import detect_anomalies
from app.anomaly.router import classify_query
from app.anomaly.explainer import explain_anomaly
from app.config import INDEX_DIR
import pandas as pd
from pathlib import Path


# -- Request/Response Schemas ------------------------------------------

class QueryRequest(BaseModel):
    """Schema for the /query endpoint request body."""
    question: str = Field(..., description="The natural-language question to ask.")
    top_k: int = Field(default=5, description="Number of context chunks to retrieve.", ge=1, le=20)


class QueryResponse(BaseModel):
    """Schema for the /query endpoint response."""
    answer: str
    sources: list[dict[str, Any]]
    query: str


class IngestResponse(BaseModel):
    """Schema for the /ingest endpoint response."""
    status: str
    chunks_indexed: int


class HealthResponse(BaseModel):
    """Schema for the / health check response."""
    status: str
    documents_indexed: int


# -- Application Lifespan ---------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the FAISS index on startup, or run ingestion if none exists.
    
    The loaded store is saved to app.state.store so all endpoints
    can access it without reinitializing.
    """
    print("[STARTUP] Loading document index...")
    try:
        store = load_existing_index()
        print(f"[STARTUP] Loaded existing index: {store.total_vectors} vectors")
    except FileNotFoundError:
        print("[STARTUP] No existing index found. Running initial ingestion...")
        store = ingest_documents()
    
    app.state.store = store
    yield
    print("[SHUTDOWN] Sentinel-Lite API shutting down.")


# -- FastAPI App -------------------------------------------------------

app = FastAPI(
    title="Sentinel-Lite API",
    description="RAG-powered document intelligence system with anomaly detection.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow all origins during development (tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Endpoints ---------------------------------------------------------

@app.get("/", response_model=HealthResponse)
def health_check(request: Request):
    """Health check -- confirms the API is running and index is loaded."""
    store = getattr(request.app.state, "store", None)
    return {
        "status": "healthy",
        "documents_indexed": store.total_vectors if store else 0,
    }


@app.post("/query", response_model=QueryResponse)
def query_endpoint(request: Request, payload: QueryRequest):
    """Ask a question -- retrieves context from documents and generates an answer.
    
    The question is embedded, relevant chunks are retrieved from the
    FAISS index, and the local LLM generates a grounded answer.
    """
    # Validate input
    if not payload.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty. Please provide a question.",
        )
    
    # Check that the index is loaded
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(
            status_code=500,
            detail="Document index is not initialized. Run POST /ingest first.",
        )
    
    # Run the RAG pipeline
    try:
        result = query_rag(payload.question, store, top_k=payload.top_k)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Gemini API failures surface as RuntimeError
        raise HTTPException(status_code=502, detail=f"LLM service error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.post("/ingest", response_model=IngestResponse)
def ingest_endpoint(request: Request):
    """Re-run document ingestion -- rebuilds the FAISS index from scratch.
    
    Scans the sample_docs directory, processes all documents, and
    updates the in-memory index.
    """
    try:
        store = ingest_documents()
        request.app.state.store = store
        return {
            "status": "success",
            "chunks_indexed": store.total_vectors,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"No documents found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@app.post("/anomalies")
def anomalies_endpoint():
    """Run anomaly detection on the sample transactions data.
    
    Loads sample_transactions.csv, compares against the approved
    rate card, and returns all detected anomalies (duplicates,
    outliers, rate violations).
    """
    data_dir = Path(__file__).resolve().parent.parent / "data"
    transactions_file = data_dir / "sample_transactions.csv"
    rate_card_file = data_dir / "rate_card.csv"
    
    if not transactions_file.exists():
        raise HTTPException(
            status_code=404,
            detail="No transactions data found. Upload sample_transactions.csv to the data/ directory.",
        )
    
    try:
        df = pd.read_csv(transactions_file)
        reference_df = pd.read_csv(rate_card_file) if rate_card_file.exists() else None
        
        anomalies = detect_anomalies(df, reference_df)
        
        # Summary stats
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for a in anomalies:
            severity_counts[a["severity"]] = severity_counts.get(a["severity"], 0) + 1
        
        return {
            "total_anomalies": len(anomalies),
            "severity_summary": severity_counts,
            "transactions_analyzed": len(df),
            "anomalies": anomalies,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {e}")


class ExplainRequest(BaseModel):
    """Schema for the /explain_anomaly endpoint request body."""
    type: str = Field(..., description="Anomaly type (e.g., 'duplicate', 'outlier_zscore').")
    severity: str = Field(..., description="Anomaly severity ('high', 'medium', 'low').")
    description: str = Field(..., description="Human-readable description of the anomaly.")
    details: dict = Field(default_factory=dict, description="Additional anomaly details.")
    row_indices: list = Field(default_factory=list, description="List of affected row indices.")


@app.post("/explain_anomaly")
def explain_anomaly_endpoint(payload: ExplainRequest):
    """Generate an AI-powered explanation for a specific anomaly.
    
    Takes the raw anomaly data from the detector and sends it to the
    local LLM (Ollama/Llama 3.1) to produce a human-readable explanation
    with business context, risk assessment, and recommended actions.
    """
    anomaly_dict = {
        "type": payload.type,
        "severity": payload.severity,
        "description": payload.description,
        "details": payload.details,
        "row_indices": payload.row_indices,
    }
    
    try:
        result = explain_anomaly(anomaly_dict)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Explanation failed: {e}")


@app.post("/reason")
def reason_endpoint(request: Request, payload: QueryRequest):
    """Multi-document reasoning -- answers complex questions using chain-of-thought.
    
    Decomposes the question into sub-questions, retrieves evidence for
    each independently, then synthesizes a cross-referenced answer.
    Returns the full reasoning chain for transparency.
    """
    if not payload.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )
    
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(
            status_code=500,
            detail="Document index is not initialized. Run POST /ingest first.",
        )
    
    try:
        result = multi_doc_query(payload.question, store, top_k=payload.top_k)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reasoning failed: {e}")
