#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the local quality gate with iterative self-check loops."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_step(label: str, command: list[str], *, cwd: Path) -> int:
    print(f"\n[quality-gate] {label}")
    print(f"[quality-gate] cmd: {' '.join(command)}")
    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        print(f"[quality-gate] FAILED: {label} (exit={completed.returncode})")
    else:
        print(f"[quality-gate] OK: {label}")
    return completed.returncode


def resolve_python(explicit: str | None) -> str:
    if explicit:
        return explicit
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT.parent / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT.parent / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Drawform quality checks.")
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable used for subprocess runs (defaults to local .venv if present).",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Refresh golden baseline before verification run.",
    )
    parser.add_argument(
        "--stability-runs",
        type=int,
        default=2,
        help="Stability loop count for marked samples in test_views.py.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Repeat the full quality gate this many times (default: 1).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    py = resolve_python(args.python)
    print(f"[quality-gate] Python: {py}")

    steps: list[tuple[str, list[str], Path]] = [
        ("Norm profile unit tests", [py, "-m", "unittest", "test_norm_profile.py"], ROOT),
        ("API endpoint tests", [py, "-m", "unittest", "test_api_endpoints.py"], ROOT),
    ]

    if args.update_golden:
        steps.append(
            (
                "Update golden baseline",
                [py, "test_views.py", "--update-golden"],
                ROOT,
            )
        )

    steps.extend(
        [
            ("View regression", [py, "test_views.py", "--sample-set", "baseline"], ROOT),
            (
                "View stability loop",
                [
                    py,
                    "test_views.py",
                    "--sample-set",
                    "baseline",
                    "--stability-runs",
                    str(max(1, args.stability_runs)),
                ],
                ROOT,
            ),
            ("Generate PDF review checklist", [py, "generate_pdf_review_checklist.py"], ROOT),
        ]
    )

    failed = 0
    loop_count = max(1, int(args.iterations))
    for loop_index in range(1, loop_count + 1):
        print(f"\n[quality-gate] ==== Iteration {loop_index}/{loop_count} ====")
        for label, command, cwd in steps:
            rc = run_step(label, command, cwd=cwd)
            if rc != 0:
                failed += 1

    if failed:
        print(f"\n[quality-gate] Completed with {failed} failing step(s) across {loop_count} iteration(s).")
        return 1
    print(f"\n[quality-gate] All steps passed across {loop_count} iteration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
