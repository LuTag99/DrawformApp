#!/usr/bin/env python
"""API endpoint integration tests with mocked FreeCAD subprocess calls."""

from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main

TEST_USER = main.AuthenticatedUser(uid="test-user", email="test@drawform.local")


class ApiEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        # Explizit den Auth-Vertrag fuer Tests injizieren: kein Bearer-Token,
        # kein Firebase-Admin-SDK; stattdessen ein fixer Test-User, dessen
        # ownerUid wir pro Request kennen.
        main.app.dependency_overrides[main.require_current_user] = lambda: TEST_USER
        self.client = TestClient(main.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_analyzer_jobs_path = main.ANALYZER_JOBS_PATH
        self.previous_reconstruct_jobs_path = main.RECONSTRUCT_JOBS_PATH
        temp_root = Path(self.temp_dir.name)
        main.ANALYZER_JOBS_PATH = temp_root / "analyzer_jobs.json"
        main.RECONSTRUCT_JOBS_PATH = temp_root / "reconstruct_jobs.json"
        with main.ANALYZER_LOCK:
            main.ANALYZER_JOBS.clear()
        with main.RECONSTRUCT_LOCK:
            main.RECONSTRUCT_JOBS.clear()

    def tearDown(self) -> None:
        main.app.dependency_overrides.pop(main.require_current_user, None)
        with main.ANALYZER_LOCK:
            main.ANALYZER_JOBS.clear()
        with main.RECONSTRUCT_LOCK:
            main.RECONSTRUCT_JOBS.clear()
        main.ANALYZER_JOBS_PATH = self.previous_analyzer_jobs_path
        main.RECONSTRUCT_JOBS_PATH = self.previous_reconstruct_jobs_path
        self.temp_dir.cleanup()

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
                data={"format": "pdf", "export_id": "exp-client-123"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("content-type"), "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))

    def test_export_endpoint_rejects_invalid_client_export_id(self) -> None:
        response = self.client.post(
            "/api/export",
            files={"file": ("sample.step", b"ISO-10303-21;", "application/step")},
            data={"format": "pdf", "export_id": "bad/id"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("export_id has invalid format", response.text)

    def test_export_endpoint_validates_norm_profile(self) -> None:
        response = self.client.post(
            "/api/export",
            files={"file": ("sample.step", b"ISO-10303-21;", "application/step")},
            data={"format": "pdf", "scale": "3:7"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported scale", response.text)

    def test_ai_insight_endpoint_returns_backend_proxy_payload(self) -> None:
        response = self.client.post(
            "/api/ai-insight",
            json={"statusSummary": "Fast gate ok, baseline 20/20 passed, complex_bracket render ok."},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsInstance(payload.get("narrative"), str)
        self.assertTrue(payload["narrative"])
        self.assertEqual(payload.get("chips"), ["Fast Gate gruen", "Baseline stabil", "Weiterbauen"])

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
            self.assertTrue(main.ANALYZER_JOBS_PATH.exists())

    def test_analyze_job_is_persisted_to_disk(self) -> None:
        with patch("main.ANALYZER_WORKER_DELAY_SECONDS", 0.0), patch(
            "main.run_feature_probe", return_value=None
        ):
            response = self.client.post(
                "/api/analyze",
                files={"file": ("part.step", b"ISO-10303-21;", "application/step")},
                data={"units": "mm", "scale": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        persisted = main.load_job_map(main.ANALYZER_JOBS_PATH)
        self.assertIn(job_id, persisted)

    def test_analyze_endpoint_respects_client_job_id(self) -> None:
        with patch("main.ANALYZER_WORKER_DELAY_SECONDS", 0.0), patch(
            "main.run_feature_probe", return_value=None
        ):
            response = self.client.post(
                "/api/analyze",
                files={"file": ("part.step", b"ISO-10303-21;", "application/step")},
                data={"job_id": "job-client-123", "units": "mm", "scale": "1"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["id"], "job-client-123")
        self.assertEqual(payload["metadata"]["jobId"], "job-client-123")
        persisted = main.load_job_map(main.ANALYZER_JOBS_PATH)
        self.assertIn("job-client-123", persisted)

    def test_reconstruct_job_is_persisted_to_disk(self) -> None:
        with patch("main._run_reconstruct_pipeline", return_value=None):
            response = self.client.post(
                "/api/reconstruct",
                files={
                    "front": ("front.png", b"front", "image/png"),
                    "top": ("top.png", b"top", "image/png"),
                    "left": ("left.png", b"left", "image/png"),
                    "right": ("right.png", b"right", "image/png"),
                    "back": ("back.png", b"back", "image/png"),
                },
                data={"part_name": "Bracket", "width_mm": "120", "height_mm": "80", "depth_mm": "25"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["id"]
        persisted = main.load_job_map(main.RECONSTRUCT_JOBS_PATH)
        self.assertIn(job_id, persisted)


class AuthContractTests(unittest.TestCase):
    """Locked-in behavior of require_current_user for the two supported modes."""

    def test_disabled_mode_returns_stub_user(self) -> None:
        previous = main.FIREBASE_AUTH_ENABLED
        main.FIREBASE_AUTH_ENABLED = False
        try:
            user = main.require_current_user(authorization=None)
        finally:
            main.FIREBASE_AUTH_ENABLED = previous
        self.assertEqual(user.uid, main.LOCAL_DEV_UID)
        self.assertEqual(user.email, main.LOCAL_DEV_EMAIL)

    def test_enabled_mode_without_token_raises_401(self) -> None:
        from fastapi import HTTPException

        previous = main.FIREBASE_AUTH_ENABLED
        main.FIREBASE_AUTH_ENABLED = True
        try:
            with self.assertRaises(HTTPException) as ctx:
                main.require_current_user(authorization=None)
        finally:
            main.FIREBASE_AUTH_ENABLED = previous
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
