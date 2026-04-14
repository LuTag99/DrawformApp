#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sample catalog utilities for baseline and real-world regression sets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent / "_samples"
REAL_PRIORITY_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "knowledge" / "reference_learning" / "real_priority_samples.json"
)
REAL20_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "knowledge" / "reference_learning" / "real20_samples.json"
)
REAL_SAMPLE_FOLDERS = {
    "milling parts",
    "sheetmetals",
    "02_millingparts_miba",
    "05_202500614-10000_endeffektor",
    "05_202500614-10000_endeffektor - fd",
    "10-03-2026",
    "2025-04-24_blechteile",
    "adapterplatte ur10_ur20",
    "bleche magazinwagen",
    "bleche magazinwagen 2",
}
# Top-level category folders for baseline samples (depth-1 subdirectories of _samples/).
BASELINE_CATEGORY_FOLDERS = {
    "fraesteile",
    "drehteile",
    "blechteile",
    "baugruppen",
}
STEP_EXTENSIONS = {".stp", ".step"}
PDF_EXTENSIONS = {".pdf"}
_DUPLICATE_SUFFIX_RE = re.compile(r" \(\d+\)$", flags=re.IGNORECASE)


@dataclass(frozen=True)
class SampleRecord:
    name: str
    step_path: Path
    pdf_path: Path | None
    category: str


def canonical_stem(stem: str) -> str:
    return _DUPLICATE_SUFFIX_RE.sub("", stem.strip()).strip().lower()


def display_stem(stem: str) -> str:
    return _DUPLICATE_SUFFIX_RE.sub("", stem.strip()).strip()


def _is_real_sample_path(path: Path, *, samples_dir: Path) -> bool:
    try:
        rel = path.relative_to(samples_dir)
    except ValueError:
        return False
    if len(rel.parts) < 2:
        return False
    # Old layout: _samples/<RealFolder>/file  (parts[0] is real folder)
    if rel.parts[0].lower() in REAL_SAMPLE_FOLDERS:
        return True
    # New layout: _samples/<Category>/<RealFolder>/file  (parts[1] is real folder)
    if len(rel.parts) >= 3 and rel.parts[1].lower() in REAL_SAMPLE_FOLDERS:
        return True
    return False


def _prefer_candidate(current: Path | None, candidate: Path) -> bool:
    if current is None:
        return True
    current_dup = bool(_DUPLICATE_SUFFIX_RE.search(current.stem))
    candidate_dup = bool(_DUPLICATE_SUFFIX_RE.search(candidate.stem))
    if current_dup != candidate_dup:
        return not candidate_dup
    current_len = len(str(current))
    candidate_len = len(str(candidate))
    if candidate_len != current_len:
        return candidate_len < current_len
    return str(candidate).lower() < str(current).lower()


