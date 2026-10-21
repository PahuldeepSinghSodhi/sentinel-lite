# Sentinel-Lite frontend

React/Vite interface for the case-based procurement review workflow: **Source files → Anomaly review → Ask documents → Download report**. The frontend supports both the default local backend and the separately configured invite-only cloud beta. See the [project README](../README.md) for the complete workflow, stack, and verification status.

## Local development

Run the FastAPI backend first, then:

```powershell
npm ci
npm run dev
```

Open `http://localhost:5173`. The frontend expects the API at `http://localhost:8000` unless `VITE_API_BASE_URL` is set. Run `npm run lint` and `npm run build` before submitting changes.

## Cloud configuration

The deployed beta is [invite-only](https://sentinel-document-intelligence.vercel.app). Its Vercel build uses the Modal HTTPS API URL and public Supabase client configuration. See the [deployment runbook](../docs/cloud-deployment.md) for the exact settings and checks. `VITE_` values are bundled into browser code: **never put a service-role key, database password, or model API key in a Vite variable**. The API owns authorization and retrieves saved provider keys server-side. Existing local cases are not uploaded automatically.
