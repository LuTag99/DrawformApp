from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import main
from job_persistence import load_job_map, save_job_map


class JobPersistenceTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            payload = {
                "job-1": {
                    "id": "job-1",
                    "status": "completed",
                    "metadata": {"views": ["Front"]},
                }
            }

            save_job_map(path, payload)
            loaded = load_job_map(path)

            self.assertEqual(loaded, payload)

    def test_load_returns_empty_map_for_invalid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text('["invalid"]', encoding="utf-8")

            self.assertEqual(load_job_map(path), {})

    def test_restore_marks_inflight_jobs_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            payload = {
                "job-1": {"id": "job-1", "status": "pending"},
                "job-2": {"id": "job-2", "status": "processing"},
                "job-3": {"id": "job-3", "status": "completed"},
            }

            save_job_map(path, payload)
            restored = main._restore_job_map(
                path,
                interruption_message="Backend restart interrupted the analyzer job.",
            )

            self.assertEqual(restored["job-1"]["status"], "failed")
            self.assertEqual(restored["job-2"]["status"], "failed")
            self.assertEqual(restored["job-3"]["status"], "completed")

            persisted = load_job_map(path)
            self.assertEqual(
                persisted["job-1"]["error"], "Backend restart interrupted the analyzer job."
            )
            self.assertEqual(
                persisted["job-2"]["error"], "Backend restart interrupted the analyzer job."
            )


if __name__ == "__main__":
    unittest.main()
