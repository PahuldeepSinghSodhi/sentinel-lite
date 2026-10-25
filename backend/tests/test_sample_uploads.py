"""Sample isolation and terminal file-validation regressions without cloud writes."""
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.cloud import samples, uploads, store, worker, jobs
from app.cloud.auth import user_context
from app.cases.store import validate_file


class SampleUploadTests(TestCase):
    def test_packaged_sample_has_all_three_valid_files(self):
        counts = {}
        for kind, relative in samples.FILES:
            path = samples.BACKEND_DIR/"data"/relative
            counts[kind] = validate_file(kind,path.name,path.read_bytes())[1]
        self.assertEqual(counts["transactions"],12)
        self.assertGreater(counts["rate_card"],0)
        self.assertGreater(counts["contract"],0)

    def test_existing_active_sample_reopens_without_writes_or_new_jobs(self):
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={"id":"sample","status":"active"}
        with user_context({"id":"owner"}),patch.object(samples.db,"connect") as db,patch.object(samples.store,"get_case",return_value={"id":"sample"}):
            db.return_value.__enter__.return_value=conn
            self.assertEqual(samples.open_sample(),{"id":"sample"})
        self.assertFalse(any("INSERT" in call.args[0] for call in conn.execute.call_args_list))
        self.assertIn(("owner",),[call.args[1] for call in conn.execute.call_args_list])

    def test_provisioning_does_not_mark_sample_active_if_a_file_fails(self):
        with patch.object(store,"get_case",return_value={"ready":False}),patch.object(store,"save_file",side_effect=ValueError("Storage limit reached")),patch.object(store,"mark_started") as started:
            with self.assertRaises(ValueError):samples.prepare_sample("sample")
            started.assert_not_called()

    def test_finished_provisioning_is_idempotent(self):
        with patch.object(store,"get_case",return_value={"ready":True}),patch.object(store,"save_file") as save:
            self.assertEqual(samples.prepare_sample("sample"),{"case_id":"sample"})
            save.assert_not_called()

    def test_provisioning_retry_uses_same_case_after_partial_file_failure(self):
        with patch.object(store,"get_case",return_value={"ready":False}),patch.object(store,"save_file") as save,patch.object(store,"sync_artifacts"),patch.object(store,"mark_started") as started,patch("app.cases.sources.build_index"):
            save.side_effect=[{},ValueError("Storage temporarily full")]
            with self.assertRaises(ValueError):samples.prepare_sample("same-case")
            started.assert_not_called()
            save.side_effect=None
            samples.prepare_sample("same-case")
            started.assert_called_once_with("same-case")
            self.assertTrue(all(c.args[0]=="same-case" for c in save.call_args_list))

    def test_sample_source_write_requires_its_running_provisioning_job(self):
        conn=MagicMock()
        with user_context({"id":"owner"}),self.assertRaisesRegex(ValueError,"Sample files are fixed"):
            store._check_file_write(conn,{"id":"sample","sample_version":"v1","status":"draft"})
        conn.execute.return_value.fetchone.return_value={"exists":1}
        with user_context({"id":"owner"},"demo-job"):
            store._check_file_write(conn,{"id":"sample","sample_version":"v1","status":"starting"},True)

    def test_invalid_content_is_a_terminal_validation_error_before_adoption(self):
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={"id":"upload","status":"queued","case_id":"case","kind":"transactions","filename":"random.csv","size":3,"path":"staging/test"}
        with user_context({"id":"owner"}),patch.object(uploads.db,"connect") as db,patch.object(uploads.objects,"get",return_value=b"bad"),patch.object(uploads.store,"save_file",side_effect=ValueError("Missing required columns: hourly_rate")),patch.object(uploads.objects,"delete") as delete:
            db.return_value.__enter__.return_value=conn
            with self.assertRaisesRegex(uploads.UploadValidationError,"Missing required columns"):
                uploads.validate_upload("upload")
            delete.assert_not_called()

    def test_worker_does_not_retry_invalid_upload(self):
        job={"id":str(uuid4()),"case_id":str(uuid4()),"owner_id":str(uuid4()),"kind":"upload","attempts":1,"payload_json":{"upload_id":"upload"}}
        conn=MagicMock();conn.execute.return_value.fetchone.side_effect=[{"email":"qa@example.test"},{"exists":1}]
        with tempfile.TemporaryDirectory() as scratch,patch.object(worker,"PROVIDER","aws"),patch.object(jobs,"claim",return_value=job),patch.object(jobs,"fail") as fail,patch.object(worker.db,"connect") as db,patch.object(store,"root",return_value=Path(scratch)),patch("app.cloud.aws_jobs.perform",side_effect=uploads.UploadValidationError("Missing required columns: hourly_rate")):
            db.return_value.__enter__.return_value=conn
            self.assertTrue(worker.run_once())
            fail.assert_called_once_with(job,public_error="Missing required columns: hourly_rate",terminal=True,error_code="upload_invalid")

    def test_cancellation_does_not_remove_running_or_completed_upload(self):
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={"status":"queued"}
        with user_context({"id":"owner"}),patch.object(uploads.db,"connect") as db,patch.object(store,"_owner"),patch.object(uploads.objects,"delete") as delete:
            db.return_value.__enter__.return_value=conn
            with self.assertRaisesRegex(ValueError,"already being validated"):
                uploads.cancel("case",str(uuid4()))
            delete.assert_not_called()

    def test_confirmation_rolls_back_reservation_when_job_insert_fails(self):
        conn=MagicMock()
        conn.execute.return_value.fetchone.side_effect=[{"status":"reserved","size":3,"path":"staging/file"},{"status":"reserved"},None]
        with user_context({"id":"owner"}),patch.object(uploads.db,"connect") as db,patch.object(store,"_owner"),patch.object(uploads,"client") as aws,patch("app.cloud.aws_jobs.queue",side_effect=RuntimeError("queue unavailable")) as queue,patch.object(uploads,"fail_upload"):
            db.return_value.__enter__.return_value=conn
            aws.return_value.head_object.return_value={"ContentLength":3}
            with self.assertRaisesRegex(RuntimeError,"queue unavailable"):
                uploads.confirm("case",str(uuid4()))
            self.assertIs(queue.call_args.kwargs["connection"],conn)
            self.assertTrue(any(c.args[0] is RuntimeError for c in db.return_value.__exit__.call_args_list))
