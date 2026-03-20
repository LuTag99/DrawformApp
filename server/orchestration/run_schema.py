"""Run-state schema for Drawform orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PathType(StrEnum):
    FAST_PATH = "FAST-PATH"
    FULL_PATH = "FULL-PATH"
    LONG_RUN = "LONG-RUN"


class RunStage(StrEnum):
    PLANNER = "planner"
    BUILDER = "builder"
    ARTIFACT_STEWARD = "artifact_steward"
    CRITIC = "critic"
    REGRESSION = "regression"
    REPORT = "report"
    DONE = "done"


class RunStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class ArtifactRecord(BaseModel):
    """Normalized artifact references for the active target case."""

    debug_svg: str | None = None
    preview_png: str | None = None
    report_json: str | None = None
    pdf: str | None = None
    extra_files: list[str] = Field(default_factory=list)


class GateState(BaseModel):
    """Outcome of the critic / regression gates."""

    critic_passed: bool | None = None
    regression_passed: bool | None = None
    release_passed: bool | None = None
    consecutive_passes: int = 0


class RunEvent(BaseModel):
    """Small event log for traceability across iterations."""

    timestamp_utc: str
    stage: RunStage
    message: str


class RunState(BaseModel):
    """Persistent state for one orchestrated Drawform run."""

    run_id: str
    task_summary: str
    revision: int = Field(default=0, ge=0)
    iteration: int = Field(default=1, ge=1)
    path_type: PathType
    target_case: str
    benchmark_set: str = "baseline"
    artifact_dir: str
    stage: RunStage = RunStage.PLANNER
    status: RunStatus = RunStatus.IN_PROGRESS
    previous_verdict: str | None = None
    previous_failure_classes: list[str] = Field(default_factory=list)
    required_commands: list[str] = Field(default_factory=list)
    latest_builder_change: list[str] = Field(default_factory=list)
    latest_artifacts: ArtifactRecord = Field(default_factory=ArtifactRecord)
    critic_verdict: str | None = None
    critic_scores: dict[str, int] | None = None
    failure_classes: list[str] = Field(default_factory=list)
    regression_summary: dict[str, Any] = Field(default_factory=dict)
    open_risks: list[str] = Field(default_factory=list)
    gates: GateState = Field(default_factory=GateState)
    history: list[RunEvent] = Field(default_factory=list)

    def add_event(self, *, stage: RunStage | None = None, message: str) -> None:
        """Append a timestamped event to the run history."""

        self.history.append(
            RunEvent(
                timestamp_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
                stage=stage or self.stage,
                message=message,
            )
        )

    def bump_revision(self) -> None:
        """Advance the run revision after a persisted state change."""

        self.revision += 1
