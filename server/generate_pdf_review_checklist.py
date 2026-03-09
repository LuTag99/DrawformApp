#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate a manual PDF review checklist from debug reports."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEBUG_DIR = ROOT / "_debug"
OUTPUT_PATH = DEBUG_DIR / "PDF_REVIEW_CHECKLIST.md"

SAMPLES = [
    "complex_bracket",
    "flanged_manifold",
    "stepped_shaft",
    "u_channel_assembly",
    "mounting_panel_complex",
]


def load_report(sample_name: str):
    report_path = DEBUG_DIR / f"{sample_name}_report.json"
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def line_for_sample(sample_name: str) -> str:
    report = load_report(sample_name)
    pdf_path = f"server/_debug/{sample_name}_sample.pdf"
    if report is None:
        return f"| [ ] | `{sample_name}` | `{pdf_path}` | n/a | n/a | n/a | report fehlt |"

    det = report.get("detection", {})
    features = report.get("features", {})
    quality = report.get("quality", {})
    conf = float(det.get("confidence") or 0.0)
    axis = det.get("longest_axis") or "?"
    holes = int(features.get("hole_count") or 0)
    overflow = (quality.get("overflow_mm") or {}).get("max", "n/a")
    note = []
    if not quality.get("fits_inside_drawing_area", False):
        note.append("clipping")
    if quality.get("scale_reduction_needed", False):
        note.append("scale_reduction")
    if conf < 0.1:
        note.append("low_conf")
    note_text = ", ".join(note) if note else "ok"

    return (
        f"| [ ] | `{sample_name}` | `{pdf_path}` | "
        f"{axis} / {conf:.2f} | {holes} | {overflow} | {note_text} |"
    )


def build_markdown() -> str:
    lines = [
        "# PDF Review Checklist (Complex Samples)",
        "",
        "Manuelle Sichtpruefung vor Freigabe:",
        "1. Ansichten korrekt orientiert (Top/Front/Left).",
        "2. Bemaessung lesbar und ohne Ueberlagerung.",
        "3. Titelblock/Felder korrekt.",
        "4. Keine abgeschnittenen Geometrien.",
        "",
        "| Done | Sample | PDF | Axis/Conf | Holes | MaxOverflow(mm) | Notes |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    lines.extend(line_for_sample(name) for name in SAMPLES)
    lines.append("")
    lines.append("Hinweis: Hake `Done` erst nach visueller PDF-Pruefung ab.")
    return "\n".join(lines) + "\n"


def main() -> int:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(build_markdown(), encoding="utf-8")
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
