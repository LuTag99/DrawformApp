#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Evaluate curated real-part reference-learning budgets from the existing index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_INDEX_PATH = ROOT / "knowledge" / "reference_learning" / "reference_drawings_index.json"
DEFAULT_MANIFEST_PATH = ROOT / "knowledge" / "reference_learning" / "real_priority_samples.json"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gate curated real parts against the reference-learning index."
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="reference_drawings_index.json path",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Curated real-priority manifest path",
    )
    parser.add_argument(
        "--priority-only",
        action="store_true",
        help="Evaluate only manifest entries tagged with group=priority.",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON file: {path} ({exc})") from exc


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_manifest_entries(path: Path, *, priority_only: bool) -> list[dict[str, Any]]:
    payload = _load_json(path)
    entries = payload.get("samples")
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"Manifest has no samples: {path}")
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(f"Invalid manifest entry in {path}: {entry!r}")
        if priority_only and str(entry.get("group") or "").strip().lower() != "priority":
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            raise SystemExit(f"Manifest entry missing name in {path}: {entry!r}")
        normalized.append(entry)
    if not normalized:
        raise SystemExit(f"Manifest selection is empty: {path}")
    return normalized


def evaluate_entry(entry: dict[str, Any], record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    comparison = record.get("comparison") or {}
    thresholds = entry.get("reference_learning") or {}
    flags = set(comparison.get("flags") or [])

    if bool(thresholds.get("require_sheet_match")) and not bool(comparison.get("sheet_match")):
        issues.append("sheet_match expected True")
    if bool(thresholds.get("require_abwicklung_match")) and not bool(comparison.get("abwicklung_match")):
        issues.append("abwicklung_match expected True")

    max_occupancy = _as_float(thresholds.get("max_occupancy_l1"))
    occupancy = _as_float(comparison.get("occupancy_l1"))
    if max_occupancy is not None:
        if occupancy is None:
            issues.append("occupancy_l1 missing")
        elif occupancy > max_occupancy:
            issues.append(f"occupancy_l1 {occupancy:.4f} > {max_occupancy:.4f}")

    min_font_ratio = _as_float(thresholds.get("min_font_ratio"))
    font_ratio = _as_float(comparison.get("median_font_ratio"))
    if min_font_ratio is not None:
        if font_ratio is None:
            issues.append("median_font_ratio missing")
        elif font_ratio < min_font_ratio:
            issues.append(f"median_font_ratio {font_ratio:.3f} < {min_font_ratio:.3f}")

    for flag in thresholds.get("disallowed_flags") or []:
        if flag in flags:
            issues.append(f"disallowed flag present: {flag}")

    return issues


def main(argv=None) -> int:
    args = parse_args(argv)
    index_payload = _load_json(args.index)
    records = index_payload.get("records")
    if not isinstance(records, list) or not records:
        raise SystemExit(f"Reference-learning index has no records: {args.index}")
    record_map = {
        str(record.get("name") or "").strip(): record
        for record in records
        if str(record.get("name") or "").strip()
    }
    entries = load_manifest_entries(args.manifest, priority_only=args.priority_only)

    failures = 0
    print("\n[reference-learning-gate] Curated real-part gate")
    print(f"[reference-learning-gate] index: {args.index}")
    print(f"[reference-learning-gate] manifest: {args.manifest}")
    for entry in entries:
        name = str(entry["name"])
        record = record_map.get(name)
        if record is None:
            print(f"[reference-learning-gate] FAIL {name}: missing in reference index")
            failures += 1
            continue
        issues = evaluate_entry(entry, record)
        if issues:
            print(f"[reference-learning-gate] FAIL {name}")
            for issue in issues:
                print(f"  - {issue}")
            failures += 1
            continue
        comparison = record.get("comparison") or {}
        print(
            "[reference-learning-gate] OK {name} "
            "(occupancy_l1={occ:.4f}, font_ratio={font:.3f}, flags={flags})".format(
                name=name,
                occ=_as_float(comparison.get("occupancy_l1")) or 0.0,
                font=_as_float(comparison.get("median_font_ratio")) or 0.0,
                flags=",".join(comparison.get("flags") or []) or "-",
            )
        )

    if failures:
        print(f"\n[reference-learning-gate] FAILED: {failures} issue block(s)")
        return 1
    print("\n[reference-learning-gate] All curated samples passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
