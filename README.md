# Sentinel-Lite

Sentinel-Lite is a local procurement review assistant. It flags duplicate transactions, unusual values, and hourly rates above an approved rate card. Reviewers can inspect the exact source location, record a decision, ask questions about uploaded files, and export a PDF case report. AI answers and explanations use a local Ollama model; anomaly detection is rule/statistics based.

## What a review looks like

1. Click **New case**, or **Try sample** for the bundled demo.
2. Upload **Transactions CSV** and **Approved rate card CSV**. Both are required. A text-based **Vendor contract PDF or TXT** is optional.
3. Click **Start review**. Files are then locked so previous findings cannot silently change; create another case for new uploads.
4. Run a scan, open its transaction/rate-card evidence, and select **Investigate**, **Approved exception**, or **False alarm**. Approved exceptions require a note.
5. In **Ask documents**, ask about the latest scan (for example, duplicate counts by vendor) or the uploaded files. Scan answers use saved findings and link to the original CSV rows; document questions use retrieved passages. Use the persistent **Download report** button for a PDF with separate anomaly and document-intelligence sections.

After a review starts, its source files are locked to preserve evidence. In **Source files**, choose **Add your own files** to create a new case with fresh upload controls; the earlier case remains in the case selector. Scan questions use the latest scan at the time they are asked, so past saved answers remain tied to their original scan when you scan again.

New scan-backed answers are displayed as a short summary, exact counts, vendor groups, and expandable finding details. Their plain-text answer and source citations remain saved for the PDF report. Older saved answers remain available in a collapsed detail view; ask again to get the new presentation.

Each case has separate files, a FAISS index, SQLite records, scan history, decisions, and question history under `backend/data/cases/` (ignored by Git). A citation identifies a PDF page, TXT line range, or CSV row and columns. These are locations of retrieved context, not a guarantee that every claim in an AI answer is correct. Scanned image PDFs need OCR and are rejected in this version.

## Run locally

Requires Python 3.12+, Node.js 22+, and [Ollama](https://ollama.com/) with `llama3.1` available locally.

```powershell
ollama pull llama3.1
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The API docs are at `http://localhost:8000/docs`. On macOS/Linux, activate the Python environment with `source venv/bin/activate`. If Ollama is not already running, start it with `ollama serve`. Set `VITE_API_BASE_URL` when the API is not on port 8000.

For Docker, start Ollama on the host and run `docker compose up --build` at the repository root; run the frontend separately as above. Compose mounts `backend/data` and `backend/index_data`, binds the API to `127.0.0.1:8000`, and reaches Ollama through `host.docker.internal`. Depending on the host setup, Ollama may need to listen on an address reachable from Docker. Do not expose this unauthenticated local demo API to a network.

## Upload contract and case API

Transaction CSV needs `vendor_name`, `role_level`, and numeric `hourly_rate`. Rate-card CSV needs `vendor_name`, `role_level`, and positive numeric `approved_rate`; each vendor/role pair must be unique. Extra columns such as `hours`, `total_amount`, `transaction_id`, and `invoice_ref` are supported. Files must be UTF-8 CSV/TXT or text-based PDF, at most 10 MB each.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | Existing sample index status |
| `GET` | `/cases` | Local case summaries |
| `POST` | `/cases` | Create case; JSON `{ "name": "May review" }` |
| `POST` | `/cases/demo` | Create sample case from bundled files |
| `GET` | `/cases/{id}` | Files, scans, decisions, and questions |
| `POST` | `/cases/{id}/files/{kind}` | Multipart field `file`; kind is `transactions`, `rate_card`, or `contract` |
| `POST` | `/cases/{id}/start` | Requires both mandatory uploads; builds case index |
| `POST` | `/cases/{id}/scans` | Persists a distinct scan and findings |
| `PATCH` | `/cases/{id}/findings/{finding_id}` | JSON `decision` and `note` |
| `POST` | `/cases/{id}/questions` | JSON `question` and optional `top_k` |
| `GET` | `/cases/{id}/source/{kind}` | Query `row`, `page`, or `line_start`/`line_end` |
| `GET` | `/cases/{id}/report` | PDF with all scans and questions for one case |

Legacy sample endpoints remain available for compatibility: `POST /query`, `/reason`, `/ingest`, `/anomalies`, and `/explain_anomaly`. The app UI uses the case-scoped endpoints.

## Evaluation and limitations

Run `python -m unittest tests.test_cases tests.test_benchmark -v` from `backend/` for the case workflow and the 240-transaction synthetic benchmark. Run `python -m app.evaluation.synthetic` to regenerate the `backend/data/benchmark_*` files and print its metrics. Upload `benchmark_transactions.csv`, `benchmark_rate_card.csv`, and optionally `benchmark_contract.txt` as a larger demo. The labelled sample contains injected rate violations, a duplicate pair, a large outlier, and an approved exception that requires reviewer judgment.

On the initial generated benchmark, the detector found 9 labelled type/row pairs with 3 false positives: **75% precision, 100% recall, 85.7% F1**. All three false-positive type/row flags arise from the single approved exception at transaction row index 230, demonstrating why reviewer decisions matter. These are controlled synthetic results and do not establish real-world accuracy or time savings. Scan duration printed by the script covers anomaly detection and scoring only; it excludes uploads, embedding, LLM generation, and human review. The original 20-question RAG harness remains in `backend/tests/test_evaluation.py`; CI runs retrieval-only checks because Ollama is not present on the runner. Full LLM evaluation must run locally.

The current version is a single-user local prototype: no login, OCR, multi-user permissions, or deployment-grade data governance. The LLM can still be wrong; reviewers should verify citations and decisions.

## Stack

FastAPI, Pandas/SciPy, sentence-transformers (`all-MiniLM-L6-v2`), FAISS, Ollama (`llama3.1`), SQLite, ReportLab, React, and Vite. The retrieval pipeline is implemented directly and does **not** use LangChain.
