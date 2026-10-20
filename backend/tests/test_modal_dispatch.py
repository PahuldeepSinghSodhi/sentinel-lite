"""Modal dispatch tests without a Modal account or billable resources."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.cloud import dispatch


class ModalDispatchTests(unittest.TestCase):
    def test_queued_job_is_spawned_once(self):
        worker = Mock()
        modal = SimpleNamespace(Function=SimpleNamespace(from_name=Mock(return_value=worker)))
        with patch("app.cloud.dispatch.jobs.queue", return_value={"job_id": "j1", "status": "queued"}) as queue, \
             patch.dict(sys.modules, {"modal": modal}):
            result = dispatch.queue_and_dispatch("c1", "scan")
        self.assertEqual(result["job_id"], "j1")
        queue.assert_called_once_with("c1", "scan")
        modal.Function.from_name.assert_called_once_with("sentinel-cloud", "process_jobs")
        worker.spawn.assert_called_once_with()

    def test_running_job_does_not_spawn_duplicate(self):
        modal = SimpleNamespace(Function=SimpleNamespace(from_name=Mock()))
        with patch("app.cloud.dispatch.jobs.queue", return_value={"job_id": "j1", "status": "running"}), \
             patch.dict(sys.modules, {"modal": modal}):
            dispatch.queue_and_dispatch("c1", "start")
        modal.Function.from_name.assert_not_called()

    def test_dispatch_failure_keeps_generic_error(self):
        worker = Mock()
        worker.spawn.side_effect = RuntimeError("provider secret should not leak")
        modal = SimpleNamespace(Function=SimpleNamespace(from_name=Mock(return_value=worker)))
        with patch("app.cloud.dispatch.jobs.queue", return_value={"job_id": "j1", "status": "queued"}), \
             patch.dict(sys.modules, {"modal": modal}):
            with self.assertRaisesRegex(RuntimeError, "processing could not start") as error:
                dispatch.queue_and_dispatch("c1", "scan")
        self.assertNotIn("provider secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
