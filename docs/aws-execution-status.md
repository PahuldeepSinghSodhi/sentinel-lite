# AWS migration execution status

Verified October 25, 2026. AWS deployment: https://sentinel-aws-preview.vercel.app.
The main production domain still uses the original deployment. An AWS-backed
release candidate has been uploaded to the existing Vercel project with domain
promotion disabled, and the existing production deployment was verified unchanged.

## Completed and verified

| Stage | Evidence |
|---|---|
| Baseline | Git checkpoints, encrypted source snapshots, isolated PostgreSQL restore, file hashes |
| Application | Cognito sessions, canonical account mapping, RDS/S3/Secrets Manager adapters, durable background operations |
| Foundation/runtime | Dedicated VPC, restricted ingress, private RDS, API Gateway private integration, ECR, EC2 API and warmed worker |
| Historical transfer | Fresh source: 2 original users, 2 invites, 4 cases, 8 objects / 153,208 bytes; imported values and hashes compared |
| AWS preview | Real email-code login, ownership denial, direct uploads, indexing/scans, saved deterministic answers, decisions, signed PDFs and reports |
| Capacity | Three 2,400-row scans while another account read metadata; no container OOM/restart observed |
| Browser | Real AWS + installed Chrome: three tab returns and native refresh preserved case/draft; one `/me` initially and another after reload |
| Operations | Encrypted daily backups, isolated restore comparison, protected off-account copy, schedules, 11 alarms, confirmed alert email, spending/credit alerts |
| Checks | 37 frontend tests, lint/build; cloud/AWS tests, case/benchmark tests; nine recovery tests; controlled Chrome outage/revocation/in-flight-operation smoke |

Both source snapshots restored into isolated local PostgreSQL. An AWS recovery
set containing 23 objects and synthetic qualification history also passed an
isolated database/file restore. These are application recovery tests, not a
complete AWS account or authentication-credential restoration.

## Remaining completion gate

The owner must sign in to the AWS preview and re-enter/test the external AI
provider key in Settings. As last checked, the AWS owner has no configured key.
Plaintext Vault keys were deliberately excluded from export. Hosted AI question
and uncached investigation checks, final write pause/transfer, production
promotion and old-worker shutdown remain pending. Gmail placed test codes in
Spam; check there for the sign-in email.

After that input, the agent can complete the authorized operator work using the
[cutover instructions](aws-recovery.md). Do not describe the main production
migration or hosted AI validation as complete yet.

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
- Local mode stays separate. The source website remains writable until the
  controlled final pause; a fresh final snapshot is required then.
- Runtime bootstrap-secret access and ECR push permissions are temporary grants,
  removed when their operator commands finish.

Resource references and private evidence live outside Git under
`C:\Users\sodhi\SentinelRecovery\aws-migration`. No plaintext provider/database
passwords belong in these documents. See [architecture](aws-architecture.md).
