"""Cloud security smoke checks without requiring real accounts or API keys."""
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from app.cloud import auth, jobs, objects, providers, store


class CloudUnitTests(unittest.TestCase):
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
    assert client.get('/cases').status_code == 401
    denied = client.get('/cases', headers={'Origin':'https://sentinel-document-intelligence.vercel.app'})
    assert denied.headers.get('access-control-allow-origin') == 'https://sentinel-document-intelligence.vercel.app'
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
