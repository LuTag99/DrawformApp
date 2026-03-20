from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestration.artifacts import collect_target_case_artifacts, load_run_state, save_run_state
from orchestration.orchestrator import advance_run_state
from orchestration.run_schema import PathType, RunStage, RunState


class OrchestrationTests(unittest.TestCase):
    def test_save_and_load_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "run_a"
            state = RunState(
                run_id="run_a",
                task_summary="test run",
                path_type=PathType.FULL_PATH,
                target_case="complex_bracket",
                benchmark_set="baseline",
                artifact_dir=str(artifact_dir),
            )
            state.add_event(message="Initialized in test.")
            path = save_run_state(state)
            loaded = load_run_state(path)
            self.assertEqual(loaded.run_id, "run_a")
            self.assertEqual(loaded.target_case, "complex_bracket")
            self.assertEqual(len(loaded.history), 1)

    def test_collect_target_case_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            debug_dir = tmp_path / "_debug"
            debug_dir.mkdir()
            for suffix in ("debug.svg", "preview.png", "report.json", "latest.pdf"):
                (debug_dir / f"sample_part_{suffix}").write_text("artifact", encoding="utf-8")

            state = RunState(
                run_id="run_artifacts",
                task_summary="artifact sync",
                path_type=PathType.FULL_PATH,
                target_case="sample_part",
                benchmark_set="baseline",
                artifact_dir=str(tmp_path / "agent_runs" / "run_artifacts"),
            )
            artifacts = collect_target_case_artifacts(state, source_debug_dir=debug_dir)
            self.assertTrue(artifacts.debug_svg)
            self.assertTrue((tmp_path / "agent_runs" / "run_artifacts" / "sample_part_debug.svg").exists())
            self.assertTrue((tmp_path / "agent_runs" / "run_artifacts" / "sample_part_report.json").exists())

    def test_full_path_stage_flow(self) -> None:
        state = RunState(
            run_id="run_flow",
            task_summary="flow",
            path_type=PathType.FULL_PATH,
            target_case="complex_bracket",
            benchmark_set="baseline",
            artifact_dir="server/_debug/agent_runs/run_flow",
        )
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.BUILDER)
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.ARTIFACT_STEWARD)
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.CRITIC)
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.REGRESSION)
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.REPORT)
        self.assertEqual(advance_run_state(state, decision="pass").stage, RunStage.DONE)

    def test_advance_rejects_stale_stage(self) -> None:
        state = RunState(
            run_id="run_guard",
            task_summary="guard",
            path_type=PathType.FULL_PATH,
            target_case="complex_bracket",
            benchmark_set="baseline",
            artifact_dir="server/_debug/agent_runs/run_guard",
            stage=RunStage.BUILDER,
        )
        with self.assertRaisesRegex(ValueError, "Stage mismatch"):
            advance_run_state(state, decision="pass", expected_stage=RunStage.CRITIC)

    def test_long_run_requires_second_pass_cycle(self) -> None:
        state = RunState(
            run_id="run_long",
            task_summary="long flow",
            path_type=PathType.LONG_RUN,
            target_case="complex_bracket",
            benchmark_set="baseline",
            artifact_dir="server/_debug/agent_runs/run_long",
            stage=RunStage.REGRESSION,
        )
        advance_run_state(state, decision="pass")
        self.assertEqual(state.stage, RunStage.REPORT)
        self.assertEqual(state.gates.consecutive_passes, 1)
        advance_run_state(state, decision="pass")
        self.assertEqual(state.stage, RunStage.BUILDER)
        self.assertEqual(state.iteration, 2)

    def test_revision_increments_after_transition(self) -> None:
        state = RunState(
            run_id="run_revision",
            task_summary="revision",
            path_type=PathType.FULL_PATH,
            target_case="complex_bracket",
            benchmark_set="baseline",
            artifact_dir="server/_debug/agent_runs/run_revision",
        )
        self.assertEqual(state.revision, 0)
        advance_run_state(state, decision="pass")
        self.assertEqual(state.revision, 1)


if __name__ == "__main__":
    unittest.main()
