from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping


def load_job_map(path: Path | str) -> dict[str, dict[str, Any]]:
    job_path = Path(path)
    if not job_path.exists():
        return {}
    try:
        payload = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    jobs: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, dict):
            jobs[key] = value
    return jobs


def save_job_map(path: Path | str, jobs: Mapping[str, Mapping[str, Any]]) -> Path:
    job_path = Path(path)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = job_path.with_suffix(job_path.suffix + ".tmp")
    payload = json.dumps(dict(jobs), indent=2, ensure_ascii=True)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(job_path)
    return job_path