def _dedupe_by_canonical(files: list[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(files, key=lambda item: str(item).lower()):
        key = canonical_stem(path.stem)
        if _prefer_candidate(result.get(key), path):
            result[key] = path
    return result


def discover_baseline_samples(*, samples_dir: Path = SAMPLES_DIR) -> list[SampleRecord]:
    records: list[SampleRecord] = []
    # Legacy: STEP files directly in _samples/
    for path in sorted(samples_dir.glob("*.stp"), key=lambda item: str(item).lower()):
        records.append(
            SampleRecord(
                name=path.stem,
                step_path=path,
                pdf_path=None,
                category="baseline",
            )
        )
    # New structure: STEP files one level deep inside category folders
    for category_dir in sorted(samples_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        if category_dir.name.lower() not in BASELINE_CATEGORY_FOLDERS:
            continue
        for path in sorted(category_dir.iterdir(), key=lambda item: str(item).lower()):
            if path.is_file() and path.suffix.lower() in STEP_EXTENSIONS:
                records.append(
                    SampleRecord(
                        name=path.stem,
                        step_path=path,
                        pdf_path=None,
                        category="baseline",
                    )
                )
    return records


def discover_real_samples(*, samples_dir: Path = SAMPLES_DIR) -> list[SampleRecord]:
    step_candidates = [
        path
        for path in samples_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in STEP_EXTENSIONS and _is_real_sample_path(path, samples_dir=samples_dir)
    ]
    pdf_candidates = [
        path
        for path in samples_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in PDF_EXTENSIONS and _is_real_sample_path(path, samples_dir=samples_dir)
    ]

    dedup_steps = _dedupe_by_canonical(step_candidates)
    dedup_pdfs = _dedupe_by_canonical(pdf_candidates)
    records: list[SampleRecord] = []
    for key in sorted(dedup_steps.keys()):
        step_path = dedup_steps[key]
        records.append(
            SampleRecord(
                name=display_stem(step_path.stem),
                step_path=step_path,
                pdf_path=dedup_pdfs.get(key),
                category="real",
            )
        )
    return records


def load_real_priority_names(*, manifest_path: Path = REAL_PRIORITY_MANIFEST_PATH) -> list[str]:
    if not manifest_path.exists():
        raise ValueError(f"Missing real-priority manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("samples")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Invalid real-priority manifest: {manifest_path}")

    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid real-priority entry in {manifest_path}: {entry!r}")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ValueError(f"Missing sample name in {manifest_path}: {entry!r}")
        if name in seen:
            raise ValueError(f"Duplicate real-priority sample '{name}' in {manifest_path}")
        seen.add(name)
        names.append(name)
    return names


def discover_real_priority_samples(
    *,
    samples_dir: Path = SAMPLES_DIR,
    manifest_path: Path = REAL_PRIORITY_MANIFEST_PATH,
) -> list[SampleRecord]:
    ordered_names = load_real_priority_names(manifest_path=manifest_path)
    real_samples = {record.name: record for record in discover_real_samples(samples_dir=samples_dir)}
    missing = [name for name in ordered_names if name not in real_samples]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Real-priority samples missing from catalog: {missing_text}")
    return [real_samples[name] for name in ordered_names]


def load_real20_names(*, manifest_path: Path = REAL20_MANIFEST_PATH) -> list[str]:
    """Load the fixed Real20 benchmark manifest."""
    if not manifest_path.exists():
        raise ValueError(f"Missing real20 manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("samples")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Invalid real20 manifest: {manifest_path}")

    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid real20 entry in {manifest_path}: {entry!r}")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ValueError(f"Missing sample name in {manifest_path}: {entry!r}")
        if name in seen:
            raise ValueError(f"Duplicate real20 sample '{name}' in {manifest_path}")
        seen.add(name)
        names.append(name)
    return names


def discover_real20_samples(
    *,
    samples_dir: Path = SAMPLES_DIR,
    manifest_path: Path = REAL20_MANIFEST_PATH,
) -> list[SampleRecord]:
    """Load the fixed 20-part real benchmark set in deterministic manifest order."""
    ordered_names = load_real20_names(manifest_path=manifest_path)
    real_samples = {record.name: record for record in discover_real_samples(samples_dir=samples_dir)}
    missing = [name for name in ordered_names if name not in real_samples]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Real20 samples missing from catalog: {missing_text}")
    return [real_samples[name] for name in ordered_names]


def resolve_sample_set(sample_set: str, *, samples_dir: Path = SAMPLES_DIR) -> list[SampleRecord]:
    normalized = str(sample_set or "").strip().lower() or "baseline"
    baseline = discover_baseline_samples(samples_dir=samples_dir)
    real = discover_real_samples(samples_dir=samples_dir)
    if normalized == "baseline":
        return baseline
    if normalized == "real":
        return real
    if normalized == "real_priority":
        return discover_real_priority_samples(samples_dir=samples_dir)
    if normalized == "real20":
        return discover_real20_samples(samples_dir=samples_dir)
    if normalized == "all":
        return baseline + real
    raise ValueError(f"Unsupported sample set: {sample_set}")
