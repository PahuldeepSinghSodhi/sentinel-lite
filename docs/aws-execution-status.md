# AWS migration execution status

Completed October 25, 2026. Main deployment:
https://sentinel-document-intelligence.vercel.app. The frontend remains on Vercel;
the active application services run on AWS. The separate AWS preview remains at
https://sentinel-aws-preview.vercel.app. The old Modal API and hourly recovery
schedule are stopped. Original private Supabase data remains a recovery source.

The source publication also includes the subsequent [reusable-sample and upload
recovery repair](sample-upload-repair.md), workspace loading feedback and rotating
loading indicators. Their changes preserve the deployed invitation and ownership
boundaries. Local mode remains separate from cloud cases.

## Completed and verified

| Stage | Evidence |
|---|---|
| Baseline | Git checkpoints, encrypted source snapshots, isolated PostgreSQL restore, file hashes |
| Application | Cognito sessions, canonical account mapping, RDS/S3/Secrets Manager adapters, durable background operations |
| Foundation/runtime | Dedicated VPC, restricted ingress, private RDS, API Gateway private integration, ECR, EC2 API and warmed worker |
| Historical transfer | Fresh source: 2 original users, 2 invites, 4 cases, 8 objects / 153,208 bytes; imported values and hashes compared |
| Application checks | Real email-code login, ownership denial, direct uploads, indexing/scans, saved answers, decisions, signed PDFs and reports; hosted document answer and uncached investigation passed |
| Capacity | Three 2,400-row scans while another account read metadata; no container OOM/restart observed |
| Browser | Real AWS + installed Chrome: three tab returns and native refresh preserved case/draft; one `/me` initially and another after reload |
| Operations | Encrypted daily backups, isolated restore comparison, protected off-account copy, schedules, 12 alarms, confirmed alert email, spending/credit alerts |
| Checks | 37 frontend tests, lint/build; cloud/AWS tests, case/benchmark tests; nine recovery tests; controlled Chrome outage/revocation/in-flight-operation smoke |
| Final cutover | Both deployments paused and queues drained; fresh source matched the verified import; final AWS backup/restoration/off-account archive passed; Vercel production variables updated and reviewed release promoted |
| Production smoke | Main-domain Chrome case/draft/refresh continuity passed with no legacy backend requests; live AI answer returned three sources; private 51,269-byte PDF downloaded with verified main-origin CORS |

Three automatic five-minute monitor executions were also verified successful
through their scheduled Systems Manager commands. The first nightly backup run
is still pending its scheduled time; the same backup document passed manual
execution and restoration checks.

The operator's temporary Cognito test refresh token was revoked and its local
encrypted session/challenge files removed after the final audit. The user's
independent browser session was preserved. A later authenticated operator audit
requires a fresh test login through `scripts/aws_login_probe.py`; the saved audit
remains the dated record of the completed checks.

Both source snapshots restored into isolated local PostgreSQL. An AWS recovery
set containing 23 objects and synthetic qualification history also passed an
isolated database/file restore. These are application recovery tests, not a
complete AWS account or authentication-credential restoration.

## Reconciliation and release

The owner re-entered and tested the provider key through Settings. Plaintext
Vault keys were never exported. The final source capture matched the prior
verified transfer, so no duplicate reimport was needed; this preserved the new
AWS answers, investigation and any preview edits. Both queues were empty at
the handoff. AWS writes were resumed after the main-domain read/continuity check.

Frontend rollback and re-promotion were exercised on the isolated preview.
Production alias promotion was then verified against the reviewed static asset.
A cross-database rollback after new AWS writes has not been exercised; preserve
and reconcile those writes before ever returning to the old data store.

## Boundaries

- AWS remains on its active Free plan in Sydney; no paid upgrade or advanced
  feature activation. The latest check reported $140 in credits. Resources
  consume credits while running.
- EC2: t3.small, 2 vCPU / 2 GiB, Standard credits, encrypted 20 GiB gp3.
  RDS: private Single-AZ PostgreSQL, db.t4g.micro, encrypted 20 GiB gp2.
- RDS Free-plan retention is one day. Separate logical backups retain at least
  seven complete daily sets, with S3 expiration after eight days. The identical
  scheduled backup document was manually tested; the first nightly execution
  has not yet been observed.
- Vercel and external LLM providers remain. Jobs use PostgreSQL leases; this
  deployment does not use SQS, Lambda, ECS, Fargate, ALB or NAT Gateway.
- Local mode stays separate. The source was paused before its final snapshot;
  its API and scheduled worker are now stopped. The old data was not deleted.
- Runtime bootstrap-secret access and ECR push permissions are temporary grants,
  removed when their operator commands finish.

Resource references and private evidence live outside Git under
`C:\Users\sodhi\SentinelRecovery\aws-migration`. No plaintext provider/database
passwords belong in these documents. See [architecture](aws-architecture.md).
