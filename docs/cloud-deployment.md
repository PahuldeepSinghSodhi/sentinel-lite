# Invite-only cloud beta: Modal deployment runbook

The AWS migration's recoverable starting point, backup commands, restore proof,
current configuration, and unresolved checks are recorded in
[Stage 0 recovery baseline](stage0-recovery.md). Stage 0 does not change this deployment.

The invite-only beta is deployed at
<https://sentinel-document-intelligence.vercel.app>. Its API is hosted at
<https://pahuldeepsinghsodhi--sentinel-cloud-api.us-east.modal.run>. The
frontend, API health check, database connection, service key, email-link
request, CORS, and unauthenticated-route rejection were verified on
2026-10-20. On 2026-10-21, a signed-in synthetic case passed upload,
preparation, scanning, source opening, review-decision persistence, a
code-backed anomaly question, and a PDF report containing that question.
Hosted AI, second-account isolation, and deletion still need live checks;
this is **not** a production-readiness claim. Local mode remains the default
and keeps local Ollama. Never expose the original unauthenticated local API
to the public internet.

## Live beta verification status

- Passed with synthetic repo files: required CSV upload gate, optional TXT
  upload, background preparation, 12-row scan yielding 9 findings, exact CSV
  and TXT source previews, saved Investigate decision after refresh, saved
  duplicate-count answer with both CSV rows, and a three-page PDF with the
  anomaly and document-intelligence sections. The PDF's Unicode symbols were
  also checked after a font fix.
- As expected without a visitor model key, a document-only question asks the
  reviewer to configure and test an AI provider in Settings. No hosted-model
  answer or AI investigation has been validated live yet.
- Pending: a second invited account's cross-owner denial, Google/GitHub OAuth,
  case deletion, and full hosted-model failure/success tests. Email-link
  sign-in works. The initial scan took 21,748 ms on this small synthetic case;
  this is not a general performance benchmark or a manual-time-saving claim.

## Architecture

Vercel serves the React/Vite UI. Supabase Auth signs in invited users. Browser
requests go over HTTPS to the FastAPI app hosted by a Modal web function. The
API verifies the Supabase access token and checks the live invitation and case
owner. An accepted preparation or scan request creates a durable Postgres job,
then starts an on-demand Modal processing function. An hourly scheduled recovery
check wakes a worker for jobs left behind by a transient failure. Supabase
private Storage keeps originals, indexes, and reports; Modal scratch files are
temporary. Hosted AI uses the selected provider and the server-retrieved Vault
key. Scanning itself makes zero AI calls.

## Strictly free deployment gate

1. Use **Modal Starter only**. Before creating a secret or deploying, inspect
   Usage & Billing and the *current* credit amount. The project workspace was
   manually capped at **$4 total monthly usage** on 2026-10-20;
   recheck that it remains at $4 or below, with at least $4 of applicable
   credit. The page showed a **$0 default spend limit** after the usage cap
   was lowered; verify that again before every deployment. Do not add a
   payment method for this strictly free demo. If either guardrail changes or
   the available credit falls below the usage cap, stop and do not redeploy.
   Do not use Modal Shared
   Endpoints, GPUs, paid regions, paid persistent volumes, or minimum running
   containers. The app uses none of these.
2. Check Supabase Free and Vercel Hobby usage separately. Their limits are not
   controlled by Modal's budget. Keep Sentinel invite-only with the existing
   two-case/40 MB per-user and 800 MB application limits. Stop before any
   platform asks for paid upgrades. A free-tier deployment can be suspended
   after reaching its cap; it is not guaranteed to stay available.

## Prerequisites and ordering

1. Create the Vercel project from `frontend/` with the intended project name
   `sentinel-document-intelligence`. Configure it as Vite (`npm ci`, `npm run
   build`, output `dist`). Do not publish cloud mode before the API and invited
   email sign-in work.
2. In Supabase Free, apply `backend/migrations/001_cloud.sql`, insert the
   invited admin's lower-case email in `app_invites`, configure the Before User
   Created Auth hook, Email sign-in, and the final Vercel site/redirect URLs.
   Google/GitHub OAuth are optional future providers; enable their frontend
   flags only after each provider is configured in Supabase. Disable anonymous
   sign-in. Start with
   synthetic files only. Use the **Session pooler** Postgres URL from the
   Connect panel if direct IPv6 connections are unavailable.
3. After the Modal free-cost gate above is verified, install the Modal CLI
   (`python -m pip install modal==1.6.2`) and authenticate with
   `python -m modal setup`.
   Make a private, Git-ignored `backend/.env.cloud` from
   `backend/.env.cloud.example`; fill the Supabase values and exact HTTPS
   Vercel frontend origin. Do not paste secrets into a public command or
   commit them. Create the Modal Secret using
   `python -m modal secret create sentinel-cloud --from-dotenv backend/.env.cloud`.
   Check the CLI help if its syntax differs from this runbook.
4. Deploy from the repository root with `python -m modal deploy modal_app.py`. The CLI
   prints the HTTPS URL for the `api` function. Use that exact URL as
   `VITE_API_BASE_URL` in Vercel; a DuckDNS name, VM, Caddy proxy, and open ports
   are not needed. The Starter plan does not include custom domains for Modal
   web functions. Verify `/` reports `mode: cloud` and `/health` returns
   `status: ready`; the latter checks database reachability.
   The image installs the official CPU-only PyTorch wheel before the other
   dependencies so that an unneeded CUDA stack is not pulled into this
   CPU-only deployment.
