# Stage 0: Recoverable baseline

Completed locally on October 24, 2026. No AWS resources were created, no account
upgrade was performed, and no application deployment was changed.

## Code checkpoint

- Commit: `2129858616931ee2b2a66c7441cb8c057beec74b`.
- Tag: `sentinel-stage0-baseline-20261024`.
- Code-only archive: `C:\Users\sodhi\SentinelRecovery\baseline-code-2129858.zip`.
- Archive SHA-256: `414f0d8f59de83aa0431f392496e43ff806d770b7ade6e6519e2f0960ba3ec4a`.

This captures the previous session-continuity and loading-state changes. The
archive was checked for ZIP integrity and exclusion of real environment files,
private cases, and recovery keys. It contains the repository's synthetic fixtures.
Recovery tooling added in Stage 0 is a subsequent commit; it is not in this tag.
There was no push or production redeployment.

## Current deployment inventory

| Component | Observed configuration |
|---|---|
| Frontend | React/Vite on `https://sentinel-document-intelligence.vercel.app` |
| Public API | FastAPI on `https://pahuldeepsinghsodhi--sentinel-cloud-api.us-east.modal.run` |
| API resource settings | Modal: 0.5 CPU, 2 GiB RAM, one container, 180-second timeout |
| Worker settings | Modal: 1 CPU, 4 GiB RAM, one container, 900-second timeout; at most eight jobs per invocation |
| Idle behavior | Both scale down after ten idle seconds; resource figures are configured limits, not measured use |
| Scheduled recovery | Modal `recover_jobs`, hourly; dispatches a worker when durable jobs are due |
| Database | Supabase PostgreSQL 17.11 in Mumbai (`ap-south-1`), session pooler on port 5432 |
| Application tables | Ten public tables; RLS enabled on all ten |
| Private objects | Supabase bucket `sentinel-private`; public access false; bucket limit 40 MiB per object |
| Application limits | 10 MiB per file, two cases/owner, 40 MiB/owner, 800 MiB/application |
| Accounts | Supabase email sign-in; anonymous, phone, Google, and GitHub sign-in disabled |
| Invitation enforcement | Live invitation check on protected requests; `sentinel_before_user_created` function exists |
| Saved provider keys | Supabase Vault; external provider APIs remain outside the AWS migration |
| Jobs | PostgreSQL durable queue with leases; Modal dispatch plus hourly recovery |
| Embeddings | CPU MiniLM model baked into Modal image; private indexes stored with case artifacts |
| Local mode | Separate local behavior, including Ollama; unchanged by this work |

The Modal CPU, timeout, image, and schedule entries were inspected in deployment
source, not independently compared with the running Modal control plane.
Supabase's public auth settings report signup enabled with email confirmation
required. The invitation-hook function exists, but its dashboard binding was not
independently inspected in Stage 0; do not equate function existence with an
enabled hook. The API's existing invitation enforcement remains active.

No passwords, real API keys, connection strings, tokens, or private document
contents belong in this document. Existing deployment credentials remain in
their existing private environment/secret stores and must be reconfigured for recovery.

## Encrypted application backup

Backup: `C:\Users\sodhi\SentinelRecovery\stage0-20261024`.

Key: `C:\Users\sodhi\.sentinel-recovery-keys\stage0-20261024.key.dpapi`.

| Records | Count |
|---|---:|
| Account identities / users / invitations | 2 / 2 / 2 |
| Cases | 4 |
| Source-file records / artifact records | 3 / 5 |
| Jobs / scans | 2 / 1 |
| Findings / investigations / questions | 9 / 1 / 1 |
| Provider preferences | 1 |
| Private bucket objects | 8, totaling 153,208 bytes |

The backup includes every object in the bucket, not just current source files.
The selected records were exported from a repeatable-read, read-only transaction.
After downloading objects, the tool compared another consistent snapshot of
records and object versions; any difference prevents completion.

Records, paths, file contents, and the checked-in schema are encrypted with
AES-256-GCM. Each blob is authenticated against its backup format and logical
name. SHA-256 and size checks cover every downloaded object. Windows directory
permissions were checked: only the current Windows user and SYSTEM have access.
The encryption key is protected by Windows DPAPI and stored separately.

Excluded deliberately: Vault contents, provider keys, password hashes, sessions,
refresh/access tokens, and deployment credentials. Auth accounts are exported as
identity/ownership records; this is an application recovery snapshot, not a full
Supabase platform clone. Local-mode files outside this cloud deployment are not
included. Supabase database backups also require separate object-storage backups.
[Supabase backup documentation](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)

### Verify or take another backup

From the repository root, using the recovery dependencies:

```powershell
python -m pip install -r scripts/requirements-recovery.txt
python scripts/recovery.py verify --backup C:/Users/sodhi/SentinelRecovery/stage0-20261024 --key-file C:/Users/sodhi/.sentinel-recovery-keys/stage0-20261024.key.dpapi
python scripts/recovery.py backup --destination C:/Users/sodhi/SentinelRecovery/stage0-next
```

Each backup requires a new destination. The source credentials are read from
`backend/.env.cloud`; they are never passed on the command line. Source schema
changes fail closed until the export allowlist is reviewed. A partial directory
without an authenticated manifest is not a completed backup. Preserve the
previous verified backup if a new attempt fails.

