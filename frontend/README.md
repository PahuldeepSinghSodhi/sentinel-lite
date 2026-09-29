# Sentinel-Lite frontend

This React/Vite interface is part of the local case-based procurement review tool. See the [repository README](../README.md) for backend setup, supported upload formats, API routes, and evaluation.

Run `npm ci` and `npm run dev`, then open `http://localhost:5173`. The frontend expects the FastAPI backend at `http://localhost:8000`; set `VITE_API_BASE_URL` to change this. Use `npm run build` and `npm run lint` for checks.
