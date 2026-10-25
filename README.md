# Sentinel-Lite

**Evidence-backed procurement review, from uploaded files to a documented decision.** Sentinel checks transactions against an approved rate card, identifies possible duplicates and unusual charges, and lets a reviewer inspect sources, record decisions, ask document questions, and export a case report. The anomaly scan is deterministic; an AI model is called only for a requested explanation or document answer.

[Try the invite-only cloud beta](https://sentinel-document-intelligence.vercel.app) · [AWS architecture](docs/aws-architecture.md) · [Migration and recovery](docs/aws-execution-status.md) · [Portfolio and résumé wording](docs/portfolio-notes.md)

The local version remains the default and uses SQLite, local files, and Ollama. The deployed cloud beta keeps its Vercel frontend and uses AWS for the API, warmed worker, PostgreSQL, private files, login, provider-key storage, monitoring and scheduled recovery copies. The main domain was switched on October 25, 2026 after live hosted-AI, isolation, workflow, recovery and Chrome continuity checks. **This is a portfolio beta with one application host and a Single-AZ database, not a high-availability procurement or security service.**

## Why this exists

Procurement reviewers often have to reconcile transaction rows, approved prices, and contract language across separate files. Sentinel brings those sources into one case and makes each flag reviewable: the triggering rule, calculation, CSV row and columns, rate-card entry, and any suggested contract context are visible before the reviewer decides what to do. A suggested clause is explicitly not a confirmed contractual breach, and the rate card remains authoritative for numerical discrepancies.

## Architecture at a glance

| Responsibility | Local mode | Invite-only cloud beta |
| --- | --- | --- |
| Interface | React/Vite on the user's computer | React/Vite on Vercel |
| API and processing | Local FastAPI process | API Gateway private integration to EC2 FastAPI and a warmed CPU worker |
| Identity and case history | Single-user SQLite | Cognito email codes and private RDS PostgreSQL; live invitation and ownership checks |
| Documents and indexes | Local files and per-case FAISS indexes | Private encrypted S3; temporary worker scratch space |
| AI on request | Local Ollama | External supported provider; key kept server-side in Secrets Manager |
| Operations | Local process logs | CloudWatch, confirmed email alerts, EventBridge/SSM checks and encrypted recovery copies |

In AWS mode, uploads are authorized for direct S3 transfer and validated in the worker. Preparation, scans, questions, investigations and reports use durable Postgres jobs. The UI can show queued, running, completed or failed status after a refresh. Scanning makes **zero model calls**. Returning to a tab or refreshing credentials preserves the approved workspace; a new page load verifies access again. See the [AWS architecture](docs/aws-architecture.md) and [recovery runbook](docs/aws-recovery.md). Cloud mode does not upload existing local cases automatically. The [old Modal/Supabase runbook](docs/cloud-deployment.md) is retained for recovery reference.

## What a review looks like

1. Click **New case**, or **Try sample** for the bundled demo.
2. Upload **Transactions CSV** and **Approved rate card CSV**. Both are required. A text-based **Vendor contract PDF or TXT** is optional.
3. Click **Start review**. Files are then locked so previous findings cannot silently change; create another case for new uploads.
4. Run a scan. Each finding shows the triggering rows, calculation, rate-card evidence, and at most one **suggested contract context** passage when a clause looks applicable. Scanning uses no Ollama call. Choose **Investigate with AI** for a short cited brief, then record **Investigate**, **Approved exception**, or **False alarm** as the reviewer decision. Approved exceptions require a note.
5. In **Ask documents**, ask about the latest scan (for example, duplicate counts by vendor) or the uploaded files. Scan answers use saved findings and link to the original CSV rows; document questions use retrieved passages. Use the persistent **Download report** button for a PDF with separate anomaly and document-intelligence sections.

After a review starts, its source files are locked to preserve evidence. In **Source files**, choose **Add your own files** to create a new case with fresh upload controls; the earlier case remains in the case selector. Scan questions use the latest scan at the time they are asked, so past saved answers remain tied to their original scan when you scan again.

New scan-backed answers are displayed as a short summary, exact counts, vendor groups, and expandable finding details. Their plain-text answer and source citations remain saved for the PDF report. Older saved answers remain available in a collapsed detail view; ask again to get the new presentation.

In local mode, each case has separate files, a FAISS index, SQLite records, scan history, decisions, and question history under `backend/data/cases/` (ignored by Git). Cloud mode keeps the same case boundaries in Postgres and private Storage. A citation identifies a PDF page, TXT line range, or CSV row and columns. These are locations of retrieved context, not a guarantee that every claim in an AI answer is correct. Scanned image PDFs need OCR and are rejected in this version.

Investigation evidence appears immediately without a model call. Generating its **What happened / Why it matters / Next action** brief uses at most one model call, saves the result, and reuses it on repeat clicks or refresh. Local mode uses Ollama and SQLite; cloud mode uses the configured provider and Postgres. Only supplied citation IDs are displayed; a cited source still needs reviewer verification. PDF links open the uploaded original at the cited page when the browser supports page navigation, with extracted page text as a fallback. TXT links show numbered lines, and CSV links emphasize cited columns. PDF text highlighting is not implemented. The downloaded report includes the saved brief and its source locations. **Ask documents is unchanged** by this investigation feature.

Clause matching uses a contract-only FAISS index plus rule-topic checks and available explicit vendor/role or ISO-format effective-date restrictions; the rate card remains the numerical authority. Unlabelled names, unusual date wording, or ambiguous clauses may still be misread, so a suggestion is never presented as a confirmed contractual breach. If nothing passes the checks, the finding says **No clause suggested**.

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

Transaction CSV needs `vendor_name`, `role_level`, and numeric `hourly_rate`. Rate-card CSV needs `vendor_name`, `role_level`, and positive numeric `approved_rate`; each vendor/role pair must be unique. Extra columns such as `hours`, `total_amount`, `transaction_id`, and `invoice_ref` are supported. Files must be UTF-8 CSV/TXT or text-based PDF, at most 10 MB each. The routes below describe local mode; cloud case routes require a verified bearer token, and Start review and Scan return a job ID. See the [cloud API differences](docs/cloud-deployment.md#api-differences-from-local-mode).

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
| `POST` | `/cases/{id}/findings/{finding_id}/investigate` | Generate once or return the saved, cited investigation brief |
| `POST` | `/cases/{id}/questions` | JSON `question` and optional `top_k` |
| `GET` | `/cases/{id}/source/{kind}` | Query `row`, `page`, or `line_start`/`line_end` |
| `GET` | `/cases/{id}/files/contract/original` | Open the locally stored original PDF, case-scoped |
| `GET` | `/cases/{id}/report` | PDF with all scans and questions for one case |

Legacy sample endpoints remain available **in local mode** for compatibility: `POST /query`, `/reason`, `/ingest`, `/anomalies`, and `/explain_anomaly`. They are unavailable in cloud mode. The app UI uses the case-scoped endpoints.

## Evaluation and limitations

Run `python -m unittest tests.test_cases tests.test_benchmark -v` from `backend/` for the case workflow and the 240-transaction synthetic benchmark. Run `python -m app.evaluation.synthetic` to regenerate the `backend/data/benchmark_*` files and print its metrics. Upload `benchmark_transactions.csv`, `benchmark_rate_card.csv`, and optionally `benchmark_contract.txt` as a larger demo. The labelled sample contains injected rate violations, a duplicate pair, a large outlier, and an approved exception that requires reviewer judgment.

On the initial generated benchmark, the detector found 9 labelled type/row pairs with 3 false positives: **75% precision, 100% recall, 85.7% F1**. All three false-positive type/row flags arise from the single approved exception at transaction row index 230, demonstrating why reviewer decisions matter. These are controlled synthetic results and do not establish real-world accuracy or time savings. Scan duration printed by the script covers anomaly detection and scoring only; it excludes uploads, embedding, LLM generation, and human review. The original 20-question RAG harness remains in `backend/tests/test_evaluation.py`; CI runs retrieval-only checks because Ollama is not present on the runner. Full LLM evaluation must run locally.

The default local mode is a single-user prototype without login or OCR. The opt-in cloud mode adds account ownership and private storage, but is not a production security certification. The LLM can still be wrong; reviewers should verify citations and decisions.

### Cloud beta verification (2026-10-21)

One signed-in synthetic case passed required CSV upload validation, optional TXT upload, background preparation, scanning, CSV/TXT source opening, a saved review decision after refresh, a code-backed duplicate question, and PDF export. The scan processed **12 rows and produced 9 findings in 21,748 ms**; this is a single hosted walkthrough, not a latency benchmark. The duplicate answer identified **one group, two rows, and one extra copy** with source-row links. The exported PDF included both anomaly-review and document-intelligence sections.

The last recorded verification passed **42 backend tests**, frontend lint, and frontend build. Email-link sign-in works. A document-only question correctly asks for provider setup when no key is configured; successful hosted-provider answers and AI investigations are **not yet verified live**. Second-account ownership denial, Google/GitHub OAuth, and deletion also need live checks. No controlled manual-review study has established time savings. See the [runbook's verification status](docs/cloud-deployment.md#live-beta-verification-status).

### Contract-clause evaluation

`python -m app.evaluation.clause_matching --download` (from `backend/`) downloads the [public PDFs listed with their provenance and reuse notes](backend/data/clause_evaluation_sources.json) into an ignored local cache, then evaluates the [hand-labelled scenarios](backend/data/clause_evaluation_labels.json). The transaction/rate-card rows are explicitly **synthetic search probes**, not real invoices or evidence that those public contracts govern a particular vendor. Entire PDF sources, not paraphrases of the same clause, determine development versus held-out splits. Two development PDFs are procurement guidance used as negative controls, not executed contracts. Check each source's reuse terms before redistributing the PDF.

The current preliminary run has **10 labelled scenarios across 4 PDFs**: 4 applicable clauses displayed, all 4 matching the hand-labelled page/passage; 6 abstentions; 0 wrong passages among the displayed ones. Displayed precision and applicable recall are therefore 4/4, but each has a descriptive 95% Wilson interval of **51.0%–100%**. The held-out split has only **one independent contract and two applicable scenarios**, both matched; this is much too small to validate 99%. Scenarios within a document are correlated, so even those intervals should not be read as a general company-contract guarantee. The command prints breakdowns by split, finding type, and PDF. Development errors should guide extraction, passage boundaries, ranking, and applicability checks; final accuracy must be retested on untouched contracts.

`python -m app.evaluation.investigation_benchmark` measures indexing, 240-row scans with/without clause matching, peak process RAM, cold and cached investigation latency, and Ollama token/timing counters when available. In one local run, median scan time rose from **30.7 ms to 56.0 ms**; indexing took **10.05 s**; one cold investigation took **15.93 s** with 410 input and 79 output tokens, including **9.18 s model load**. Reusing the saved brief took **4.5 ms** with no model call. These are one-machine sample timings, not service-level promises. Scanning makes zero Ollama calls; a successful new investigation makes one; a cached investigation makes zero. Process RSS is not a complete measure of GPU memory, and the tool does not measure electricity directly. See [reviewer study protocol](docs/reviewer_study.md) before making any human-time-savings claim.

Deferred candidates, **not implemented**: exact-plus-semantic identifier retrieval and a small local ML reranker trained from labelled mistakes. No LangChain dependency is used.

## Stack and project status

Core: Python, FastAPI, Pandas/SciPy, sentence-transformers (`all-MiniLM-L6-v2`), FAISS, ReportLab, React, and Vite. Local mode: SQLite and Ollama (`llama3.1`). Cloud beta: Supabase Auth/Postgres/private Storage/Vault, Modal API and worker, and Vercel hosting. The retrieval pipeline is implemented directly and does **not** use LangChain; the project does not implement blockchain. The current cloud work is in an [open draft pull request](https://github.com/PahuldeepSinghSodhi/sentinel-lite/pull/1), not yet merged into `master`.
