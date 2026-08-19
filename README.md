# Sentinel-Lite: Anomaly Detection & RAG Pipeline

Sentinel-Lite is a lightweight, privacy-focused log anomaly detection system and AI assistant powered by a local Large Language Model.

## Architecture

```text
+----------------+      +----------------+      +-----------------+
|   Frontend     | ---> |   FastAPI      | ---> | Local Ollama    |
| (React/Vite)   | <--- |   Backend      | <--- | (llama3.1)      |
+----------------+      +----------------+      +-----------------+
                              |   ^
                              v   |
                        +----------------+
                        | FAISS / Pandas |
                        | Vector / Data  |
                        +----------------+
```

## Tech Stack
*   **Backend:** FastAPI, Python 3.12, Uvicorn, Pandas, SciPy
*   **AI/ML:** Sentence Transformers, FAISS (Vector Database)
*   **LLM:** Ollama (Local Execution)
*   **Frontend:** React, Vite 
*   **Deployment:** Docker, Docker Compose

## Prerequisites
*   Python 3.12+
*   Node.js 18+
*   Ollama installed locally
*   Docker & Docker Compose (Optional for deployment)

## Quick Start

### 1. Setup Ollama
Download and install [Ollama](https://ollama.com/), then pull the LLaMA 3.1 model:
```bash
ollama run llama3.1
```

### 2. Setup Backend
Open a terminal and navigate to the project root:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 3. Setup Frontend
Open a new terminal:
```bash
cd frontend
npm install
npm run dev
```

### 4. Access the Application
Open your browser and navigate to `http://localhost:5173` for the frontend UI, or `http://localhost:8000/docs` for the API documentation.

## API Reference

### Health Check
```bash
curl -X GET http://localhost:8000/health
```

### Detect Anomalies
```bash
curl -X POST http://localhost:8000/api/anomalies/detect \
     -H "Content-Type: application/json" \
     -d '{"data": [...]}'
```

### Query RAG Pipeline
```bash
curl -X POST http://localhost:8000/api/rag/query \
     -H "Content-Type: application/json" \
     -d '{"query": "How do I fix a database connection error?"}'
```

## Project Structure
```text
sentinel-lite/
├── backend/
│   ├── app/                # FastAPI application
│   │   ├── anomaly/        # Anomaly detection logic
│   │   ├── embeddings/     # Text embedding models
│   │   ├── ingestion/      # Document loading and chunking
│   │   ├── llm/            # Ollama client wrappers
│   │   ├── rag/            # Retrieval-Augmented Generation
│   │   ├── scoring/        # Confidence scoring logic
│   │   └── vectorstore/    # FAISS vector store
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
└── README.md
```

## How It Works

### Anomaly Detection
The system uses statistical methods (like Z-score from SciPy) and machine learning to analyze structured log data or metrics via Pandas, identifying outliers and unexpected patterns without sending sensitive data to the cloud.

### RAG Pipeline
The Retrieval-Augmented Generation (RAG) pipeline chunks documents, computes embeddings using `sentence-transformers`, and stores them in a local FAISS index. When queried, it retrieves the most relevant chunks and passes them as context to the local Ollama LLM to generate an accurate, hallucination-free response.
