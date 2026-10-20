# Invite-only cloud beta: deployment runbook

This is an **opt-in implementation**, not a live URL or a production-readiness claim. Local mode remains the default. Never deploy the original unauthenticated local API to the public internet.

## Architecture

Vercel serves the static React/Vite UI. A browser session comes from Supabase Auth (Google or GitHub OAuth). Every data request goes directly over HTTPS to FastAPI on an Oracle Always Free VM. The API verifies the Supabase access token and checks the live invite list and case owner. A separate worker claims durable jobs from Supabase Postgres. Supabase private Storage holds originals, indexes, and report copies. The VM's temporary files are a processing cache, not the authoritative store. Cloud AI requests use only the selected provider and a server-retrieved Vault key. Anomaly scanning makes no AI calls.

## Prerequisites and ordering

1. Create the Vercel project from `frontend/` and attempt project name `sentinel-document-intelligence`. If Vercel will not assign that `.vercel.app` address, **stop and ask the owner** instead of choosing another name. Configure it as a Vite static build (`npm ci`, `npm run build`, output `dist`). Do not deploy cloud mode publicly yet.
2. Create a dedicated Supabase Free project. Enable the Vault extension; apply `backend/migrations/001_cloud.sql`. Insert **your own lower-case email** into `app_invites` with role `admin` in the Supabase SQL editor. Set `public.sentinel_before_user_created` as the Before User Created Auth hook. Enable Google and GitHub OAuth and set their provider credentials and Supabase callback URLs. Set Supabase's site URL and redirect allowlist to the actual Vercel origin. Disable unrelated sign-in methods and anonymous sign-ins. Do not use real procurement data for the first test.
3. Create an Always Free-eligible Ampere A1 VM (target 2 OCPU, 12 GB RAM) in the OCI home region; capacity is not guaranteed. Install Docker/Compose, clone this repository, and copy `backend/.env.cloud.example` to `backend/.env.cloud` with actual secrets. Copy the **Session pooler** Postgres URL from Supabase's Connect panel; the free direct database hostname is IPv6-only and may not be reachable from the VM. Restrict the file to the VM administrator. Pin the cloud deployment to this Git commit when testing. Do not expose the API container port publicly; the cloud Compose file exposes only Caddy's 80/443. Add OCI ingress rules for 80/443 and restrict SSH to your IP.
4. Point a free DuckDNS name to the VM public IP. Target `sentinel-lite-api.duckdns.org`, fallback `sentinel-pahul-api.duckdns.org`. Set `API_HOSTNAME` to the selected name, then start `docker compose -f docker-compose.cloud.yml up -d --build`. Caddy obtains HTTPS after DNS resolves. Set `SENTINEL_FRONTEND_ORIGIN` to the final frontend origin. Verify `https://<API_HOSTNAME>/` reports `mode: cloud` and `https://<API_HOSTNAME>/health` returns `status: ready` (the latter checks database reachability).
5. Configure Vercel environment values from `frontend/.env.cloud.example` (the Supabase publishable key may be public; the service-role and Postgres credentials must **never** be in Vercel). Deploy. Confirm OAuth redirect, invitation denial, case ownership, upload, preparation, scan, question, citation, report, and deletion with synthetic files and two accounts. Verify an uninvited account and cross-account case IDs are denied. Only then share the URL.

## API differences from local mode

Cloud case endpoints require `Authorization: Bearer <Supabase access token>`. `POST /cases/{id}/start` and `/scans` return `{job_id,status}` instead of blocking until complete; poll `GET /jobs/{id}` or reload the case's `job` field. Cloud-only endpoints are `GET /me`, `GET /me/storage`, `GET/PUT/DELETE /me/model`, admin-only `GET/PUT /admin/invites`, and `DELETE /cases/{id}`. Source and report downloads also require a bearer token. Legacy `/query`, `/reason`, `/ingest`, `/anomalies`, and `/explain_anomaly` are unavailable in cloud mode.

## Security and limits

- Source files must be UTF-8 CSV/TXT or text-extractable PDF, maximum 10 MB each. An account is capped at two cases and 40 MB retained objects; the application cap is 800 MB. A case is retained until its owner deletes it. Index and report bytes count toward these limits.
- The Postgres URL and Storage service-role key are **server-only**. The API must check ownership before using them. The private bucket has no browser-facing Storage policy, and no permanent public or signed links are generated.
- Saved provider keys live in Supabase Vault, not the browser or source repository. The browser sees only provider/model/status. A key test makes a small real provider call and can count toward the visitor's quota or bill. Model traffic sends relevant case excerpts to the chosen provider, so do not describe cloud mode as fully local or suitable for confidential company contracts without their approval.
- Caddy requires reachable DNS and ports 80/443 for automatic certificates. OCI may be out of free capacity or reclaim an idle instance. Vercel Hobby is for noncommercial personal use. Do not switch to a paid resource to bypass these constraints without approval.
- Free-tier data is not a managed enterprise backup. Export representative reports and test a database restore procedure before relying on retention for important work. Monitor Storage, database, Vercel, and OCI usage; stop new uploads at the configured caps.

## Verification commands

Local regression (from `backend/`): `python -m unittest discover -s tests -p 'test_*.py'`. Frontend: `npm ci`, `npm run lint`, `npm run build`. Cloud configuration must fail startup when required environment variables are missing. On the ARM VM, run the worker against a synthetic case and verify that FAISS and sentence-transformers load and complete. Do not describe cloud deployment as complete until the live end-to-end and cross-account tests pass.
