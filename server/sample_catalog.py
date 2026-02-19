#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sample catalog utilities for baseline and real-world regression sets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent / "_samples"
REAL_SAMPLE_FOLDERS = {"milling parts", "sheetmetals"}
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
    return rel.parts[0].lower() in REAL_SAMPLE_FOLDERS


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
    for path in sorted(samples_dir.glob("*.stp"), key=lambda item: str(item).lower()):
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


def resolve_sample_set(sample_set: str, *, samples_dir: Path = SAMPLES_DIR) -> list[SampleRecord]:
    normalized = str(sample_set or "").strip().lower() or "baseline"
    baseline = discover_baseline_samples(samples_dir=samples_dir)
    real = discover_real_samples(samples_dir=samples_dir)
    if normalized == "baseline":
        return baseline
    if normalized == "real":
        return real
    if normalized == "all":
        return baseline + real
    raise ValueError(f"Unsupported sample set: {sample_set}")
