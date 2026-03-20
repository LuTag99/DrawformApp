"""Artifact and run-state helpers for Drawform orchestration."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path

from .run_schema import ArtifactRecord, RunState


SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
DEBUG_ROOT = SERVER_ROOT / "_debug"
RUNS_ROOT = DEBUG_ROOT / "agent_runs"
_SAFE_NAME_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Normalize arbitrary text to a filesystem-friendly slug."""

    lowered = str(value or "").strip().lower()
    normalized = _SAFE_NAME_RE.sub("_", lowered).strip("_")
    return normalized or "run"


def to_repo_relative(path: Path) -> str:
    """Return a repo-relative path string when possible."""

    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def create_run_id(*, task_summary: str, target_case: str) -> str:
    """Create a stable run id with timestamp + target case."""

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    task_slug = slugify(task_summary)[:40]
    case_slug = slugify(target_case)[:30]
    return f"{case_slug}_{task_slug}_{timestamp}"


def ensure_run_dir(run_id: str, *, runs_root: Path = RUNS_ROOT) -> Path:
    """Create the run artifact directory if needed."""

    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def resolve_run_state_path(run_ref: str | Path, *, runs_root: Path = RUNS_ROOT) -> Path:
    """Resolve either a run id or a direct path to a run_state.json file."""

    candidate = Path(run_ref)
    if candidate.exists():
        if candidate.is_dir():
            return candidate / "run_state.json"
        return candidate
    return runs_root / str(run_ref) / "run_state.json"


def save_run_state(state: RunState, *, destination: Path | None = None) -> Path:
    """Persist the current run state as JSON."""

    destination = destination or (Path(state.artifact_dir) / "run_state.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump(mode="json")
    tmp_destination = destination.with_suffix(destination.suffix + ".tmp")
    tmp_destination.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp_destination.replace(destination)
    return destination


def load_run_state(run_ref: str | Path, *, runs_root: Path = RUNS_ROOT) -> RunState:
    """Load an existing run state by id or path."""

    state_path = resolve_run_state_path(run_ref, runs_root=runs_root)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise ValueError(f"Corrupted run_state.json: {state_path}") from exc
    return RunState.model_validate(payload)


def _copy_if_exists(source: Path, destination_dir: Path) -> str | None:
    """Copy a file into the run directory and return a repo-relative path."""

    if not source.exists():
        return None
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    return to_repo_relative(destination)


def collect_target_case_artifacts(
    state: RunState,
    *,
    source_debug_dir: Path = DEBUG_ROOT,
    include_review_checklist: bool = False,
) -> ArtifactRecord:
    """Copy the latest known artifacts for the active target case into the run dir."""

    run_dir = Path(state.artifact_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    target = state.target_case
    artifacts = ArtifactRecord(
        debug_svg=_copy_if_exists(source_debug_dir / f"{target}_debug.svg", run_dir),
        preview_png=_copy_if_exists(source_debug_dir / f"{target}_preview.png", run_dir),
        report_json=_copy_if_exists(source_debug_dir / f"{target}_report.json", run_dir),
        pdf=_copy_if_exists(source_debug_dir / f"{target}_latest.pdf", run_dir),
    )
    extra_files: list[str] = []
    if include_review_checklist:
        copied = _copy_if_exists(source_debug_dir / "PDF_REVIEW_CHECKLIST.md", run_dir)
        if copied:
            extra_files.append(copied)
    artifacts.extra_files = extra_files
    state.latest_artifacts = artifacts
    return artifacts
