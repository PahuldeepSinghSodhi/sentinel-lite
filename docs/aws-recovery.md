# Recovery and final cutover

Operator tools use the approved temporary `sentinel-migration` profile and
verify the expected AWS account. Install `scripts/requirements-aws.txt` locally.
The Linux Python 3.12 runtime uses `backend/aws/requirements.lock` with hashes.

## Recovery

```powershell
python scripts/aws_operations.py --run backup
python scripts/aws_operations.py --run restore-drill
python scripts/aws_archive_backup.py
```

Backups take a repeatable-read application snapshot, copy referenced private
objects, hash them, encrypt objects/manifest with AES-GCM and publish completion
only after read-back verification. The separate private S3 bucket retains at
least seven complete daily sets. Passwords, provider keys and auth sessions are
excluded; provider preferences remain recoverable.

The drill inserts rows in foreign-key order into a unique isolated schema,
compares every value, restores objects to a unique test prefix and verifies
hashes. It rolls back the test schema and removes only its own test objects.
Master-secret read permission is temporary and removed afterward. This is not
an automatic replacement of the live database or an AWS-account restoration.

The off-account copy is encrypted under
`C:\Users\sodhi\SentinelRecovery\aws-migration\off-account`. Its local key is
Windows/DPAPI protected and depends on this user/profile. Preserve both. A
portable password-wrapped recovery key remains an owner action.

During an actual incident, stop writes/workers, preserve reachable state, restore
into fresh isolated database/storage destinations, compare values and hashes,
reprovision/rebind Cognito subjects to canonical IDs, re-enter provider keys and
test ownership before switching runtime references. RDS snapshot/PITR is an
additional AWS facility with one-day Free-plan retention.

## Remaining cutover sequence

1. Owner: sign in to the AWS preview and enter/test the provider key in Settings.
   Agent: run `python scripts/aws_qualify.py owner-ai` and verify an uncached
   investigation. Keep keys out of chat, terminal output and backup payloads.
2. Recheck Free-plan credits, alarms and `python scripts/aws_readiness.py`.
3. Deploy the old `modal_app.py` with `SENTINEL_READ_ONLY=true`. Verify its public
   `/health` reports `writes_paused`. Protected reads remain available.
   Pause AWS writes with `python scripts/aws_deploy.py --read-only --api-only`.
4. Drain queued/running jobs in both databases. Capture a fresh source backup
   into a new protected directory. Compare case IDs and preview edits with the
   baseline. Reconcile deletions/conflicts explicitly; never silently resurrect
   or overwrite a case. The prior pre-cutover snapshot is not a substitute.
5. Import that exact snapshot with `scripts/aws_import.py --backup ... --key-file
   ...`, preserving canonical IDs, intentional AWS-only records and configured
   provider secrets. Verify the command, counts/values and all object hashes.
6. Create a fresh AWS backup, run its isolated restore drill and archive the
   ciphertext off account. Record its completion marker.
7. Prepare the final frontend with `python scripts/aws_release_candidate.py`.
   It uses the existing Vercel project and `--skip-domain`, verifies that the
   main deployment is unchanged and records the previous deployment metadata.
8. Set production Vercel variables to AWS mode/public API/region/pool/client;
   retain the previous Supabase public config and Modal API reference for
   recovery. Never put provider or server keys in `VITE_` variables.
9. Promote the reviewed candidate to the existing domain. Resume AWS writes at
   the controlled point with `python scripts/aws_deploy.py --writable --api-only`.
   Check native login/refresh, ownership, history, a synthetic complete workflow
   and Chrome continuity on the main domain before declaring completion.
10. After successful stabilization, stop the old Modal application and hourly
    recovery schedule. Retain original private Supabase data and encrypted
    checkpoints during the recovery window.

The main-site write pause, final promotion and production rollback have not been
performed. The remaining manual input is the provider key; subsequent operator
work is already authorized by the migration request.

## Rollback boundary

Before business writes reach AWS, make the source writable and promote the
recorded previous Vercel deployment to restore the prior frontend/API/auth flow.
Preparing the staged candidate has not tested a production rollback.

After AWS accepts writes, a frontend-only rollback can hide new AWS records.
Freeze both sides, preserve an AWS recovery set and reconcile added/changed/
deleted records and objects into the chosen destination first. Do not perform a
blind cross-database rollback. If reconciliation is uncertain, keep AWS records
intact and repair that deployment.

The scripts cover foundation, private API integration, image build/deploy,
import, previews, release preparation, operations and live qualification.
Cognito/SES were bootstrapped through AWS APIs; email ownership and SES
production approval succeeded. This is not a claim of a complete Terraform or
CloudFormation recreation of the account.