### Recovery on another computer

The current DPAPI key works only with this Windows login/profile. For recovery
after losing this computer, export a password-protected portable key in your own
terminal, then keep that key, the password, and an off-device backup safely:

```powershell
python scripts/recovery.py export-key --key-file C:/Users/sodhi/.sentinel-recovery-keys/stage0-20261024.key.dpapi --destination C:/Users/sodhi/SentinelRecovery/stage0-portable.recovery-key
```

The command prompts privately for a password of at least 16 characters. No
password needs to be sent to this chat. This export/off-device copy has **not**
been performed. The current verified backup protects local rollback, but it is
not yet a recovery copy independent of this machine.

## Restore rehearsal

Passed against a fresh, isolated PostgreSQL 17.11 cluster on loopback. Actual
table definitions, foreign keys, constraints, and indexes were used. All restored
values were compared with the backup, and every restored file was hash-checked.
The server was stopped afterwards. Live Supabase data was never a restore target.

The restored database retains user IDs and historical ownership. Provider
preferences go into `recovery_model_preferences`; active `model_settings` stays
empty because no provider key was restored. Login credentials and provider keys
must be configured again. Authentication policies, service configuration, and
secret stores require their provider-specific setup before serving traffic.
Queued/running jobs must be reviewed before enabling a recovered worker.

Portable PostgreSQL binaries were obtained from EDB, linked by PostgreSQL's
[official Windows download page](https://www.postgresql.org/download/windows/).
The local archive is `postgresql-17.11-2-windows-x64-binaries.zip`, SHA-256
`2f868d77832f5cbc62182a0ca57f02df14d33d85ce0d0bbaaeb0de3a7029bd2b`.
This is a locally computed integrity fingerprint, not a vendor-published checksum.
No Windows service or system-wide PostgreSQL installation was created.

Repeat the isolated rehearsal:

```powershell
python scripts/rehearse_recovery.py --postgres-bin C:/Users/sodhi/SentinelRecovery/tools/pgsql/bin --backup C:/Users/sodhi/SentinelRecovery/stage0-20261024 --key-file C:/Users/sodhi/.sentinel-recovery-keys/stage0-20261024.key.dpapi
```

It creates a fresh password-protected cluster under `SentinelRecovery/restore-tests`,
binds only to `127.0.0.1`, restores into a new database, compares records and files,
then stops the server. Protected rehearsal files remain locally for inspection;
the temporary server password file is removed. Never point a production frontend
or worker at this rehearsal. The lower-level restore command rejects remote
database hosts and creates a new database rather than overwriting an existing one.

To roll back application code, use the tag in a separate checkout or extract the
code archive to a new folder. Do not reset an active working tree. To recover
data into a hosted service, first restore locally, configure fresh authentication
and secrets in the destination, import ownership records and objects using the
destination adapter, verify counts/hashes, and only then switch the frontend.
Stage 0 does not implement production AWS import or cutover.

## Deployment verification and open findings

- Passed: frontend and API reachability, database health, CORS, missing/invalid
  session rejection (`401/session_invalid`), invited login, case listing, saved
  scan/question history, source excerpt, provider configuration status, storage
  quota read, and cross-owner rejection (`404`).
- Live Chrome against the real deployment: sample case selected, sections
  opened, unsent draft retained across three tab returns, exactly one `/me`
  verification, zero failed API responses, and zero browser errors.
- The sample's three source files matched repository fixtures byte for byte.
  The test used a temporary existing-admin session without sending email, then
  signed out only that session. No case writes or external LLM calls occurred.
- New-case upload/preparation/scan, decision writes, report regeneration,
  deletion, and hosted LLM calls were not repeated against production: both
  accounts already have two cases. Preserve existing data and use a dedicated
  test environment for these write operations in the next stage.
- Performance needs improvement: in this single run, API startup request
  19.1 seconds, invitation read 3.7 seconds, case list 5.6 seconds, case detail
  9.3 seconds, source excerpt 11.9 seconds, and browser workspace readiness
  27.0 seconds. These include client/network/service overhead, were measured
  sequentially, and must not be summed or presented as general benchmarks.
- Passed locally: 27 frontend tests, 13 backend cloud tests, nine recovery safety
  tests, frontend lint, production build, and Chrome synthetic-service checks
  covering tab returns, in-flight operation preservation, outage, and revocation.

Private evidence files are `verification.json`, `restore-verification.json`, and
`deployed-smoke.json` inside the protected backup directory. The reusable live
check is `python scripts/deployed_baseline.py`; it is explicitly restricted to
the existing sample and performs no new-case or provider-call tests.

## AWS account gate before Stage 1

Rechecked in AWS Settings: **Free plan, $100 credits remaining, $0 due,
April 24, 2027 expiry**. The project remains Sydney. No unearned promotional
credits are included in the budget.

The simplified project cannot select Mumbai. Advanced features require an
upgrade and activation is irreversible; leave those controls untouched under
the current no-spending constraint.
[AWS region rules](https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html),
[advanced-feature requirements](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html).

Stage 0's completion gate is met for a local recoverable baseline. Stage 1 may
prepare and qualify application changes without creating AWS resources. Before
later AWS provisioning, recheck credits, service availability, spending controls,
and establish an off-device recovery copy. The current production deployment
remains the fallback until a later, separately verified cutover.
