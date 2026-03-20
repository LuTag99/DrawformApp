"""Simple CLI orchestrator for Drawform agent runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from orchestration.artifacts import RUNS_ROOT, collect_target_case_artifacts, create_run_id, ensure_run_dir, load_run_state, save_run_state
    from orchestration.run_schema import PathType, RunStage, RunState, RunStatus
else:
    from .artifacts import RUNS_ROOT, collect_target_case_artifacts, create_run_id, ensure_run_dir, load_run_state, save_run_state
    from .run_schema import PathType, RunStage, RunState, RunStatus


def _load_json_payload(raw: str | None = None, *, file_path: str | None = None) -> dict[str, Any]:
    if file_path:
        payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
        return dict(payload)
    if not raw:
        return {}
    if raw.startswith("@"):
        payload = json.loads(Path(raw[1:]).read_text(encoding="utf-8"))
        return dict(payload)
    payload = json.loads(raw)
    return dict(payload)


def _parse_scores(raw: str | None = None, *, file_path: str | None = None) -> dict[str, int] | None:
    payload = _load_json_payload(raw, file_path=file_path)
    if not payload:
        return None
    return {str(key): int(value) for key, value in dict(payload).items()}


def _parse_mapping(raw: str | None = None, *, file_path: str | None = None) -> dict[str, Any]:
    return _load_json_payload(raw, file_path=file_path)


def _format_summary(state: RunState) -> str:
    return "\n".join(
        [
            f"run_id={state.run_id}",
            f"revision={state.revision}",
            f"stage={state.stage}",
            f"status={state.status}",
            f"iteration={state.iteration}",
            f"path_type={state.path_type}",
            f"target_case={state.target_case}",
            f"benchmark_set={state.benchmark_set}",
            f"artifact_dir={state.artifact_dir}",
            f"critic_verdict={state.critic_verdict or '-'}",
            f"failure_classes={','.join(state.failure_classes) or '-'}",
            f"consecutive_passes={state.gates.consecutive_passes}",
        ]
    )


def _next_stage_for_pass(state: RunState) -> RunStage:
    if state.stage == RunStage.PLANNER:
        return RunStage.BUILDER
    if state.stage == RunStage.BUILDER:
        if state.path_type == PathType.FAST_PATH:
            return RunStage.CRITIC
        return RunStage.ARTIFACT_STEWARD
    if state.stage == RunStage.ARTIFACT_STEWARD:
        return RunStage.CRITIC
    if state.stage == RunStage.CRITIC:
        if state.path_type == PathType.FAST_PATH:
            return RunStage.REPORT
        return RunStage.REGRESSION
    if state.stage == RunStage.REGRESSION:
        return RunStage.REPORT
    if state.stage == RunStage.REPORT:
        if state.path_type == PathType.LONG_RUN and state.gates.consecutive_passes < 2:
            return RunStage.BUILDER
        return RunStage.DONE
    return RunStage.DONE


def advance_run_state(
    state: RunState,
    *,
    decision: str,
    note: str | None = None,
    expected_stage: RunStage | None = None,
    expected_iteration: int | None = None,
    expected_revision: int | None = None,
    critic_verdict: str | None = None,
    critic_scores: dict[str, int] | None = None,
    regression_summary: dict[str, Any] | None = None,
    failure_classes: list[str] | None = None,
    open_risks: list[str] | None = None,
    latest_builder_change: list[str] | None = None,
) -> RunState:
    """Advance the run according to the current stage and gate decision."""

    decision = str(decision or "pass").strip().lower()
    if decision not in {"pass", "fail", "hold"}:
        raise ValueError(f"Unsupported decision: {decision}")

    if expected_stage is not None and state.stage != expected_stage:
        raise ValueError(f"Stage mismatch: expected {expected_stage}, found {state.stage}")
    if expected_iteration is not None and state.iteration != expected_iteration:
        raise ValueError(f"Iteration mismatch: expected {expected_iteration}, found {state.iteration}")
    if expected_revision is not None and state.revision != expected_revision:
        raise ValueError(f"Revision mismatch: expected {expected_revision}, found {state.revision}")

    if critic_verdict is not None:
        state.critic_verdict = critic_verdict
    if critic_scores is not None:
        state.critic_scores = critic_scores
    if regression_summary:
        state.regression_summary = regression_summary
    if failure_classes is not None:
        state.previous_failure_classes = list(state.failure_classes)
        state.failure_classes = list(dict.fromkeys(failure_classes))
    if open_risks:
        state.open_risks = list(dict.fromkeys([*state.open_risks, *open_risks]))
    if latest_builder_change:
        state.latest_builder_change = list(latest_builder_change)

    current_stage = state.stage

    if decision == "hold":
        state.status = RunStatus.BLOCKED
        state.add_event(stage=current_stage, message=note or "Run put on hold.")
        state.bump_revision()
        return state

    if current_stage == RunStage.CRITIC:
        state.gates.critic_passed = decision == "pass"
        if decision != "pass":
            state.gates.consecutive_passes = 0
    if current_stage == RunStage.REGRESSION:
        state.gates.regression_passed = decision == "pass"
        if decision == "pass":
            state.gates.consecutive_passes += 1
        else:
            state.gates.consecutive_passes = 0

    if decision == "fail":
        if current_stage in {RunStage.CRITIC, RunStage.REGRESSION, RunStage.REPORT}:
            state.iteration += 1
            state.stage = RunStage.BUILDER
            state.status = RunStatus.IN_PROGRESS
            state.add_event(
                stage=current_stage,
                message=note or f"{current_stage} failed; looping back to builder for iteration {state.iteration}.",
            )
            state.bump_revision()
            return state
        state.status = RunStatus.FAILED
        state.add_event(stage=current_stage, message=note or f"{current_stage} failed.")
        state.bump_revision()
        return state

    next_stage = _next_stage_for_pass(state)
    state.stage = next_stage
    if next_stage == RunStage.DONE:
        state.status = RunStatus.COMPLETED
    else:
        if current_stage == RunStage.REPORT and state.path_type == PathType.LONG_RUN and state.gates.consecutive_passes < 2:
            state.iteration += 1
        state.status = RunStatus.IN_PROGRESS
    state.add_event(stage=current_stage, message=note or f"{current_stage} passed; next stage: {next_stage}.")
    state.bump_revision()
    return state


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run-state orchestrator for Drawform agent workflows.")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Create a new run state.")
    start.add_argument("--task-summary", required=True)
    start.add_argument("--target-case", required=True)
    start.add_argument("--path-type", choices=[item.value for item in PathType], required=True)
    start.add_argument("--benchmark-set", default="baseline")
    start.add_argument("--run-id", default=None)
    start.add_argument("--required-command", action="append", default=[])
    start.add_argument("--open-risk", action="append", default=[])
    start.add_argument("--initial-stage", choices=[RunStage.PLANNER.value, RunStage.BUILDER.value], default=RunStage.PLANNER.value)

    show = sub.add_parser("show", help="Show a run state.")
    show.add_argument("run_ref")
    show.add_argument("--json", action="store_true")

    collect = sub.add_parser("collect-artifacts", help="Copy current target-case artifacts into the run dir.")
    collect.add_argument("run_ref")
    collect.add_argument("--include-review-checklist", action="store_true")

    advance = sub.add_parser("advance", help="Advance a run state through the stage machine.")
    advance.add_argument("run_ref")
    advance.add_argument("--decision", choices=("pass", "fail", "hold"), default="pass")
    advance.add_argument("--note", default=None)
    advance.add_argument("--expect-stage", choices=[item.value for item in RunStage], default=None)
    advance.add_argument("--expect-iteration", type=int, default=None)
    advance.add_argument("--expect-revision", type=int, default=None)
    advance.add_argument("--critic-verdict", default=None)
    advance.add_argument("--critic-scores-json", default=None)
    advance.add_argument("--critic-scores-file", default=None)
    advance.add_argument("--regression-summary-json", default=None)
    advance.add_argument("--regression-summary-file", default=None)
    advance.add_argument("--failure-class", action="append", default=None)
    advance.add_argument("--open-risk", action="append", default=[])
    advance.add_argument("--builder-change", action="append", default=[])

    return parser


def _cmd_start(args: argparse.Namespace) -> int:
    run_id = args.run_id or create_run_id(task_summary=args.task_summary, target_case=args.target_case)
    run_dir = ensure_run_dir(run_id, runs_root=RUNS_ROOT)
    state = RunState(
        run_id=run_id,
        task_summary=args.task_summary,
        path_type=PathType(args.path_type),
        target_case=args.target_case,
        benchmark_set=args.benchmark_set,
        artifact_dir=str(run_dir),
        stage=RunStage(args.initial_stage),
        required_commands=list(args.required_command),
        open_risks=list(args.open_risk),
    )
    state.add_event(message="Run initialized.")
    save_run_state(state)
    print(_format_summary(state))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    state = load_run_state(args.run_ref, runs_root=RUNS_ROOT)
    if args.json:
        print(json.dumps(state.model_dump(mode="json"), indent=2, ensure_ascii=True))
    else:
        print(_format_summary(state))
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    state = load_run_state(args.run_ref, runs_root=RUNS_ROOT)
    artifacts = collect_target_case_artifacts(state, include_review_checklist=args.include_review_checklist)
    state.add_event(message="Artifacts synchronized for target case.")
    state.bump_revision()
    save_run_state(state)
    print(json.dumps(artifacts.model_dump(mode="json"), indent=2, ensure_ascii=True))
    return 0


def _cmd_advance(args: argparse.Namespace) -> int:
    state = load_run_state(args.run_ref, runs_root=RUNS_ROOT)
    updated = advance_run_state(
        state,
        decision=args.decision,
        note=args.note,
        expected_stage=RunStage(args.expect_stage) if args.expect_stage else None,
        expected_iteration=args.expect_iteration,
        expected_revision=args.expect_revision,
        critic_verdict=args.critic_verdict,
        critic_scores=_parse_scores(args.critic_scores_json, file_path=args.critic_scores_file),
        regression_summary=_parse_mapping(args.regression_summary_json, file_path=args.regression_summary_file),
        failure_classes=args.failure_class,
        open_risks=args.open_risk,
        latest_builder_change=args.builder_change,
    )
    save_run_state(updated)
    print(_format_summary(updated))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        return _cmd_start(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "collect-artifacts":
        return _cmd_collect(args)
    if args.command == "advance":
        return _cmd_advance(args)
    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
