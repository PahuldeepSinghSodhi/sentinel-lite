# Invite-only cloud beta: Modal deployment runbook

This is an **opt-in implementation**, not a live URL or a production-readiness
claim. Local mode remains the default and keeps local Ollama. Never expose the
original unauthenticated local API to the public internet.

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
   Usage & Billing. A workspace **without a payment method may receive only $1
   of the advertised $30 monthly credit**, with a Modal-set $1 usage limit.
   That no-card configuration is suitable only if the displayed usage limit is
   no higher than the available credit. Do not add a payment method for this
   strictly free demo. If the account has a payment method, set a Workspace
   usage budget no higher than the available credit **and** a $0 out-of-pocket
   spend limit; stop if either guardrail is unavailable. Never assume the
   published $30 credit is active for a particular workspace. Do not use Modal Shared
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
5. Deploy the Vercel build. Confirm the email-link redirect, invite rejection,
   ownership checks, upload, preparation job, scan job, question, citation,
   report, refresh, and deletion with synthetic files. Test a second account
   against another owner's case ID. Do not share the URL until these pass.

## API differences from local mode

Cloud case endpoints require `Authorization: Bearer <Supabase access token>`.
`POST /cases/{id}/start` and `/scans` return `{job_id,status}` rather than
blocking. Poll `GET /jobs/{id}` or reload the case. Cloud-only routes are
`GET /me`, `GET /me/storage`, `GET/PUT/DELETE /me/model`, admin-only
`GET/PUT /admin/invites`, and `DELETE /cases/{id}`. Source and report downloads
also require a bearer token. Legacy unauthenticated `/query`, `/reason`,
`/ingest`, `/anomalies`, and `/explain_anomaly` are unavailable in cloud mode.

## Security, resource limits, and verification

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
  peak usage**. Measure a synthetic case and tune downward if possible. Both
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
