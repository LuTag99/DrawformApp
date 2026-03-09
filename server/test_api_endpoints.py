#!/usr/bin/env python
"""API endpoint integration tests with mocked FreeCAD subprocess calls."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class ApiEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)
        with main.ANALYZER_LOCK:
            main.ANALYZER_JOBS.clear()

    def tearDown(self) -> None:
        with main.ANALYZER_LOCK:
            main.ANALYZER_JOBS.clear()

    def test_export_endpoint_returns_pdf(self) -> None:
        async def fake_to_thread(func, *args, **kwargs):
            command = args[0]
            output_path = Path(command[3])
            output_path.write_bytes(b"%PDF-1.4\n%Drawform Test PDF\n")
            return SimpleNamespace(returncode=0, stderr="", stdout="ok")

        with patch("main.resolve_freecad_cmd", return_value=Path(__file__).resolve()), patch(
            "main.asyncio.to_thread", new=fake_to_thread
        ):
            response = self.client.post(
                "/api/export",
                files={"file": ("sample.step", b"ISO-10303-21;", "application/step")},
                data={"format": "pdf"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("content-type"), "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))

    def test_export_endpoint_validates_norm_profile(self) -> None:
        response = self.client.post(
            "/api/export",
            files={"file": ("sample.step", b"ISO-10303-21;", "application/step")},
            data={"format": "pdf", "scale": "3:7"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported scale", response.text)

    def test_analyze_job_lifecycle(self) -> None:
        probe_payload = {
            "ok": True,
            "bbox_mm": {"X": 200.0, "Y": 80.0, "Z": 12.0},
            "hole_count": 4,
            "hole_diameter_mm": 8.0,
            "hole_pitch_mm": 120.0,
            "bend_radius_mm": 4.0,
            "is_flat": True,
            "flat_ratio": 0.15,
            "longest_axis": "X",
        }

        with patch("main.ANALYZER_WORKER_DELAY_SECONDS", 0.0), patch(
            "main.run_feature_probe", return_value=probe_payload
        ):
            create_response = self.client.post(
                "/api/analyze",
                files={"file": ("part.step", b"ISO-10303-21;", "application/step")},
                data={"units": "mm", "scale": "1", "views": '["Top","Front","Left","Iso"]'},
            )

            self.assertEqual(create_response.status_code, 200, create_response.text)
            payload = create_response.json()
            job_id = payload["id"]
            self.assertEqual(payload["status"], "pending")

            final_job = None
            for _ in range(40):
                get_response = self.client.get(f"/api/analyze/{job_id}")
                self.assertEqual(get_response.status_code, 200, get_response.text)
                final_job = get_response.json()
                if final_job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final_job)
            self.assertEqual(final_job.get("status"), "completed", final_job)
            result = final_job.get("result") or {}
            self.assertTrue(result.get("measurements"))
            self.assertTrue(result.get("recommendations"))

            list_response = self.client.get("/api/analyze")
            self.assertEqual(list_response.status_code, 200, list_response.text)
            jobs = list_response.json()
            self.assertTrue(any(job.get("id") == job_id for job in jobs))


if __name__ == "__main__":
    unittest.main()
