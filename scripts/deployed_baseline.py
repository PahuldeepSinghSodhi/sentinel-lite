"""Read-only deployed workflow check using the existing, byte-matched sample case.

Creates and then signs out ONLY its own temporary admin session. Does not email,
create/delete cases, change decisions, generate reports, or call an LLM provider.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

from dotenv import dotenv_values
import requests

from recovery import ROOT, load_backup

API = "https://pahuldeepsinghsodhi--sentinel-cloud-api.us-east.modal.run"
FRONTEND = "https://sentinel-document-intelligence.vercel.app"


def main():
    result = {"checks": {}, "new_case_workflow": "not_run_existing_accounts_at_case_quota",
              "llm_calls": 0, "case_writes": 0}
    env = dotenv_values(ROOT / "backend/.env.cloud")
    source = env["SUPABASE_URL"].rstrip("/")
    backup = Path.home() / "SentinelRecovery/stage0-20261024"
    key = Path.home() / ".sentinel-recovery-keys/stage0-20261024.key.dpapi"
    _, _, manifest = load_backup(backup, key)
    session = None
    try:
        for label, path in (("frontend", FRONTEND), ("api", API + "/"), ("health", API + "/health")):
            start = time.monotonic()
            response = requests.get(path, timeout=120)
            result["checks"][label] = {"status": response.status_code, "ms": round(1000 * (time.monotonic() - start))}
            response.raise_for_status()
        for label, headers in (("missing_session", {}), ("invalid_session", {"Authorization": "Bearer synthetic-invalid-session"})):
            response = requests.get(API + "/me", headers=headers, timeout=30)
            assert response.status_code == 401 and response.json()["code"] == "session_invalid"
            result["checks"][label] = True
        response = requests.options(API + "/me", headers={"Origin": FRONTEND, "Access-Control-Request-Method": "GET"}, timeout=30)
        assert response.headers.get("access-control-allow-origin") == FRONTEND
        result["checks"]["cors"] = True
        active = next(c for c in manifest["tables"]["public.cases"] if c["status"] == "active")
        user = next(u for u in manifest["tables"]["auth.users"] if u["id"] == active["owner_id"])
        assert any(i["email"].lower() == user["email"].lower() and i["role"] == "admin" and i["enabled"]
                   for i in manifest["tables"]["public.app_invites"])
        hashes = {o["name"]: o["sha256"] for o in manifest["objects"]}
        from recovery import digest
        fixture_hashes = {digest((ROOT / "backend/data" / name).read_bytes()) for name in (
            "sample_transactions.csv", "rate_card.csv", "sample_docs/service_agreement.txt")}
        files = [f for f in manifest["tables"]["public.case_files"] if f["case_id"] == active["id"]]
        assert len(files) == 3 and all(hashes[f["path"]] in fixture_hashes for f in files)
        result["checks"]["sample_files_match_repository"] = True
        admin_headers = {"apikey": env["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + env["SUPABASE_SERVICE_ROLE_KEY"]}
        generated = requests.post(source + "/auth/v1/admin/generate_link", headers=admin_headers,
                                  json={"type": "magiclink", "email": user["email"]}, timeout=30)
        generated.raise_for_status()
        verified = requests.post(source + "/auth/v1/verify", headers={"apikey": env["SUPABASE_ANON_KEY"]},
                                 json={"type": "email", "token_hash": generated.json()["hashed_token"]}, timeout=30)
        verified.raise_for_status()
        session = verified.json()
        assert session["user"]["id"] == user["id"]
        headers = {"Authorization": "Bearer " + session["access_token"]}
        for label, path in (("invitation", "/me"), ("case_list", "/cases"), ("saved_case", "/cases/" + active["id"]),
                            ("source_excerpt", "/cases/" + active["id"] + "/source/transactions?row=2"),
                            ("provider_configuration", "/me/model"), ("quota", "/me/storage")):
            start = time.monotonic()
            response = requests.get(API + path, headers=headers, timeout=60)
            result["checks"][label] = {"status": response.status_code, "ms": round(1000 * (time.monotonic() - start))}
            response.raise_for_status()
            if label == "saved_case":
                review = response.json()
                assert review["scans"] and review["questions"] and review["can_report"]
                result["checks"]["saved_history"] = True
        other = next(c for c in manifest["tables"]["public.cases"] if c["owner_id"] != user["id"])
        response = requests.get(API + "/cases/" + other["id"], headers=headers, timeout=30)
        assert response.status_code in (403, 404)
        result["checks"]["cross_owner_denied"] = response.status_code
        session["expires_at"] = int(time.time()) + session.get("expires_in", 3600)
        payload = {"session": session, "project": source.split("//")[1].split(".")[0],
                   "caseId": active["id"], "origin": FRONTEND, "api": API}
        browser = subprocess.run(["node", str(ROOT / "frontend/scripts/live-baseline-smoke.mjs")],
                                 input=json.dumps(payload), capture_output=True, text=True, timeout=180)
        # Only parse our deliberately redacted JSON report; never emit browser stderr.
        result["browser"] = json.loads(browser.stdout.strip().splitlines()[-1])
        assert browser.returncode == 0 and result["browser"]["passed"]
        result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["failure_type"] = type(exc).__name__
    finally:
        if session:
            try:
                response = requests.post(source + "/auth/v1/logout?scope=local", headers={
                    "apikey": env["SUPABASE_ANON_KEY"], "Authorization": "Bearer " + session["access_token"]}, timeout=30)
                result["temporary_session_signed_out"] = response.status_code in (200, 204)
            except requests.RequestException:
                result["temporary_session_signed_out"] = False
            if not result["temporary_session_signed_out"]:
                result["passed"] = False
        (backup / "deployed-smoke.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
