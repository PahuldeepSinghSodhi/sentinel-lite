"""Focused safety tests: no network calls, cloud writes, or real credentials."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.exceptions import InvalidTag

import recovery as r


class RecoveryTests(unittest.TestCase):
    def test_ciphertext_tampering_wrong_key_and_blob_swap_rejected(self):
        key = bytes(range(32))
        encrypted = r.seal(key, b"private document", "objects/000001.enc")
        self.assertNotIn(b"private document", encrypted)
        self.assertEqual(r.unseal(key, encrypted, "objects/000001.enc"), b"private document")
        for changed_key, body, name in (
            (bytes(32), encrypted, "objects/000001.enc"),
            (key, encrypted[:-1] + bytes([encrypted[-1] ^ 1]), "objects/000001.enc"),
            (key, encrypted, "objects/000002.enc"),
        ):
            with self.assertRaises(InvalidTag):
                r.unseal(changed_key, body, name)

    def test_allowlist_excludes_credentials(self):
        exported = " ".join(r.TABLES.values())
        for excluded in ("vault_id", "encrypted_password", "refresh_token", "secret", "identity_data"):
            self.assertNotIn(excluded, exported)
        self.assertEqual(set(r.TABLES["public.model_settings"].split()),
                         {"owner_id", "provider", "model", "updated_at"})

    def test_path_traversal_and_windows_paths_rejected(self):
        for name in ("", "../file", "/file", "a/../../file", "a\\file", "C:/file"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                r.validate_path(name)

    def test_missing_object_and_wrong_size_rejected(self):
        rows = {name: [] for name in r.TABLES}
        rows["public.case_files"] = [dict.fromkeys(r.TABLES["public.case_files"].split())]
        rows["public.case_files"][0].update(path="case/file.csv", size=5)
        for objects in ([], [{"name": "case/file.csv", "size": 6}]):
            with self.assertRaises(ValueError):
                r.validate_records(rows, objects)

    def test_unexpected_secret_column_rejected(self):
        rows = {name: [] for name in r.TABLES}
        rows["public.model_settings"] = [{**dict.fromkeys(r.TABLES["public.model_settings"].split()),
                                           "api_key": "synthetic-do-not-export"}]
        with self.assertRaises(ValueError):
            r.validate_records(rows, [])

    def test_schema_drift_rejected_before_reading_records(self):
        columns = [(name.split(".")[1], column)
                   for name, selected in r.TABLES.items() if name.startswith("public.")
                   for column in selected.split()]
        columns.append(("model_settings", "vault_id"))
        conn = Mock()
        conn.execute.side_effect = [columns, *([[]] * len(r.TABLES))]
        self.assertEqual(r.read_rows(conn), {name: [] for name in r.TABLES})
        conn = Mock()
        conn.execute.return_value = columns + [("model_settings", "new_secret")]
        with self.assertRaises(ValueError):
            r.read_rows(conn)
        self.assertEqual(conn.execute.call_count, 1)

    def fixture(self, directory, key):
        rows = {name: [] for name in r.TABLES}
        schema = b"-- synthetic schema"
        objects = [{"name": "case/file.csv", "size": 3, "file": "objects/000000.enc", "sha256": r.digest(b"csv")}]
        manifest = {"format": r.FORMAT, "source_consistent": True, "tables": rows,
                    "objects": objects, "schema_sha256": r.digest(schema)}
        (directory / "objects").mkdir()
        (directory / "objects/000000.enc").write_bytes(r.seal(key, b"csv", "objects/000000.enc"))
        (directory / "schema.enc").write_bytes(r.seal(key, schema, "schema.enc"))
        (directory / "manifest.enc").write_bytes(r.seal(key, r.canonical(manifest), "manifest.enc"))

    def test_verify_roundtrip_and_missing_blob(self):
        key = bytes(range(32))
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, "read_key", return_value=key):
            directory = Path(tmp)
            self.fixture(directory, key)
            result = r.verify(directory, "unused")
            self.assertTrue(result["verified"])
            self.assertEqual(result["objects"], 1)
            self.assertEqual(result["object_bytes"], 3)
            (directory / "objects/000000.enc").unlink()
            with self.assertRaises(FileNotFoundError):
                r.verify(directory, "unused")

    def test_remote_restore_rejected_without_connecting(self):
        with patch.object(r, "verify"), patch.object(r, "load_backup", return_value=(None, None, {})), patch.object(r.psycopg, "connect") as connect:
            for dsn in ("host=db.example.test dbname=postgres", "host=127.0.0.1 hostaddr=192.0.2.1"):
                with self.assertRaises(ValueError):
                    r.restore("unused", "unused", dsn, "unused")
            connect.assert_not_called()

    def test_existing_directory_and_repository_backup_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                r.backup("unused", tmp, "unused")
        with self.assertRaises(ValueError):
            r.backup("unused", r.ROOT / "recovery-private", "unused")


if __name__ == "__main__":
    unittest.main()