5. Deploy the Vercel build. Confirm the email-link redirect, invite rejection,
   ownership checks, upload, preparation job, scan job, question, citation,
   report, refresh, and deletion with synthetic files. Test a second account
   against another owner's case ID. Keep the beta invite-only and do not
   present it as production-ready until the remaining checks pass.

## API differences from local mode

Cloud case endpoints require `Authorization: Bearer <Supabase access token>`.
`POST /cases/{id}/start` and `/scans` return `{job_id,status}` rather than
blocking. Poll `GET /jobs/{id}` or reload the case. Cloud-only routes are
`GET /me`, `GET /me/storage`, `GET/PUT/DELETE /me/model`, admin-only
`GET/PUT /admin/invites`, and `DELETE /cases/{id}`. Source and report downloads
also require a bearer token. Legacy unauthenticated `/query`, `/reason`,
`/ingest`, `/anomalies`, and `/explain_anomaly` are unavailable in cloud mode.

## Security, resource limits, and verification

### Session continuity rollout

Deployed backend first, then the frontend, on 2026-10-22. The existing
`sentinel-document-intelligence.vercel.app` alias serves the updated cloud
bundle. Live checks passed: `/health` returned 200/ready, missing and invalid
bearer tokens returned 401/`session_invalid`, CORS allowed the frontend origin,
and a fresh browser reached the invited-email sign-in form. Signed-in continuity
was checked in installed Chrome against synthetic services before deployment;
the deployed site still needs that check with a real invited session.

The pre-deployment Modal dashboard showed Starter, $29.95 remaining credits,
a $4 usage limit, and the default $0 spend limit; Vercel reported Hobby.
These are deployment-time observations, not guarantees of future usage.
The root `.vercelignore` excludes backend credentials, case files, environment
files, logs, and generated frontend assets from the Vercel source upload.

Deploy the backend before the frontend for the session continuity update. The
cloud access gate returns `{ "detail": "...", "code": "..." }` with
`session_invalid` (401), `account_unverified` or `invite_required` (403), and
`auth_unavailable` (503). Ordinary resource permission errors remain separate.
No database migration or new environment variables are required.

The browser verifies `/me` once per page load and account identity (user ID and
normalized email). Approval stays in memory only. Same-account auth events and
token refreshes preserve the mounted workspace; sign-out or account changes
clear it. The server still checks invitations on every protected request, so a
revocation takes effect on the next request. Outages preserve an already open
workspace and surface a retryable request error. Initial verification errors
offer an explicit retry; returning to a browser tab does not restart the check.

Before release, run `npm test`, `npm run lint`, and `npm run build` in
`frontend/`, plus `python -m unittest tests.test_cloud` in `backend/`. With an
invited test account, select a case, open Ask documents, enter an unsent
question, and switch to another Chrome tab and back repeatedly. Confirm the
question and section remain and no extra `/me` requests appear in Network.
`npm run test:browser` automates this against installed Chrome and synthetic
services, including token refresh, an in-flight question, outage, and revocation.
It uses a temporary browser profile and leaves real accounts untouched. On
machines with Chrome installed elsewhere, set `CHROME_PATH` to its executable.
Also verify sign-out, account switching, and invitation revocation. Compare
401/403/503 responses after deployment; do not log bearer tokens or private data.

- Files must be UTF-8 CSV/TXT or text-extractable PDF, at most 10 MB each.
  Private Supabase Storage holds source files, indexes, and reports. The
  service-role key and Postgres URL exist only in Modal Secrets, never Vercel
  variables or browser code. The API checks case ownership before object
  access; no permanent public or signed links are generated.
- Saved provider keys live in Supabase Vault. The browser sees only
  provider/model/configuration status. A key test makes a real provider call
  and can consume that visitor's provider quota or money. Cloud model calls
  send relevant excerpts to that provider; do not use confidential company
  material without authorization.
- The API currently requests 0.5 Modal physical CPU and 2 GiB RAM; the worker
  requests 1 CPU and 4 GiB RAM. These are **configuration limits, not measured
  peak usage**. The embedding model is baked into the image to avoid a fresh
  download each time a worker scales up. Measure a synthetic case and tune
  downward if possible. Both
  functions are capped at one container; unused functions scale to zero. The
  hourly recovery check consumes some compute even when the app is idle. A
  queued job may take up to an hour to recover automatically; retrying Start
  review or Scan will attempt immediate dispatch. Modal containers scale down
  after 10 seconds of inactivity to conserve the small no-card credit.
- Run backend tests from `backend/` with `python -m unittest discover -s tests
  -p 'test_*.py'`. Run frontend `npm run lint` and `npm run build`. Cloud
  startup must fail if required settings are missing. Test the actual Modal
  deployment for FAISS/Sentence Transformers imports, peak RAM, scan time,
  cold start, job retry, and credit consumption before calling it complete.
  Monitor Supabase, Vercel, and Modal free usage. Free-tier data is not a
  managed enterprise backup.
