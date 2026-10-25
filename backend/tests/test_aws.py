"""AWS adapter isolation, credential validation and private-storage checks without AWS calls."""
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from psycopg import OperationalError
from botocore.exceptions import ClientError

from app.cloud import auth, aws_auth, aws_objects, aws_clients


class AWSAdapterTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, **updates):
        now = datetime.now(timezone.utc)
        claims = {"sub": "cognito-sub", "email": "user@example.test", "email_verified": True,
                  "iss": "https://cognito-idp.ap-southeast-2.amazonaws.com/pool", "aud": "client",
                  "iat": now, "exp": now + timedelta(minutes=15), "token_use": "id", **updates}
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": "test"})

    def authenticate(self, token, row=None, error=None):
        key = Mock()
        key.get_signing_key_from_jwt.return_value.key = self.private.public_key()
        database = Mock()
        database.__enter__ = Mock(return_value=database)
        database.__exit__ = Mock(return_value=False)
        database.execute.return_value.fetchone.return_value = row
        with patch.dict(os.environ, {"AWS_REGION": "ap-southeast-2", "COGNITO_USER_POOL_ID": "pool", "COGNITO_CLIENT_ID": "client"}), patch.object(aws_auth, "key_client", return_value=key), patch.object(aws_auth.db, "connect", side_effect=error, return_value=database):
            return aws_auth.authenticate(token)

    def test_validated_identity_uses_bound_application_id_and_database_role(self):
        result = self.authenticate(self.token(), {"id": "app-user", "email": "user@example.test", "disabled": False, "role": "reviewer"})
        self.assertEqual(result, {"id": "app-user", "email": "user@example.test", "role": "reviewer"})

    def test_wrong_client_issuer_expiry_and_token_type_fail(self):
        for updates in ({"aud": "other"}, {"iss": "https://other.example.test"},
                        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, {"token_use": "access"}):
            with self.subTest(updates=updates), self.assertRaises(auth.AccessError) as error:
                self.authenticate(self.token(**updates))
            self.assertEqual(error.exception.code, "session_invalid")

    def test_unverified_email_and_unbound_identity_fail_closed(self):
        with self.assertRaises(auth.AccessError) as error:
            self.authenticate(self.token(email_verified=False))
        self.assertEqual(error.exception.code, "account_unverified")
        for row in (None, {"id": "u", "email": "other@example.test", "disabled": False, "role": "admin"},
                    {"id": "u", "email": "user@example.test", "disabled": True, "role": "admin"},
                    {"id": "u", "email": "user@example.test", "disabled": False, "role": None}):
            with self.assertRaises(auth.AccessError) as error:
                self.authenticate(self.token(), row)
            self.assertEqual(error.exception.code, "invite_required")

    def test_database_outage_is_retryable(self):
        with self.assertRaises(auth.AccessError) as error:
            self.authenticate(self.token(), error=OperationalError("private connection information"))
        self.assertEqual(error.exception.code, "auth_unavailable")
        self.assertNotIn("private", str(error.exception))

    def test_s3_encryption_missing_objects_and_partial_cleanup_failure(self):
        service = Mock()
        with patch.object(aws_objects, "client", return_value=service):
            aws_objects.put("owner/case/file", b"synthetic")
            self.assertEqual(service.put_object.call_args.kwargs["ServerSideEncryption"], "AES256")
            service.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            with self.assertRaises(FileNotFoundError):
                aws_objects.get("owner/case/missing")
            service.delete_objects.return_value = {"Errors": [{"Code": "AccessDenied"}]}
            with self.assertRaises(RuntimeError):
                aws_objects.delete(["owner/case/file"])

    def test_unsafe_paths_and_download_header_injection(self):
        for path in ("../secret", "/secret", "owner/../secret", "owner\\secret"):
            with self.assertRaises(ValueError):
                aws_objects.valid_path(path)
        service = Mock()
        with patch.object(aws_objects, "client", return_value=service):
            aws_objects.signed_download("owner/case/report", 'report.pdf\r\nInjected: yes')
        args = service.generate_presigned_url.call_args.kwargs
        self.assertEqual(args["ExpiresIn"], 300)
        self.assertNotIn("\r", args["Params"]["ResponseContentDisposition"])
        self.assertNotIn("\n", args["Params"]["ResponseContentDisposition"])

    def test_cloud_api_import_does_not_load_embedding_runtime(self):
        process = subprocess.run([sys.executable, "-c", "import sys; import app.main; assert 'torch' not in sys.modules; assert 'sentence_transformers' not in sys.modules"],
                                 env={**os.environ, "SENTINEL_MODE": "cloud"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_cutover_pause_keeps_authenticated_reads_but_blocks_writes(self):
        code = """from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch
with TestClient(app) as c, patch('app.cloud.auth.authenticate',return_value={'id':'u','email':'u@example.test','role':'admin'}), patch('app.cases.router.store.list_cases',return_value=[]):
    assert c.get('/me').status_code==200
    assert c.get('/cases').json()==[]
    result=c.post('/cases',json={'name':'paused'})
    assert result.status_code==503 and result.json()['code']=='migration_read_only'
    assert c.get('/cases/anything/report').status_code==503
"""
        env={**os.environ,"SENTINEL_MODE":"cloud","SENTINEL_CLOUD_PROVIDER":"aws","SENTINEL_READ_ONLY":"true",
             "AWS_REGION":"ap-southeast-2","SENTINEL_DATABASE_SECRET_ID":"test","SENTINEL_STORAGE_BUCKET":"test",
             "COGNITO_USER_POOL_ID":"test","COGNITO_CLIENT_ID":"test","SENTINEL_SECRET_PREFIX":"test","SENTINEL_RDS_CA_FILE":"test"}
        result=subprocess.run([sys.executable,"-c",code],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
