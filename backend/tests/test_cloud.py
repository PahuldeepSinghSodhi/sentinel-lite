"""Cloud security smoke checks without requiring real accounts or API keys."""
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4
import requests
from psycopg import OperationalError

from app.cloud import auth, jobs, objects, providers, store, worker


class CloudUnitTests(unittest.TestCase):
    def test_authentication_failure_classification(self):
        verified = {"id": "user-1", "email": "User@Example.com", "email_confirmed_at": "2026-10-20"}
        cases = [
            (Mock(status_code=401), None, "session_invalid", 401),
            (Mock(status_code=403), None, "session_invalid", 401),
            (Mock(status_code=429), None, "auth_unavailable", 503),
            (Mock(status_code=500), None, "auth_unavailable", 503),
            (None, requests.Timeout("timeout"), "auth_unavailable", 503),
            (Mock(status_code=200, json=Mock(return_value={})), None, "account_unverified", 403),
            (Mock(status_code=200, json=Mock(side_effect=ValueError("bad JSON"))), None, "auth_unavailable", 503),
            (Mock(status_code=200, json=Mock(return_value=[])), None, "auth_unavailable", 503),
        ]
        env = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "test"}
        for response, failure, expected_code, expected_status in cases:
            with self.subTest(code=expected_code, response=response), patch.dict(os.environ, env), patch(
                "app.cloud.auth.requests.get", return_value=response, side_effect=failure
            ), patch("app.cloud.auth.db.connect") as connect:
                with self.assertRaises(auth.AccessError) as raised:
                    auth.authenticate("Bearer token")
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.status_code, expected_status)
                connect.assert_not_called()

        with patch.dict(os.environ, env), patch(
            "app.cloud.auth.requests.get", return_value=Mock(status_code=200, json=Mock(return_value=verified))
        ), patch("app.cloud.auth.db.connect", side_effect=OperationalError("private database URL")):
            with self.assertRaises(auth.AccessError) as raised:
                auth.authenticate("Bearer token")
            self.assertEqual(raised.exception.code, "auth_unavailable")
            self.assertEqual(raised.exception.status_code, 503)
            self.assertNotIn("private database", str(raised.exception))

    def test_approved_account_is_normalized_and_checked_on_every_request(self):
        response = Mock(status_code=200)
        response.json.return_value = {"id": "user-1", "email": " User@Example.com ", "email_confirmed_at": "2026-10-20"}
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = {"role": "reviewer"}

        @contextmanager
        def fake_db():
            yield conn

        with patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "test"}), patch(
            "app.cloud.auth.requests.get", return_value=response
        ), patch("app.cloud.auth.db.connect", fake_db):
            self.assertEqual(auth.authenticate("Bearer token"), {"id": "user-1", "email": "user@example.com", "role": "reviewer"})
            conn.execute.return_value.fetchone.return_value = None
            with self.assertRaises(auth.AccessError) as raised:
                auth.authenticate("Bearer token")
            self.assertEqual(raised.exception.code, "invite_required")
            self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(conn.execute.call_count, 2)

    def test_missing_bearer_rejected_without_network(self):
        with patch("app.cloud.auth.requests.get") as request:
            with self.assertRaises(PermissionError):
                auth.authenticate("")
            request.assert_not_called()

    def test_revoked_invitation_rejected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"id": "user-1", "email": "User@Example.com",
                                      "email_confirmed_at": "2026-10-20T00:00:00Z"}

        @contextmanager
        def fake_db():
            conn = Mock()
            conn.execute.return_value.fetchone.return_value = None
            yield conn

        with patch("app.cloud.auth.requests.get", return_value=response), patch(
            "app.cloud.auth.db.connect", fake_db
        ), patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "test"}):
            with self.assertRaisesRegex(PermissionError, "not invited"):
                auth.authenticate("Bearer signed-token")

    def test_provider_is_fixed_and_redacts_errors(self):
        with self.assertRaises(ValueError):
            providers.HostedClient("http://evil.example", "model", "secret")
        self.assertNotIn("llama-3.3-70b-versatile", providers.MODELS["groq"])
        self.assertEqual(providers.MODELS["ollama_cloud"][0], "gpt-oss:20b")
        response = Mock(ok=False, status_code=401)
        with patch("app.cloud.providers.requests.post", return_value=response) as post:
            client = providers.HostedClient("groq", "openai/gpt-oss-20b", "private-test-key")
            with self.assertRaisesRegex(RuntimeError, "rejected the saved key") as error:
                client.generate("test")
            self.assertNotIn("private-test-key", str(error.exception))
            self.assertEqual(post.call_args.args[0], providers.ENDPOINTS["groq"])

    def test_storage_download_uses_authenticated_endpoint(self):
        response = Mock(status_code=200, content=b"private document")
        with patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co",
                                      "SUPABASE_SERVICE_ROLE_KEY": "server-only"}), patch(
            "app.cloud.objects.requests.get", return_value=response
        ) as request:
            self.assertEqual(objects.get("owner/case/file.pdf"), b"private document")
            self.assertIn("/object/authenticated/", request.call_args.args[0])

    def test_case_lookup_includes_signed_in_owner(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = None
        @contextmanager
        def fake_db():
            yield conn

        with auth.user_context({"id": "user-1", "email": "user@example.com", "role": "reviewer"}), patch(
            "app.cloud.store.db.connect", fake_db
        ):
            with self.assertRaises(KeyError):
                store.get_case("11111111-1111-4111-8111-111111111111")
        self.assertEqual(conn.execute.call_args.args[1],
                         ("11111111-1111-4111-8111-111111111111", "user-1"))

    def test_cloud_file_path_accepts_database_uuid(self):
        case_id = uuid4()

        @contextmanager
        def fake_db():
            conn = Mock()
            conn.execute.return_value.fetchone.return_value = {
                "path": "private/test/transactions.csv", "extension": ".csv"
            }
            yield conn

        with tempfile.TemporaryDirectory() as scratch, patch(
            "app.cloud.store.db.connect", fake_db
        ), patch("app.cloud.store._owner"), patch(
            "app.cloud.store.objects.get", return_value=b"vendor_name\nApex\n"
        ), patch("app.cloud.store.root", return_value=Path(scratch)):
            target = store.file_path(case_id, "transactions")
            self.assertEqual(target.read_bytes(), b"vendor_name\nApex\n")
            self.assertEqual(target.parent.name, str(case_id))

    def test_cloud_case_result_normalizes_database_ids(self):
        case_id, scan_id, finding_id = uuid4(), uuid4(), uuid4()
        conn = Mock()
        conn.execute.side_effect = [
            [],
            [{"id": scan_id, "case_id": case_id, "created_at": "now",
              "transactions_analyzed": 1, "duration_ms": 1}],
            [{"id": finding_id, "data_json": {"type": "duplicate"},
              "decision": None, "note": None, "decided_at": None}],
            Mock(fetchone=Mock(return_value=None)),
            [],
            Mock(fetchone=Mock(return_value=None)),
        ]
        result = store._case_result(conn, {"id": case_id, "name": "Synthetic",
                                           "status": "active", "created_at": "now",
                                           "started_at": "now"})
        self.assertEqual(result["id"], str(case_id))
        self.assertEqual(result["scans"][0]["id"], str(scan_id))
        self.assertEqual(result["scans"][0]["findings"][0]["id"], str(finding_id))

    def test_worker_claim_reaps_exhausted_lease_and_uses_skip_locked(self):
        @contextmanager
        def fake_db():
            conn = Mock()
            conn.execute.side_effect = [
                [{"case_id": "case-1", "kind": "start"}],
                None,
                Mock(fetchone=Mock(return_value=None)),
            ]
            yield conn
            self.assertIn("status = 'failed'", conn.execute.call_args_list[0].args[0])
            self.assertIn("status = 'draft'", conn.execute.call_args_list[1].args[0])
            self.assertIn("LIMIT 1 FOR UPDATE SKIP LOCKED", conn.execute.call_args_list[2].args[0])
        with patch("app.cloud.jobs.db.connect", fake_db):
            self.assertIsNone(jobs.claim())

    def test_worker_normalizes_database_uuid_for_case_paths(self):
        case_id, owner_id, job_id = uuid4(), uuid4(), uuid4()
        job = {"id": job_id, "case_id": case_id, "owner_id": owner_id,
               "kind": "start", "attempts": 1}

        @contextmanager
        def fake_db():
            conn = Mock()
            conn.execute.side_effect = [
                Mock(fetchone=Mock(return_value={"email": "reviewer@example.com"})),
                Mock(fetchone=Mock(return_value={"invited": True})),
            ]
            yield conn

        with tempfile.TemporaryDirectory() as scratch, patch(
            "app.cloud.worker.jobs.claim", return_value=job
        ), patch("app.cloud.worker.db.connect", fake_db), patch(
            "app.cloud.worker.sources.build_index"
        ) as build, patch("app.cloud.worker.store.sync_artifacts") as sync, patch(
            "app.cloud.worker.store.mark_started"
        ) as started, patch("app.cloud.worker.jobs.finish") as finish, patch(
            "app.cloud.worker.jobs.fail"
        ) as fail, patch("app.cloud.worker.store.root", return_value=Path(scratch)):
            self.assertTrue(worker.run_once())
        build.assert_called_once_with(str(case_id))
        sync.assert_called_once_with(str(case_id))
        started.assert_called_once_with(str(case_id))
        finish.assert_called_once_with(job_id, None)
        fail.assert_not_called()

    def test_cloud_mode_blocks_legacy_and_requires_session(self):
        code = """from fastapi.testclient import TestClient
from app.main import app
from contextlib import contextmanager
from unittest.mock import Mock, patch
@contextmanager
def healthy_db():
    yield Mock()
with TestClient(app) as client:
    assert client.get('/').json()['mode'] == 'cloud'
    with patch('app.cloud.db.connect', healthy_db):
        assert client.get('/health').json() == {'status': 'ready', 'mode': 'cloud'}
    assert client.post('/query', json={'question':'x'}).status_code == 404
    missing = client.get('/cases')
    assert missing.status_code == 401
    assert missing.json()['code'] == 'session_invalid'
    from app.cloud.auth import AccessError
    for code, status in [('session_invalid', 401), ('account_unverified', 403), ('invite_required', 403), ('auth_unavailable', 503)]:
        with patch('app.cloud.auth.authenticate', side_effect=AccessError(code, 'Public detail', status)):
            failure = client.get('/me', headers={'Origin':'https://sentinel-document-intelligence.vercel.app'})
        assert failure.status_code == status
        assert failure.json() == {'code': code, 'detail': 'Public detail'}
        assert failure.headers.get('access-control-allow-origin') == 'https://sentinel-document-intelligence.vercel.app'
    denied = client.get('/cases', headers={'Origin':'https://sentinel-document-intelligence.vercel.app'})
    assert denied.headers.get('access-control-allow-origin') == 'https://sentinel-document-intelligence.vercel.app'
    import os
    with patch.dict(os.environ, {'SENTINEL_READ_ONLY':'true'}), patch('app.cloud.auth.authenticate', return_value={'id':'u','email':'u@example.test','role':'admin'}):
        assert client.get('/me').status_code == 200
        assert client.post('/cases',json={'name':'paused'}).json()['code'] == 'migration_read_only'
        assert client.get('/cases/any/report').status_code == 503
        with patch('app.cases.router.store.list_cases',return_value=[]):
            assert client.get('/cases').json() == []
"""
        env = {**os.environ, "SENTINEL_MODE": "cloud", "SUPABASE_URL": "https://example.supabase.co",
               "SUPABASE_ANON_KEY": "test", "SUPABASE_SERVICE_ROLE_KEY": "test",
               "SUPABASE_DB_URL": "postgresql://test:test@localhost/test"}
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cloud_startup_fails_closed_without_credentials(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {"SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL"}}
        env["SENTINEL_MODE"] = "cloud"
        code = """from fastapi.testclient import TestClient
from app.main import app
with TestClient(app):
    pass
"""
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing cloud configuration", result.stderr)


if __name__ == "__main__":
    unittest.main()
