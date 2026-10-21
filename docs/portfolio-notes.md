# Sentinel-Lite: portfolio and résumé notes

These claims describe the `codex/cloud-invite-beta` branch as verified on 2026-10-21. The cloud work is in an [open draft pull request](https://github.com/PahuldeepSinghSodhi/sentinel-lite/pull/1), not yet merged into `master`. Update this page after further live testing; do not turn a pending check into a completed claim.

## Project description

Sentinel-Lite is an evidence-backed procurement review application. Reviewers upload a required transactions CSV and approved rate-card CSV, optionally add a text-extractable contract, then inspect rule-based anomaly findings and cited source locations. They can record decisions, ask questions about the case, and export a PDF review history. Anomaly counts and rate calculations are code-driven; a model is called only for a requested explanation or document answer.

The original local mode uses FastAPI, SQLite, local per-case FAISS indexes, React, and local Ollama. The invite-only cloud beta separates a Vercel frontend, Modal FastAPI API and background worker, and Supabase Auth/Postgres/private Storage/Vault. It retains local Ollama rather than silently moving local cases or documents online. Cloud model settings support user-supplied keys for an allowlisted provider/model; the browser does not receive saved keys. Relevant excerpts do leave the application for the selected provider when an AI request is made.

## Defensible résumé bullets

- Built and deployed an invite-only procurement-review beta across Vercel, Modal, and Supabase, with authenticated, owner-scoped cases and private storage for source files, indexes, and reports.
- Implemented durable background jobs for document preparation and deterministic anomaly scans, including persisted status, retries, recovery, and zero scan-time LLM calls.
- Developed source-linked review of duplicate transactions, unusual values, and rate-card discrepancies, with saved reviewer decisions, document questions, and PDF case reports.
- Added server-side bring-your-own-key model configuration through Supabase Vault while retaining a separate local-Ollama mode. **Live hosted-model answer and investigation checks are still pending.**

For a shorter résumé, choose the three bullets most relevant to the role. Keep the pending-live-check qualifier when discussing the model integration in an interview; do not imply every cloud feature has passed end-to-end testing.

## Evidence and limits

| Evidence | What it supports | What it does not support |
| --- | --- | --- |
| Signed-in synthetic cloud walkthrough: 12 transaction rows, 9 findings, one saved decision and duplicate question, citations, and a three-page report | The tested upload-to-report path worked on the deployed beta | General accuracy, throughput, uptime, or employee time savings |
| Last recorded verification: 42 backend tests, frontend lint and build | Automated and build checks passed on the branch | Second-account isolation or hosted-provider success in production |
| Local 240-transaction labelled synthetic benchmark: 75% precision, 100% recall, 85.7% F1 | Performance on that constructed dataset | Real procurement accuracy or fraud detection capability |
| Preliminary clause test: 10 scenarios from 4 PDFs, 4 correct displayed clauses and 6 abstentions | A small, explicitly labelled clause-matching check | A 99% clause-accuracy claim or broad contract generalization |

Email-link sign-in and the synthetic cloud case were checked live. Hosted-provider answers and investigations, a second user's denied access to another case, Google/GitHub OAuth, and case deletion remain pending live checks. The cloud beta is not a production security certification. Free-tier hosting and third-party AI usage are not guaranteed to be free or continuously available.

## Interview explanation

> I built Sentinel because reviewing transactions against approved prices and contracts can require switching among several files. The anomaly engine performs explicit calculations and keeps the exact evidence visible; the reviewer makes the final decision. I then moved the single-user prototype into an invite-only cloud beta by separating the browser, authenticated API, durable database and private object storage, and background worker. I kept the local Ollama workflow for private local use, while the hosted version lets an invited reviewer configure a supported AI provider. I verified the deployed synthetic upload-to-report flow and documented the remaining security and AI integration tests rather than claiming production readiness.

## Claims to avoid

- **LangChain or blockchain:** neither is implemented in this repository. The application uses sentence-transformers and FAISS directly.
- **Trained fraud detector:** anomaly checks are explicit rules and statistics, not a trained fraud classifier.
- **99% contract-clause accuracy:** the current labelled evaluation is too small to justify it.
- **Manual-review time saved:** no controlled reviewer-time comparison has been completed.
- **Fully private cloud AI:** a requested cloud AI answer sends relevant excerpts to the user-selected provider.
- **Production-ready or permanently free:** important live checks and independent hosting/provider quotas remain.
