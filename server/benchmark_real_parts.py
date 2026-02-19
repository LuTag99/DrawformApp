#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local benchmark against real manufacturing reference PDFs."""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from sample_catalog import resolve_sample_set

ROOT = Path(__file__).resolve().parent
STEP_TO_PDF = ROOT / "freecad" / "step_to_pdf.py"
FREECAD_DEFAULT_PYTHON = r"C:\Program Files\FreeCAD 1.0\bin\python.exe"
SUPPORTED_FORMATS = {"A3", "A2"}


def resolve_freecad_python() -> str:
    env_value = (os.getenv("FREECAD_PYTHON") or "").strip()
    if env_value and Path(env_value).exists():
        return env_value
    if Path(FREECAD_DEFAULT_PYTHON).exists():
        return FREECAD_DEFAULT_PYTHON
    found = shutil_which("python.exe") or shutil_which("python")
    return found or FREECAD_DEFAULT_PYTHON


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def page_size_label(width_mm: float, height_mm: float) -> str:
    if abs(width_mm - 420.0) <= 5.0 and abs(height_mm - 297.0) <= 5.0:
        return "A3"
    if abs(width_mm - 594.0) <= 8.0 and abs(height_mm - 420.0) <= 8.0:
        return "A2"
    return "OTHER"


def extract_pdf_metrics(pdf_path: Path):
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PyMuPDF fehlt. Installiere lokal: python -m pip install pymupdf"
        ) from exc

    doc = fitz.open(pdf_path)
    page = doc[0]
    width_mm = page.rect.width * 25.4 / 72.0
    height_mm = page.rect.height * 25.4 / 72.0
    raw = page.get_text("dict")
    spans = []
    text_lines = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            line_fragments = []
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if not text:
                    continue
                line_fragments.append(text)
                spans.append(float(span.get("size") or 0.0))
            if line_fragments:
                text_lines.append(" ".join(line_fragments))
    doc.close()

    text_blob = "\n".join(text_lines)
    median_size = statistics.median(spans) if spans else 0.0
    return {
        "sheet": page_size_label(width_mm, height_mm),
        "width_mm": width_mm,
        "height_mm": height_mm,
        "span_count": len(spans),
        "median_font_pt": float(median_size),
        "line_count": len(text_lines),
        "has_abwicklung": "abwicklung" in text_blob.lower(),
        "has_brand_text": "spie" in text_blob.lower(),
    }


def run_export(step_path: Path, output_pdf: Path, debug_dir: Path):
    cmd = [resolve_freecad_python(), str(STEP_TO_PDF), str(step_path), str(output_pdf)]
    env = os.environ.copy()
    env["DRAWFORM_DEBUG_DIR"] = str(debug_dir)
    completed = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"Export fehlgeschlagen fuer {step_path.name}: {detail}")


def evaluate_metrics(name: str, ref_metrics: dict, out_metrics: dict):
    issues = []
    if out_metrics["sheet"] not in SUPPORTED_FORMATS:
        issues.append(f"{name}: Ausgabeformat unerwartet ({out_metrics['sheet']})")
    if ref_metrics["has_abwicklung"] and not out_metrics["has_abwicklung"]:
        issues.append(f"{name}: Abwicklungsmarker fehlt im generierten PDF.")
    if out_metrics["has_brand_text"]:
        issues.append(f"{name}: Branding-Text erkannt (SPIE), neutraler Output erwartet.")

    min_font_pt = max(6.5, ref_metrics["median_font_pt"] * 0.50)
    if out_metrics["median_font_pt"] < min_font_pt:
        issues.append(
            f"{name}: Schrift zu klein ({out_metrics['median_font_pt']:.2f}pt < {min_font_pt:.2f}pt)."
        )

    min_lines = max(18, int(ref_metrics["line_count"] * 0.40))
    if out_metrics["line_count"] < min_lines:
        issues.append(
            f"{name}: Zu wenige Textzeilen ({out_metrics['line_count']} < {min_lines})."
        )
    return issues


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark generated PDFs against real local references.")
    parser.add_argument(
        "--sample-set",
        choices=("real", "all"),
        default="real",
        help="Sample set to benchmark (default: real).",
    )
    parser.add_argument(
        "--keep-pdfs",
        action="store_true",
        help="Keep generated benchmark PDFs in server/_debug/benchmark.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    samples = resolve_sample_set(args.sample_set)
    candidates = [sample for sample in samples if sample.category == "real" and sample.pdf_path]
    if not candidates:
        print("Keine realen STEP/PDF-Paare gefunden.")
        return 1

    benchmark_dir = ROOT / "_debug" / "benchmark"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    all_issues = []

    with tempfile.TemporaryDirectory() as temp_root:
        temp_dir = Path(temp_root)
        for sample in candidates:
            ref_pdf = sample.pdf_path
            out_pdf = (benchmark_dir if args.keep_pdfs else temp_dir) / f"{sample.name}_generated.pdf"
            run_export(sample.step_path, out_pdf, ROOT / "_debug")
            ref_metrics = extract_pdf_metrics(ref_pdf)
            out_metrics = extract_pdf_metrics(out_pdf)
            issues = evaluate_metrics(sample.name, ref_metrics, out_metrics)
            all_issues.extend(issues)
            print(
                f"{sample.name:52} | ref={ref_metrics['sheet']} {ref_metrics['median_font_pt']:.2f}pt | "
                f"gen={out_metrics['sheet']} {out_metrics['median_font_pt']:.2f}pt | "
                f"abwicklung={out_metrics['has_abwicklung']}"
            )

    if all_issues:
        print("\nBenchmark WARN/FAIL:")
        for issue in all_issues:
            print(f"- {issue}")
        return 1

    print("\nBenchmark OK: Alle realen Teile innerhalb der lokalen Zielkriterien.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
