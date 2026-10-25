# Sentinel-Lite: portfolio and résumé notes

These claims describe the AWS migration checkout and the deployed main website,
verified October 25, 2026. The code is checkpointed on `codex/aws-migration`;
deployment does not imply that GitHub `master` or the older cloud-beta draft PR
has been updated. See [verified migration status](aws-execution-status.md).

## Project description

Sentinel-Lite is an evidence-backed procurement review application. Reviewers upload a required transactions CSV and approved rate-card CSV, optionally add a text-extractable contract, then inspect rule-based anomaly findings and cited source locations. They can record decisions, ask questions about the case, and export a PDF review history. Anomaly counts and rate calculations are code-driven; a model is called only for a requested explanation or document answer.

The local mode uses FastAPI, SQLite, local FAISS indexes, React and Ollama. The
deployed cloud version keeps React on Vercel and runs an API and warmed CPU
worker on EC2 behind API Gateway's private VPC integration. It uses private RDS
PostgreSQL, private S3, Cognito email-code authentication, Secrets Manager,
CloudWatch and EventBridge/SSM operations. The queue is PostgreSQL-based, not
SQS. Local cases do not silently move online. Requested hosted AI calls send
relevant excerpts to the selected external provider; saved keys stay server-side.

## Defensible résumé bullets

- Migrated a document-review application's API, warmed CPU worker, database, private files, authentication and provider-key storage to AWS while retaining a Vercel frontend.
- Implemented Cognito account binding, server-side invitation/ownership checks, private S3 upload tickets and signed downloads, with RDS PostgreSQL and Secrets Manager.
- Added leased background jobs and retry keys for document preparation, scans, questions, investigations and reports; preserved case and draft state across tab returns and credential refreshes.
- Configured scheduled health checks, CloudWatch/email alerts and encrypted daily recovery copies; verified isolated database/file restoration and a controlled frontend rollback.

For a shorter résumé, choose three relevant bullets. This is a portfolio beta on
one application host and a Single-AZ database. Do not turn successful controlled
tests into an uptime, security-certification or broad production-scale claim.

## Evidence and limits

| Evidence | What it supports | What it does not support |
| --- | --- | --- |
| Signed-in synthetic cloud walkthrough: 12 transaction rows, 9 findings, one saved decision and duplicate question, citations, and a three-page report | The tested upload-to-report path worked on the deployed beta | General accuracy, throughput, uptime, or employee time savings |
| AWS validation: 37 frontend tests, cloud/AWS backend tests, nine recovery tests, lint/build, real Chrome continuity and live AI/report checks | The tested migration and application paths worked | Exhaustive testing or independent security certification |
| Three 2,400-row synthetic scans: detector timers 1,520 / 1,788 / 2,402 ms, with parallel warm metadata reads around 0.4–0.5 s | Controlled CPU-worker and concurrent-read qualification | Real-data accuracy, many simultaneous workers, or an SLA |
| Final main-domain smoke: native refresh/tab continuity, live cited answer and private PDF; no Supabase/Modal browser requests | The main domain uses the AWS backend and retains UI state | Permanent availability after credits expire |
| Local 240-transaction labelled synthetic benchmark: 75% precision, 100% recall, 85.7% F1 | Performance on that constructed dataset | Real procurement accuracy or fraud detection capability |
| Preliminary clause test: 10 scenarios from 4 PDFs, 4 correct displayed clauses and 6 abstentions | A small, explicitly labelled clause-matching check | A 99% clause-accuracy claim or broad contract generalization |

Cognito email-code login, another account's ownership denial, synthetic upload/
scan/report/deletion, hosted answers and an uncached investigation were checked
live. Google/GitHub sign-in is disabled. Recovery tests compare application rows
and file hashes; they do not restore an entire AWS account or authentication
credentials. Free-plan credits and external-provider quotas are finite.

## Interview explanation

> I built Sentinel to keep transaction calculations and their source evidence together. I first made a local version, then migrated the hosted backend to AWS while keeping the frontend on Vercel. A small always-running server keeps the embedding model warm, and slow work runs through a durable queue so the API remains responsive. Cognito identifies the account, the API checks its live invitation and case ownership, and private S3/RDS store the evidence and history. I also added monitoring and tested encrypted backups through an isolated restore. I measured the small synthetic workload and documented the limits: one host, a Single-AZ database, finite credits, and external AI-provider quotas.

## Claims to avoid

- **LangChain or blockchain:** neither is implemented in this repository. The application uses sentence-transformers and FAISS directly.
- **Trained fraud detector:** anomaly checks are explicit rules and statistics, not a trained fraud classifier.
- **99% contract-clause accuracy:** the current labelled evaluation is too small to justify it.
- **Manual-review time saved:** no controlled reviewer-time comparison has been completed.
- **Fully private cloud AI:** a requested cloud AI answer sends relevant excerpts to the user-selected provider.
- **High availability or permanently free:** one host, a Single-AZ database and finite credits are explicit limits.
- **SQS, ECS/Fargate, Lambda or Terraform:** these are not the implemented architecture; the worker queue uses PostgreSQL and provisioning uses operator scripts/AWS APIs.
