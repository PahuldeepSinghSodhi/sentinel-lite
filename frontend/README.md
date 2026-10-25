# Sentinel-Lite frontend

React/Vite interface for the case-based procurement review workflow: **Source files → Anomaly review → Ask documents → Download report**. The frontend supports both the default local backend and the separately configured invite-only cloud beta. See the [project README](../README.md) for the complete workflow, stack, and verification status.

## Local development

Run the FastAPI backend first, then:

```powershell
npm ci
npm run dev
```

Open `http://localhost:5173`. The frontend expects the API at `http://localhost:8000` unless `VITE_API_BASE_URL` is set. Run `npm test`, `npm run lint` and `npm run build` before submitting changes.

## Cloud configuration

The deployed beta is [invite-only](https://sentinel-document-intelligence.vercel.app). Its Vercel build uses the AWS API Gateway URL and public Cognito configuration. See [.env.aws.example](.env.aws.example), the [AWS architecture](../docs/aws-architecture.md), and [migration/recovery runbook](../docs/aws-recovery.md).

`VITE_CLOUD_PROVIDER=aws` selects the Cognito adapter. `VITE_AWS_REGION`, `VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_CLIENT_ID` must match the deployed pool/client. `VITE_API_BASE_URL` points to the matching API Gateway deployment. Google/GitHub sign-in stays disabled. The legacy [.env.cloud.example](.env.cloud.example) and [Modal/Supabase runbook](../docs/cloud-deployment.md) are retained for historical recovery, not the active site's configuration.

`VITE_` values are bundled into browser code: **never put a service-role key, database password, AWS credential, or model API key in a Vite variable**. The API owns authorization and retrieves saved provider keys server-side. Existing local cases are not uploaded automatically.

The interface preserves approved same-account sessions across tab returns, shows workspace activity and rotating loaders, provisions one reusable private sample per invited account, and exposes upload-validation errors and recovery actions. Private workspace state resets on sign-out/account changes. Server requests continue to enforce access after the entry screen is dismissed.
