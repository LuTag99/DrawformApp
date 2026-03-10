#!/usr/bin/env python
"""Build a reusable reference-learning corpus from real STEP/PDF pairs."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

import fitz  # type: ignore
import numpy as np

from benchmark_real_parts import run_export, resolve_freecad_python
from sample_catalog import SampleRecord, discover_real_samples

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "knowledge" / "reference_learning"
BENCHMARK_DIR = ROOT / "_debug" / "benchmark"
CONTACT_DIR = ROOT / "_debug" / "reference_learning"
FEATURE_SCRIPT = ROOT / "freecad" / "step_feature_probe.py"
GRID_COLS = 10
GRID_ROWS = 8
DARK_THRESHOLD = 245


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a durable reference-learning corpus from real STEP/PDF pairs."
    )
    parser.add_argument(
        "--refresh-exports",
        action="store_true",
        help="Re-export generated PDFs even if cached benchmark PDFs already exist.",
    )
    parser.add_argument(
        "--render-contact-sheets",
        action="store_true",
        help="Render side-by-side reference/generated contact sheets into server/_debug/reference_learning.",
    )
    return parser.parse_args()


def page_size_label(width_mm: float, height_mm: float) -> str:
    if abs(width_mm - 420.0) <= 5.0 and abs(height_mm - 297.0) <= 5.0:
        return "A3"
    if abs(width_mm - 594.0) <= 8.0 and abs(height_mm - 420.0) <= 8.0:
        return "A2"
    return "OTHER"


def mm_from_rect(rect: fitz.Rect) -> tuple[float, float]:
    return (rect.width * 25.4 / 72.0, rect.height * 25.4 / 72.0)


def is_dimension_like_text(text: str) -> bool:
    compact = "".join(str(text or "").strip().split())
    if not compact:
        return False
    if not any(ch.isdigit() for ch in compact):
        return False
    if compact.count(".") >= 2 and compact.count(",") == 0:
        return False
    allowed = set("0123456789-+.,xX/()[]<>~=:mMRrOD")
    expanded = compact.replace("mm", "m").replace("MM", "M")
    for ch in expanded:
        if ch.isdigit():
            continue
        if ch == "°" or ch == "Ø":
            continue
        if ch not in allowed:
            return False
    return True


def analyze_pdf(pdf_path: Path) -> dict:
    doc = fitz.open(pdf_path)
    page = doc[0]
    width_mm, height_mm = mm_from_rect(page.rect)
    raw = page.get_text("dict")
    spans: list[float] = []
    text_lines: list[str] = []
    dim_text_count = 0
    text_rects: list[fitz.Rect] = []
    for block in raw.get("blocks", []):
        bbox = block.get("bbox")
        if bbox:
            text_rects.append(fitz.Rect(bbox))
        for line in block.get("lines", []):
            fragments: list[str] = []
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if not text:
                    continue
                fragments.append(text)
                spans.append(float(span.get("size") or 0.0))
                if is_dimension_like_text(text):
                    dim_text_count += 1
            if fragments:
                text_lines.append(" ".join(fragments))

    drawings = page.get_drawings()
    draw_rects = [entry.get("rect") for entry in drawings if entry.get("rect")]
    all_rects = text_rects + draw_rects
    bbox_ratio = 0.0
    bbox_mm = None
    if all_rects:
        union = fitz.Rect(all_rects[0])
        for rect in all_rects[1:]:
            union.include_rect(rect)
        bbox_ratio = max(
            0.0,
            min(1.0, (union.width * union.height) / (page.rect.width * page.rect.height)),
        )
        bbox_mm = [
            round(value * 25.4 / 72.0, 2)
            for value in (union.x0, union.y0, union.x1, union.y1)
        ]

    target_width_px = 800
    zoom = target_width_px / page.rect.width
    pix = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False
    )
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = image < DARK_THRESHOLD
    ink_ratio = float(ink.mean())
    y_coords, x_coords = np.where(ink)
    raster_bbox_ratio = 0.0
    raster_bbox = None
    if len(x_coords):
        x0 = int(x_coords.min())
        x1 = int(x_coords.max())
        y0 = int(y_coords.min())
        y1 = int(y_coords.max())
        raster_bbox_ratio = ((x1 - x0 + 1) * (y1 - y0 + 1)) / float(
            image.shape[0] * image.shape[1]
        )
        raster_bbox = [x0, y0, x1, y1]

    grid: list[list[float]] = []
    height_px, width_px = image.shape
    for gy in range(GRID_ROWS):
        row: list[float] = []
        y0 = gy * height_px // GRID_ROWS
        y1 = (gy + 1) * height_px // GRID_ROWS
        for gx in range(GRID_COLS):
            x0 = gx * width_px // GRID_COLS
            x1 = (gx + 1) * width_px // GRID_COLS
            row.append(float(ink[y0:y1, x0:x1].mean()))
        grid.append(row)

    text_blob = "\n".join(text_lines).lower()
    doc.close()
    return {
        "pdf_path": str(pdf_path),
        "sheet_label": page_size_label(width_mm, height_mm),
        "sheet_mm": [round(width_mm, 2), round(height_mm, 2)],
        "span_count": len(spans),
        "median_font_pt": round(float(statistics.median(spans)) if spans else 0.0, 2),
        "line_count": len(text_lines),
        "dimension_like_text_count": dim_text_count,
        "drawing_count": len(drawings),
        "has_abwicklung": "abwicklung" in text_blob,
        "has_logo_placeholder": "spie" in text_blob,
        "bbox_ratio": round(bbox_ratio, 4),
        "bbox_mm": bbox_mm,
        "ink_ratio": round(ink_ratio, 4),
        "raster_bbox_ratio": round(raster_bbox_ratio, 4),
        "raster_bbox": raster_bbox,
        "occupancy_grid": grid,
    }


def compare_metrics(reference: dict, generated: dict) -> dict:
    reference_grid = np.array(reference["occupancy_grid"], dtype=float)
    generated_grid = np.array(generated["occupancy_grid"], dtype=float)
    occupancy_l1 = float(np.mean(np.abs(reference_grid - generated_grid)))

    def safe_ratio(baseline: float | int, candidate: float | int) -> float | None:
        if not baseline:
            return None
        return float(candidate) / float(baseline)

    font_ratio = safe_ratio(reference["median_font_pt"], generated["median_font_pt"])
    line_ratio = safe_ratio(reference["line_count"], generated["line_count"])
    dim_ratio = safe_ratio(
        reference["dimension_like_text_count"], generated["dimension_like_text_count"]
    )
    drawing_ratio = safe_ratio(reference["drawing_count"], generated["drawing_count"])
    flags: list[str] = []
    if reference["sheet_label"] != generated["sheet_label"]:
        flags.append("sheet_mismatch")
    if reference["has_abwicklung"] != generated["has_abwicklung"]:
        flags.append("abwicklung_mismatch")
    if font_ratio is not None and font_ratio < 0.65:
        flags.append("font_too_small")
    if dim_ratio is not None and dim_ratio < 0.55:
        flags.append("dimension_density_too_low")
    if occupancy_l1 > 0.04:
        flags.append("layout_diverges")
    return {
        "sheet_match": reference["sheet_label"] == generated["sheet_label"],
        "abwicklung_match": reference["has_abwicklung"] == generated["has_abwicklung"],
        "logo_placeholder_in_output": generated["has_logo_placeholder"],
        "median_font_ratio": round(font_ratio, 3) if font_ratio is not None else None,
        "line_ratio": round(line_ratio, 3) if line_ratio is not None else None,
        "dimension_text_ratio": round(dim_ratio, 3) if dim_ratio is not None else None,
        "drawing_ratio": round(drawing_ratio, 3) if drawing_ratio is not None else None,
        "bbox_ratio_delta": round(generated["bbox_ratio"] - reference["bbox_ratio"], 4),
        "raster_bbox_ratio_delta": round(
            generated["raster_bbox_ratio"] - reference["raster_bbox_ratio"], 4
        ),
        "ink_ratio_delta": round(generated["ink_ratio"] - reference["ink_ratio"], 4),
        "occupancy_l1": round(occupancy_l1, 4),
        "flags": flags,
    }


def probe_step(step_path: Path, *, freecad_python: str) -> dict:
    with tempfile.TemporaryDirectory() as temp_root:
        output_path = Path(temp_root) / "feature.json"
        completed = subprocess.run(
            [freecad_python, str(FEATURE_SCRIPT), str(step_path), str(output_path)],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not output_path.exists():
            return {
                "ok": False,
                "error": (completed.stderr or completed.stdout or "").strip(),
            }
        data = json.loads(output_path.read_text(encoding="utf-8"))
        return {
            "ok": bool(data.get("ok")),
            "bbox_mm": data.get("bbox_mm"),
            "is_flat": data.get("is_flat"),
            "flat_ratio": data.get("flat_ratio"),
            "hole_count": data.get("hole_count"),
            "hole_diameters_mm": data.get("hole_diameters_mm"),
            "is_sheet_metal_by_faces": data.get("is_sheet_metal_by_faces"),
            "measured_thickness_mm": data.get("measured_thickness_mm"),
            "bend_radius_mm": data.get("bend_radius_mm"),
            "thread_label": data.get("thread_label"),
            "flat_pattern_detected": bool(data.get("flat_pattern")),
        }


def render_contact_sheets(records: list[dict]) -> None:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow fehlt. Installiere lokal: python -m pip install pillow"
        ) from exc

    CONTACT_DIR.mkdir(parents=True, exist_ok=True)

    def render_thumb(pdf_path: Path, label: str, max_size: tuple[int, int]) -> Image.Image:
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        image.thumbnail(max_size)
        canvas = Image.new("RGB", (max_size[0], max_size[1] + 30), "white")
        x = (max_size[0] - image.width) // 2
        y = (max_size[1] - image.height) // 2
        canvas.paste(image, (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            [0, max_size[1], max_size[0] - 1, max_size[1] + 29],
            fill=(240, 240, 240),
            outline=(180, 180, 180),
        )
        draw.text((8, max_size[1] + 8), label, fill="black")
        doc.close()
        return canvas

    rows: list[tuple[Image.Image, Image.Image]] = []
    for index, record in enumerate(records, start=1):
        rows.append(
            (
                render_thumb(
                    Path(record["reference_pdf"]),
                    f"{index:02d} REF {record['name']}",
                    (520, 360),
                ),
                render_thumb(
                    Path(record["generated_pdf"]),
                    f"{index:02d} GEN {record['name']}",
                    (520, 360),
                ),
            )
        )

    chunk_size = 7
    cell_w = 540
    cell_h = 410
    for chunk_start in range(0, len(rows), chunk_size):
        chunk = rows[chunk_start : chunk_start + chunk_size]
        sheet = Image.new("RGB", (cell_w * 2, cell_h * len(chunk)), (248, 248, 248))
        for row_index, (reference_thumb, generated_thumb) in enumerate(chunk):
            y = row_index * cell_h
            sheet.paste(reference_thumb, (0, y))
            sheet.paste(generated_thumb, (cell_w, y))
        output_path = CONTACT_DIR / f"contact_sheet_{chunk_start // chunk_size + 1}.png"
        sheet.save(output_path)


def ensure_generated_pdf(
    sample: SampleRecord,
    *,
    output_pdf: Path,
    refresh_exports: bool,
) -> None:
    if output_pdf.exists() and not refresh_exports:
        return
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    run_export(sample.step_path, output_pdf, ROOT / "_debug")


def build_records(samples: list[SampleRecord], *, refresh_exports: bool) -> list[dict]:
    freecad_python = resolve_freecad_python()
    if not freecad_python:
        raise RuntimeError("FreeCAD python konnte nicht gefunden werden.")

    records: list[dict] = []
    for sample in samples:
        if not sample.pdf_path:
            continue
        generated_pdf = BENCHMARK_DIR / f"{sample.name}_generated.pdf"
        ensure_generated_pdf(sample, output_pdf=generated_pdf, refresh_exports=refresh_exports)
        reference_metrics = analyze_pdf(sample.pdf_path)
        generated_metrics = analyze_pdf(generated_pdf)
        comparison = compare_metrics(reference_metrics, generated_metrics)
        records.append(
            {
                "name": sample.name,
                "category": sample.category,
                "step_path": str(sample.step_path),
                "reference_pdf": str(sample.pdf_path),
                "generated_pdf": str(generated_pdf),
                "step_features": probe_step(sample.step_path, freecad_python=freecad_python),
                "reference_metrics": reference_metrics,
                "generated_metrics": generated_metrics,
                "comparison": comparison,
            }
        )
    return records


def build_rollup(records: list[dict]) -> dict:
    def metric_average(key: str) -> float | None:
        values = [
            record["comparison"][key]
            for record in records
            if record["comparison"].get(key) is not None
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    flag_counts: dict[str, int] = {}
    for record in records:
        for flag in record["comparison"]["flags"]:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    return {
        "sample_count": len(records),
        "sheet_mismatch_count": sum(1 for r in records if not r["comparison"]["sheet_match"]),
        "abwicklung_mismatch_count": sum(
            1 for r in records if not r["comparison"]["abwicklung_match"]
        ),
        "logo_placeholder_count": sum(
            1 for r in records if r["comparison"]["logo_placeholder_in_output"]
        ),
        "avg_font_ratio": metric_average("median_font_ratio"),
        "avg_line_ratio": metric_average("line_ratio"),
        "avg_dimension_ratio": metric_average("dimension_text_ratio"),
        "avg_drawing_ratio": metric_average("drawing_ratio"),
        "avg_occupancy_l1": metric_average("occupancy_l1"),
        "avg_raster_bbox_ratio_delta": metric_average("raster_bbox_ratio_delta"),
        "flag_counts": flag_counts,
    }


def write_summary(records: list[dict], rollup: dict, *, output_path: Path) -> None:
    sorted_by_divergence = sorted(
        records,
        key=lambda item: item["comparison"]["occupancy_l1"],
        reverse=True,
    )
    lines = [
        "# Musterzeichnungen als Lerninhalt",
        "",
        "Diese Datei wird aus den realen STEP/PDF-Paaren in `server/_samples` erzeugt.",
        "Sie dient als wiederverwendbarer Referenzbestand fuer Layout-, Bemaessungs- und Norm-Reviews.",
        "",
        "## Datensatz",
        f"- Teile gesamt: {rollup['sample_count']}",
        f"- Blattformat-Mismatches: {rollup['sheet_mismatch_count']}",
        f"- Abwicklungs-Mismatches: {rollup['abwicklung_mismatch_count']}",
        f"- SPIE-/Logo-Platzhalterfunde im Output: {rollup['logo_placeholder_count']}",
        f"- Durchschnitt Font-Ratio: {rollup['avg_font_ratio']}",
        f"- Durchschnitt Dimensions-Ratio: {rollup['avg_dimension_ratio']}",
        f"- Durchschnitt Layout-Divergenz (occupancy L1): {rollup['avg_occupancy_l1']}",
        "",
        "## Hauefigste Abweichungsflags",
    ]
    for flag, count in sorted(
        rollup["flag_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"- `{flag}`: {count}")
    lines.extend(
        [
            "",
            "## Teile mit der groessten Layout-Divergenz",
            "| Teil | Flat | Lochzahl | Dicke mm | Font-Ratio | Dim-Ratio | Layout-L1 | Flags |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for record in sorted_by_divergence[:12]:
        step = record["step_features"]
        cmp = record["comparison"]
        lines.append(
            "| {name} | {flat} | {holes} | {thick} | {font} | {dim} | {occ} | {flags} |".format(
                name=record["name"],
                flat=step.get("is_flat"),
                holes=step.get("hole_count"),
                thick=step.get("measured_thickness_mm"),
                font=cmp.get("median_font_ratio"),
                dim=cmp.get("dimension_text_ratio"),
                occ=cmp.get("occupancy_l1"),
                flags=", ".join(cmp.get("flags") or []),
            )
        )
    lines.extend(
        [
            "",
            "## Nutzung",
            "1. `python server/build_reference_learning.py --refresh-exports`",
            "2. Ergebnisse in `server/knowledge/reference_learning/reference_drawings_index.json` pruefen.",
            "3. Visuelle Gegenpruefung optional mit `--render-contact-sheets` in `server/_debug/reference_learning`.",
            "4. Auffaellige Teile gezielt fuer Planner/Builder/Critic-Iterationen priorisieren.",
            "",
            "## Grenzen",
            "- Die PDF-Metriken messen Layout, Textdichte, Blattnutzung und grobe Struktur.",
            "- Sie ersetzen keine echte Konstrukteursbewertung von Bezugslogik, falschen Massen oder Normdetails.",
            "- Die Musterzeichnungen sind deshalb Lerninhalt und Referenzbasis, aber kein alleiniger Freigabeautomatismus.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    samples = discover_real_samples()
    if not samples:
        raise RuntimeError("Keine realen STEP/PDF-Paare gefunden.")
    records = build_records(samples, refresh_exports=args.refresh_exports)
    rollup = build_rollup(records)
    (OUTPUT_DIR / "reference_drawings_index.json").write_text(
        json.dumps({"rollup": rollup, "records": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_summary(
        records,
        rollup,
        output_path=OUTPUT_DIR / "reference_drawings_summary.md",
    )
    if args.render_contact_sheets:
        render_contact_sheets(records)
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "sample_count": rollup["sample_count"],
                "flag_counts": rollup["flag_counts"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
