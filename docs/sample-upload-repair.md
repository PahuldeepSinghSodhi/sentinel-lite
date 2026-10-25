# Sample access and upload recovery

Implemented October 25, 2026, following a separate-account reproduction.
Deployed to https://sentinel-document-intelligence.vercel.app. Implementation
checkpoint: `6dfa5ab` on `codex/aws-migration`.

## Reproduced failures

- The old sample endpoint created a new case on every click. At two cases it
  raised an uncaught quota error, returning the reported generic HTTP 500.
- An unrelated CSV failed content validation but was returned to the retry
  queue after its first attempt, with no public validation reason. The upload
  control remained busy while deterministic invalid input was retried.

## Resulting behavior

- Each invited AWS account has one private reusable sample in addition to two
  custom cases. Storage limits still include sample files and indexes.
- A durable, resumable provisioning job supplies the packaged transactions,
  vendor agreement and approved rate card. Reopening preserves decisions and
  history; it does not copy another account's cases or provider key.
- Existing cases are untouched, including historical cases named “Sample.”
- Transfers and validation display different stages. Invalid content fails on
  the first attempt with a safe reason; valid prior files survive failed replacements.
- Upload confirmation and job insertion commit together. Cancellation releases
  unconfirmed reservations, and duplicate confirmations reuse the existing job.
- Transfer is limited to 120 seconds; foreground job checking is limited to
  another 120 seconds. Remaining work has a persistent Check status action.
- Recovery copies include sample metadata and upload error/status records;
  isolated restoration also accepts the earlier backup format. Staged transfer
  bytes are temporary and are not part of the application-file backup. A real
  recovery must fail/release unfinished uploads and let their owners select
  those files again before resuming the worker.

## Verification

- 46 frontend tests, lint and the production build passed.
- 10 focused sample/upload tests, 21 existing cloud/AWS tests, 14 case/benchmark
  tests and nine recovery-tool tests passed.
- Live separate-account checks verified the sample with two existing custom
  cases, concurrent sample creation, private ownership, fixed sample sources,
  12-row/nine-finding scanning, evidence, decisions and private reports without
  an AI key. A second fresh invited account completed the sample in Chrome.
- Live invalid CSV and malformed PDF validation terminated after one attempt;
  valid CSV/TXT/PDF uploads, cancellation, retries and preserved replacements passed.
- Concurrent confirmations returned one completed upload job. Chrome preview
  and final main-domain checks covered visible errors, valid retry, persisted
  files after reload, source previews, private report downloads and no page
  errors. The validation-error layout was also visually inspected. Current and
  pre-change backups passed isolated restoration.

Protected command and browser evidence is outside Git under
`C:\Users\sodhi\SentinelRecovery\aws-migration\sample-upload-fix`.
