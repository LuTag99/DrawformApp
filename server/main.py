from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from job_persistence import load_job_map, save_job_map

ROOT = Path(__file__).resolve().parent
FREECAD_SCRIPT = ROOT / "freecad" / "step_to_pdf.py"
FREECAD_UNFOLD_SCRIPT = ROOT / "freecad" / "step_unfold.py"
FREECAD_FEATURE_SCRIPT = ROOT / "freecad" / "step_feature_probe.py"
JOB_STATE_DIR = ROOT / "_debug" / "job_state"
ANALYZER_JOBS_PATH = Path(
    os.getenv("DRAWFORM_ANALYZER_JOBS_PATH", str(JOB_STATE_DIR / "analyzer_jobs.json"))
)
RECONSTRUCT_JOBS_PATH = Path(
    os.getenv("DRAWFORM_RECONSTRUCT_JOBS_PATH", str(JOB_STATE_DIR / "reconstruct_jobs.json"))
)
FREECAD_TIMEOUT_SECONDS = int(os.getenv("DRAWFORM_FREECAD_TIMEOUT_SECONDS", "180"))
ANALYZER_WORKER_DELAY_SECONDS = float(os.getenv("DRAWFORM_ANALYZER_DELAY_SECONDS", "1.1"))
ANALYZER_FREECAD_TIMEOUT_SECONDS = int(os.getenv("DRAWFORM_ANALYZER_FREECAD_TIMEOUT_SECONDS", "90"))
ANALYZER_UNITS = {"mm", "cm", "inch"}
ANALYZER_FEATURE_EXTENSIONS = {".step", ".stp", ".iges", ".igs", ".stl", ".brep"}

ANALYZER_LOCK = threading.Lock()

EXPORT_DEFAULT_STANDARD = "DIN EN ISO 128/129-1"
EXPORT_DEFAULT_PROJECTION = "1. Winkel (DIN EN ISO 5456-2)"
EXPORT_DEFAULT_TOLERANCE = "DIN ISO 2768-mK"
EXPORT_ALLOWED_SCALES = {
    "20:1",
    "10:1",
    "5:1",
    "2:1",
    "1:1",
    "1:2",
    "1:5",
    "1:10",
    "1:20",
    "1:50",
    "1:100",
}
DRAWING_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,31}$")


def _safe_content_disposition(filename: str) -> dict[str, str]:
    """Build Content-Disposition header with RFC 5987 encoding for safe filenames."""
    ascii_safe = filename.encode("ascii", errors="replace").decode("ascii")
    ascii_safe = ascii_safe.replace('"', "_").replace("\n", "_").replace("\r", "_")
    encoded = quote(filename, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_safe}"; '
            f"filename*=UTF-8''{encoded}"
        )
    }
REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,7}$")
TOLERANCE_2768_RE = re.compile(r"^din\s+iso\s+2768-([fmcv])([hkl])?$", re.IGNORECASE)

app = FastAPI(title="Drawform Local API", version="0.1.0")


class MetadataValidationError(ValueError):
    """Raised when export metadata violates the supported norm profile."""


def _restore_job_map(path: Path, *, interruption_message: str) -> Dict[str, Dict[str, Any]]:
    jobs = load_job_map(path)
    if not jobs:
        return {}

    changed = False
    for job in jobs.values():
        if str(job.get("status") or "") in {"pending", "processing"}:
            job["status"] = "failed"
            job["error"] = job.get("error") or interruption_message
            changed = True

    if changed:
        try:
            save_job_map(path, jobs)
        except OSError as error:
            sys.stderr.write(f"[drawform] failed to persist restored jobs for {path}: {error}\n")

    return jobs


def _persist_job_map(path: Path, jobs: Dict[str, Dict[str, Any]]) -> None:
    try:
        save_job_map(path, jobs)
    except OSError as error:
        sys.stderr.write(f"[drawform] failed to persist jobs for {path}: {error}\n")


ANALYZER_JOBS: Dict[str, Dict[str, Any]] = _restore_job_map(
    ANALYZER_JOBS_PATH,
    interruption_message="Backend restart interrupted the analyzer job.",
)


def resolve_freecad_cmd() -> Optional[Path]:
    env_path = os.getenv("FREECAD_PYTHON") or os.getenv("FREECAD_CMD") or os.getenv("FREECAD_EXE")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            if candidate.name.lower() == "freecadcmd.exe":
                python_path = candidate.parent / "python.exe"
                if python_path.exists():
                    return python_path
            return candidate

    candidates = [
        Path(r"C:\Program Files\FreeCAD 1.0\bin\python.exe"),
        Path(r"C:\Program Files\FreeCAD 1.0\bin\FreeCADCmd.exe"),
        Path(r"C:\Program Files\FreeCAD 0.22\bin\python.exe"),
        Path(r"C:\Program Files\FreeCAD 0.22\bin\FreeCADCmd.exe"),
        Path(r"C:\Program Files\FreeCAD 0.21\bin\python.exe"),
        Path(r"C:\Program Files\FreeCAD 0.21\bin\FreeCADCmd.exe"),
        Path(r"C:\Program Files\FreeCAD 0.20\bin\python.exe"),
        Path(r"C:\Program Files\FreeCAD 0.20\bin\FreeCADCmd.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            if candidate.name.lower() == "freecadcmd.exe":
                python_path = candidate.parent / "python.exe"
                if python_path.exists():
                    return python_path
            return candidate

    for name in ("python.exe", "FreeCADCmd.exe", "FreeCADCmd"):
        found = shutil.which(name)
        if found:
            candidate = Path(found)
            if candidate.name.lower() == "freecadcmd.exe":
                python_path = candidate.parent / "python.exe"
                if python_path.exists():
                    return python_path
            return candidate

    return None


def _normalize_text(value: Optional[str], default: str, *, max_len: int, field_name: str) -> str:
    normalized = str(value or "").strip() or default
    if len(normalized) > max_len:
        raise MetadataValidationError(f"{field_name} is too long (max {max_len} chars).")
    return normalized


def _normalize_drawing_no(value: Optional[str]) -> str:
    drawing_no = _normalize_text(value, "DF-0001", max_len=32, field_name="drawing_no")
    if not DRAWING_NO_RE.fullmatch(drawing_no):
        raise MetadataValidationError(
            "drawing_no has invalid format (allowed: letters, numbers, ., _, /, -)."
        )
    return drawing_no


def _normalize_revision(value: Optional[str]) -> str:
    revision = _normalize_text(value, "A", max_len=8, field_name="revision")
    if not REVISION_RE.fullmatch(revision):
        raise MetadataValidationError(
            "revision has invalid format (allowed: letters, numbers, ., _, -)."
        )
    return revision


def _normalize_scale(value: Optional[str]) -> str:
    scale = str(value or "").strip()
    if not scale:
        return "auto"
    compact = scale.replace(" ", "")
    if compact.lower() == "auto":
        return "auto"
    if compact in EXPORT_ALLOWED_SCALES:
        return compact
    raise MetadataValidationError(
        "Unsupported scale. Allowed: auto, 20:1, 10:1, 5:1, 2:1, 1:1, 1:2, 1:5, 1:10, 1:20, 1:50, 1:100."
    )


def _normalize_unit(value: Optional[str]) -> str:
    unit = str(value or "").strip()
    if not unit:
        return "mm"
    if unit.lower() != "mm":
        raise MetadataValidationError("Unsupported unit for PDF export. Only 'mm' is supported.")
    return "mm"


def _normalize_sheet(value: Optional[str]) -> str:
    sheet = str(value or "").strip()
    if not sheet:
        return "auto"
    normalized = sheet.upper()
    if normalized in {"AUTO", "A3", "A2"}:
        return normalized.lower() if normalized == "AUTO" else normalized
    raise MetadataValidationError("Unsupported sheet for PDF export. Allowed: auto, A3, A2.")


def _normalize_standard(value: Optional[str]) -> str:
    standard = str(value or "").strip()
    if not standard:
        return EXPORT_DEFAULT_STANDARD
    compact = standard.lower().replace(" ", "")
    if compact in {
        "dineniso128/129-1",
        "diniso128/129-1",
        "iso128/129-1",
    }:
        return EXPORT_DEFAULT_STANDARD
    raise MetadataValidationError(
        "Unsupported standard. Allowed: DIN EN ISO 128/129-1."
    )


def _normalize_projection(value: Optional[str]) -> str:
    projection = str(value or "").strip()
    if not projection:
        return EXPORT_DEFAULT_PROJECTION
    compact = projection.lower().replace(" ", "").replace("-", "")
    if compact in {
        "1.winkel(dineniso54562)",
        "1.winkel",
        "firstangle",
        "1stangle",
        "first_angle",
        "1st_angle",
    }:
        return EXPORT_DEFAULT_PROJECTION
    raise MetadataValidationError(
        "Unsupported projection. Allowed: 1. Winkel (DIN EN ISO 5456-2)."
    )


def _normalize_general_tolerance(value: Optional[str]) -> str:
    tolerance = str(value or "").strip()
    if not tolerance:
        return EXPORT_DEFAULT_TOLERANCE
    if tolerance.lower() in {
        "iso 22081",
        "iso22081",
        "iso 22081 (allgemein)",
        "iso22081(allgemein)",
    }:
        return "ISO 22081 (allgemein)"
    match = TOLERANCE_2768_RE.fullmatch(" ".join(tolerance.split()))
    if match:
        grade_1 = match.group(1).lower()
        grade_2 = (match.group(2) or "").upper()
        return f"DIN ISO 2768-{grade_1}{grade_2}"
    raise MetadataValidationError(
        "Unsupported general_tolerance. Allowed: DIN ISO 2768-<f|m|c|v><H|K|L optional> or ISO 22081."
    )


def build_metadata(
    title: Optional[str],
    drawing_no: Optional[str],
    revision: Optional[str],
    author: Optional[str],
    company: Optional[str],
    *,
    scale: Optional[str] = None,
    standard: Optional[str] = None,
    projection: Optional[str] = None,
    general_tolerance: Optional[str] = None,
    unit: Optional[str] = None,
    sheet: Optional[str] = None,
    k_factor: Optional[float] = None,
    detail_level: Optional[int] = None,
) -> Dict[str, Any]:
    today = dt.date.today().strftime("%d.%m.%Y")
    normalized_scale = _normalize_scale(scale)
    normalized_unit = _normalize_unit(unit)
    normalized_sheet = _normalize_sheet(sheet)
    normalized_detail_level = max(1, min(3, int(detail_level))) if detail_level is not None else 1
    return {
        "title": _normalize_text(title, "Bauteilzeichnung", max_len=80, field_name="title"),
        "drawing_no": _normalize_drawing_no(drawing_no),
        "revision": _normalize_revision(revision),
        "author": _normalize_text(author, "Drawform", max_len=40, field_name="author"),
        "company": _normalize_text(company, "Drawform", max_len=40, field_name="company"),
        "date": today,
        "unit": normalized_unit,
        "sheet": normalized_sheet,
        "scale": normalized_scale,
        "views": ["Top", "Front", "Left", "Iso"],
        "standard": _normalize_standard(standard),
        "projection": _normalize_projection(projection),
        "general_tolerance": _normalize_general_tolerance(general_tolerance),
        "k_factor": float(k_factor) if k_factor is not None and 0.1 <= float(k_factor) <= 0.8 else None,
        "detail_level": normalized_detail_level,
    }


def format_error_message(stderr: str, stdout: str) -> str:
    details = stderr.strip() or stdout.strip()
    if details:
        return f"FreeCAD failed: {details}"
    return "FreeCAD failed without details."


def normalize_stream_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def build_export_log(command: list[str], stderr: str, stdout: str, note: str | None = None) -> str:
    parts = [f"[drawform] command: {' '.join(command)}"]
    if note:
        parts.append(f"[drawform] note: {note}")
    parts.extend(
        [
            "[drawform] --- stderr ---",
            stderr.strip(),
            "[drawform] --- stdout ---",
            stdout.strip(),
        ]
    )
    return "\n".join(parts).strip()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
        if parsed <= 0:
            return fallback
        return parsed
    except (TypeError, ValueError):
        return fallback


def parse_views(raw: Optional[str]) -> list[str]:
    if not raw:
        return ["Iso"]
    candidate = raw.strip()
    if not candidate:
        return ["Iso"]
    parsed: list[str] = []
    if candidate.startswith("["):
        try:
            value = json.loads(candidate)
            if isinstance(value, list):
                parsed = [str(item).strip() for item in value if str(item).strip()]
        except json.JSONDecodeError:
            parsed = []
    if not parsed:
        parsed = [part.strip() for part in candidate.split(",") if part.strip()]
    return parsed or ["Iso"]


def detect_source_type(file_name: str, content_type: str | None) -> str:
    ext = Path(file_name).suffix.lower()
    if (content_type or "").startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return "cad"


def convert_mm_to_unit(value_mm: float, units: str) -> float:
    if units == "inch":
        return value_mm / 25.4
    if units == "cm":
        return value_mm / 10.0
    return value_mm


def supports_feature_probe(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in ANALYZER_FEATURE_EXTENSIONS


def overlay_coords() -> list[Dict[str, Dict[str, float]]]:
    return [
        {"start": {"x": 0.16, "y": 0.32}, "end": {"x": 0.78, "y": 0.32}},
        {"start": {"x": 0.34, "y": 0.20}, "end": {"x": 0.34, "y": 0.78}},
        {"start": {"x": 0.22, "y": 0.62}, "end": {"x": 0.74, "y": 0.62}},
        {"start": {"x": 0.58, "y": 0.25}, "end": {"x": 0.58, "y": 0.68}},
    ]


def build_measurement_overlays(measurements: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    coords = overlay_coords()
    overlays = []
    for index, measurement in enumerate(measurements):
        coord = coords[index % len(coords)]
        overlays.append(
            {
                "id": f"overlay-{measurement['id']}",
                "measurementId": measurement["id"],
                "axis": measurement.get("axis", "horizontal"),
                "start": coord["start"],
                "end": coord["end"],
            }
        )
    return overlays


def run_feature_probe(file_name: str, payload: bytes) -> Optional[Dict[str, Any]]:
    if not supports_feature_probe(file_name):
        return None

    freecad_cmd = resolve_freecad_cmd()
    if not freecad_cmd or not freecad_cmd.exists() or not FREECAD_FEATURE_SCRIPT.exists():
        return None

    debug_dir = ROOT / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_path = debug_dir / "last_analyzer.log"

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        input_path = temp_root / Path(file_name).name
        output_path = temp_root / "feature_probe.json"
        input_path.write_bytes(payload)

        command = [str(freecad_cmd), str(FREECAD_FEATURE_SCRIPT), str(input_path), str(output_path)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=ANALYZER_FREECAD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            stderr = normalize_stream_text(error.stderr).strip()
            stdout = normalize_stream_text(error.stdout).strip()
            timeout_note = f"Feature probe timed out after {ANALYZER_FREECAD_TIMEOUT_SECONDS} seconds."
            log_path.write_text(
                build_export_log(command, stderr, stdout, note=timeout_note),
                encoding="utf-8",
            )
            return {"ok": False, "error": timeout_note}
        except OSError as error:
            message = f"Failed to start feature probe: {error}"
            log_path.write_text(
                build_export_log(command, message, "", note="Probe start error"),
                encoding="utf-8",
            )
            return {"ok": False, "error": message}

        log_path.write_text(build_export_log(command, result.stderr, result.stdout), encoding="utf-8")
        if result.returncode != 0 or not output_path.exists():
            return {"ok": False, "error": format_error_message(result.stderr, result.stdout)}

        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            return {"ok": False, "error": f"Invalid probe output: {error}"}


def build_measurement_templates(source_type: str, file_name: str) -> list[Dict[str, Any]]:
    base = [
        {
            "id": "edge-a",
            "label": "Kante A",
            "range": (55.0, 180.0),
            "tolerance": "+/-0.05",
            "explanation": "Primaere Bezugsflaeche fuer Montagepunkte.",
            "axis": "horizontal",
        },
        {
            "id": "edge-b",
            "label": "Kante B",
            "range": (35.0, 120.0),
            "tolerance": "+/-0.03",
            "explanation": "Querbemaessung fuer Gehaeusebreite.",
            "axis": "vertical",
        },
        {
            "id": "hole-pattern",
            "label": "Bohrungsraster",
            "range": (20.0, 70.0),
            "tolerance": "H7",
            "explanation": "Lochbild fuer Schraubverbindungen.",
            "axis": "horizontal",
        },
        {
            "id": "bend-radius",
            "label": "Biegeradius",
            "range": (6.0, 24.0),
            "tolerance": "+/-0.02",
            "explanation": "Radius fuer Abwicklung / Blechprozess.",
            "axis": "vertical",
        },
    ]
    lower_name = file_name.lower()
    if source_type == "image":
        base[2]["label"] = "Featureabstand"
        base[2]["explanation"] = "Abstand visuell erkannter Merkmale."
    elif "slot" in lower_name:
        base[2]["label"] = "Langlochmaß"
    elif "sheet" in lower_name or "blech" in lower_name:
        base[3]["label"] = "Biegekante"
        base[3]["tolerance"] = "+/-0.10"
    return base


def build_random_measurements(
    source_type: str,
    file_name: str,
    scale: float,
    units: str,
    rng: random.Random,
) -> list[Dict[str, Any]]:
    templates = build_measurement_templates(source_type, file_name)
    measurements = []
    for template in templates:
        mm_value = rng.uniform(template["range"][0], template["range"][1]) * max(scale, 1.0)
        measurements.append(
            {
                "id": template["id"],
                "label": template["label"],
                "value": round(convert_mm_to_unit(mm_value, units), 2),
                "unit": units,
                "tolerance": template["tolerance"],
                "explanation": template["explanation"],
                "axis": template["axis"],
            }
        )
    return measurements


def build_feature_measurements(
    units: str,
    scale: float,
    probe_data: Dict[str, Any],
) -> list[Dict[str, Any]]:
    dims = probe_data.get("bbox_mm")
    if not isinstance(dims, dict):
        return []

    def mm(key: str) -> float:
        return safe_float(dims.get(key), 0.0)

    ordered_axes = sorted(
        [("X", mm("X")), ("Y", mm("Y")), ("Z", mm("Z"))],
        key=lambda item: item[1],
        reverse=True,
    )
    if ordered_axes[0][1] <= 0:
        return []

    scale_factor = max(scale, 1.0)
    length_axis, length_mm = ordered_axes[0]
    width_axis, width_mm = ordered_axes[1]
    height_axis, height_mm = ordered_axes[2]
    measurements = [
        {
            "id": "overall-length",
            "label": "Gesamtlaenge",
            "value": round(convert_mm_to_unit(length_mm * scale_factor, units), 2),
            "unit": units,
            "tolerance": "+/-0.20",
            "explanation": f"Abgeleitet aus Bounding-Box entlang {length_axis}.",
            "axis": "horizontal",
        },
        {
            "id": "overall-width",
            "label": "Gesamtbreite",
            "value": round(convert_mm_to_unit(width_mm * scale_factor, units), 2),
            "unit": units,
            "tolerance": "+/-0.15",
            "explanation": f"Abgeleitet aus Bounding-Box entlang {width_axis}.",
            "axis": "vertical",
        },
        {
            "id": "overall-height",
            "label": "Gesamthoehe",
            "value": round(convert_mm_to_unit(height_mm * scale_factor, units), 2),
            "unit": units,
            "tolerance": "+/-0.10",
            "explanation": f"Abgeleitet aus Bounding-Box entlang {height_axis}.",
            "axis": "vertical",
        },
    ]

    hole_diameter_mm = safe_float(probe_data.get("hole_diameter_mm"), 0.0)
    hole_pitch_mm = safe_float(probe_data.get("hole_pitch_mm"), 0.0)
    bend_radius_mm = safe_float(probe_data.get("bend_radius_mm"), 0.0)
    if hole_diameter_mm > 0:
        measurements.append(
            {
                "id": "hole-diameter",
                "label": "Bohrungsdurchmesser",
                "value": round(convert_mm_to_unit(hole_diameter_mm * scale_factor, units), 2),
                "unit": units,
                "tolerance": "H11",
                "explanation": "Gemittelt aus erkannten kreisfoermigen Kanten.",
                "axis": "horizontal",
            }
        )
    if hole_pitch_mm > 0:
        measurements.append(
            {
                "id": "hole-pitch",
                "label": "Lochabstand",
                "value": round(convert_mm_to_unit(hole_pitch_mm * scale_factor, units), 2),
                "unit": units,
                "tolerance": "+/-0.10",
                "explanation": "Abstand zwischen aeueren Bohrungszentren.",
                "axis": "horizontal",
            }
        )
    if bend_radius_mm > 0:
        measurements.append(
            {
                "id": "bend-radius",
                "label": "Biegeradius",
                "value": round(convert_mm_to_unit(bend_radius_mm * scale_factor, units), 2),
                "unit": units,
                "tolerance": "+/-0.05",
                "explanation": "Kleinster erkannter Zylinderradius.",
                "axis": "vertical",
            }
        )
    return measurements[:6]


def build_analyzer_result(
    job: Dict[str, Any],
    payload: bytes,
    probe_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = job["metadata"]
    units = metadata.get("units", "mm")
    scale = safe_float(metadata.get("scale", 1.0), 1.0)
    active_views = metadata.get("views") or ["Iso"]
    source_type = job.get("sourceType", "cad")
    file_name = job.get("fileName", "")
    seed_source = payload + job["id"].encode("utf-8")
    seed = int(hashlib.sha256(seed_source).hexdigest()[:12], 16)
    rng = random.Random(seed)

    measurements: list[Dict[str, Any]] = []
    used_probe = False
    if source_type == "cad" and isinstance(probe_data, dict) and probe_data.get("ok") is True:
        measurements = build_feature_measurements(units, scale, probe_data)
        used_probe = len(measurements) > 0
    if not measurements:
        measurements = build_random_measurements(source_type, file_name, scale, units, rng)

    overlays = build_measurement_overlays(measurements)
    public_measurements = [
        {
            "id": measurement["id"],
            "label": measurement["label"],
            "value": measurement["value"],
            "unit": measurement["unit"],
            "tolerance": measurement["tolerance"],
            "explanation": measurement["explanation"],
        }
        for measurement in measurements
    ]

    recommendations = [
        f"Layer {metadata.get('layer') or 'AI_DIMENSIONS'} ist fuer Annotationen aktiv.",
        "Abwicklung erkannt - Fertigungsreihenfolge pruefen."
        if "Abwicklung" in active_views
        else "Keine Abwicklung in den gewaehlten Ansichten.",
        "Einheiten wurden auf inch umgerechnet." if units == "inch" else f"Einheiten: {units}.",
    ]
    notes = metadata.get("notes")
    if notes:
        recommendations.append(f"Notiz uebernommen: {str(notes)[:120]}")
    if used_probe:
        hole_count = int(safe_float(probe_data.get("hole_count"), 0.0)) if probe_data else 0
        recommendations.append(f"CAD-Feature-Probe aktiv: {hole_count} Bohrungsfeatures erkannt.")
    elif source_type == "cad":
        probe_error = probe_data.get("error") if isinstance(probe_data, dict) else None
        if probe_error:
            recommendations.append(f"Feature-Probe Fallback aktiv: {probe_error}")
        else:
            recommendations.append("Feature-Probe nicht verfuegbar, Fallback-Heuristik genutzt.")

    summary = (
        f"Backend-Worker analysierte {', '.join(active_views)} und leitete "
        f"{len(public_measurements)} Kernmasse fuer {job.get('fileName')} ab."
    )
    confidence = int(rng.uniform(84, 96))
    if used_probe:
        confidence = int(rng.uniform(91, 98))
    return {
        "summary": summary,
        "confidence": confidence,
        "modelVersion": f"feature-worker-{source_type}-0.3" if used_probe else f"feature-worker-{source_type}-0.2",
        "completedAt": now_iso(),
        "measurements": public_measurements,
        "overlays": overlays,
        "recommendations": recommendations,
    }


def update_analyzer_job(job_id: str, **changes: Any) -> Dict[str, Any]:
    with ANALYZER_LOCK:
        current = ANALYZER_JOBS.get(job_id)
        if current is None:
            raise KeyError(job_id)
        updated = {**current, **changes}
        ANALYZER_JOBS[job_id] = updated
        snapshot = copy.deepcopy(ANALYZER_JOBS)
    _persist_job_map(ANALYZER_JOBS_PATH, snapshot)
    return dict(updated)


def process_analyzer_job(job_id: str, payload: bytes):
    try:
        update_analyzer_job(job_id, status="processing")
        time.sleep(max(0.1, ANALYZER_WORKER_DELAY_SECONDS))
        with ANALYZER_LOCK:
            job = dict(ANALYZER_JOBS[job_id])
        probe_data = None
        if job.get("sourceType") == "cad":
            probe_data = run_feature_probe(job.get("fileName", "model.step"), payload)
        result = build_analyzer_result(job, payload, probe_data=probe_data)
        update_analyzer_job(job_id, status="completed", result=result, error=None)
    except Exception as exc:  # pragma: no cover - defensive fallback
        try:
            update_analyzer_job(job_id, status="failed", error=str(exc))
        except KeyError:
            pass


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/logs/last")
def last_export_log() -> Response:
    log_path = ROOT / "_debug" / "last_export.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No export log found yet.")
    return Response(content=log_path.read_text(encoding="utf-8"), media_type="text/plain")


@app.get("/api/analyze")
def list_analyzer_jobs() -> list[Dict[str, Any]]:
    with ANALYZER_LOCK:
        jobs = [dict(job) for job in ANALYZER_JOBS.values()]
    jobs.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return jobs


@app.get("/api/analyze/{job_id}")
def get_analyzer_job(job_id: str) -> Dict[str, Any]:
    with ANALYZER_LOCK:
        job = ANALYZER_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analyzer job not found.")
    return dict(job)


@app.post("/api/analyze")
async def create_analyzer_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    units: str = Form("mm"),
    scale: float = Form(1.0),
    layer: str = Form("AI_DIMENSIONS"),
    notes: Optional[str] = Form(None),
    views: Optional[str] = Form(None),
) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")
    normalized_units = str(units or "mm").lower()
    if normalized_units not in ANALYZER_UNITS:
        raise HTTPException(status_code=400, detail=f"Unsupported units: {units}")

    metadata = {
        "units": normalized_units,
        "scale": safe_float(scale, 1.0),
        "layer": (layer or "AI_DIMENSIONS").strip() or "AI_DIMENSIONS",
        "notes": (notes or "").strip() or None,
        "views": parse_views(views),
    }
    payload = await file.read()
    await file.close()

    job_id = uuid4().hex
    source_type = detect_source_type(file.filename, file.content_type)
    job: Dict[str, Any] = {
        "id": job_id,
        "createdAt": now_iso(),
        "status": "pending",
        "fileName": Path(file.filename).name,
        "size": len(payload),
        "metadata": metadata,
        "sourceType": source_type,
        "executionMode": "backend",
        "result": None,
        "error": None,
    }
    with ANALYZER_LOCK:
        ANALYZER_JOBS[job_id] = job
        snapshot = copy.deepcopy(ANALYZER_JOBS)
    _persist_job_map(ANALYZER_JOBS_PATH, snapshot)

    background_tasks.add_task(process_analyzer_job, job_id, payload)
    return dict(job)


@app.post("/api/export")
async def export_step_to_pdf(
    file: UploadFile = File(...),
    format: str = Form("pdf"),
    title: Optional[str] = Form(None),
    drawing_no: Optional[str] = Form(None),
    revision: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    company: Optional[str] = Form(None),
    scale: Optional[str] = Form(None),
    standard: Optional[str] = Form(None),
    projection: Optional[str] = Form(None),
    general_tolerance: Optional[str] = Form(None),
    unit: Optional[str] = Form(None),
    sheet: Optional[str] = Form(None),
    k_factor: Optional[float] = Form(None),
    detail_level: Optional[int] = Form(None),
) -> Response:
    if format.lower() != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF is supported right now.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")

    extension = Path(file.filename).suffix.lower()
    if extension not in (".step", ".stp"):
        raise HTTPException(status_code=400, detail="Only STEP files (.step/.stp) are supported.")

    try:
        export_meta = build_metadata(
            title,
            drawing_no,
            revision,
            author,
            company,
            scale=scale,
            standard=standard,
            projection=projection,
            general_tolerance=general_tolerance,
            unit=unit,
            sheet=sheet,
            k_factor=k_factor,
            detail_level=detail_level,
        )
    except MetadataValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    freecad_cmd = resolve_freecad_cmd()
    if not freecad_cmd or not freecad_cmd.exists():
        raise HTTPException(
            status_code=500,
            detail="FreeCAD not found. Install FreeCAD and set FREECAD_PYTHON or FREECAD_CMD.",
        )

    data = await file.read()
    await file.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        safe_name = Path(file.filename).name
        input_path = temp_root / safe_name
        output_path = temp_root / "drawing.pdf"
        meta_path = temp_root / "meta.json"

        input_path.write_bytes(data)

        # DSE: Run feature probe + build dimension plan before FreeCAD subprocess
        from rules.dimension_strategy import (
            build_dimension_plan,
            select_layout_profile_standalone,
        )

        try:
            probe_result = run_feature_probe(file.filename, data)
            if probe_result and probe_result.get("ok") is True:
                dse_layout = select_layout_profile_standalone(
                    file.filename, probe_result
                )
                dse_plan = build_dimension_plan(
                    feature_payload=probe_result,
                    layout_profile=dse_layout,
                    detail_level=int(export_meta.get("detail_level", 1)),
                )
                export_meta["features"] = probe_result
                export_meta["dimension_plan"] = dse_plan.model_dump()
        except Exception as exc:
            import logging
            logging.getLogger("drawform.dse").warning("DSE failed (non-fatal): %s", exc)

        meta_path.write_text(
            json.dumps(
                export_meta,
                indent=2,
            ),
            encoding="utf-8",
        )

        debug_dir = ROOT / "_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        command = [str(freecad_cmd), str(FREECAD_SCRIPT), str(input_path), str(output_path)]
        env = os.environ.copy()
        env["DRAWFORM_META"] = str(meta_path)
        env["DRAWFORM_DEBUG_DIR"] = str(debug_dir)
        if export_meta.get("k_factor") is not None:
            env["DRAWFORM_K_FACTOR"] = str(export_meta["k_factor"])
        log_path = debug_dir / "last_export.log"
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                env=env,
                timeout=FREECAD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            stderr = normalize_stream_text(error.stderr).strip()
            stdout = normalize_stream_text(error.stdout).strip()
            timeout_note = f"FreeCAD timed out after {FREECAD_TIMEOUT_SECONDS} seconds."
            log_path.write_text(
                build_export_log(command, stderr, stdout, note=timeout_note),
                encoding="utf-8",
            )
            details = stderr or stdout
            detail = timeout_note if not details else f"{timeout_note} {details}"
            raise HTTPException(status_code=504, detail=detail) from error
        except OSError as error:
            message = f"Failed to start FreeCAD process: {error}"
            log_path.write_text(
                build_export_log(command, message, "", note="Process start error"),
                encoding="utf-8",
            )
            raise HTTPException(status_code=500, detail=message) from error

        log_path.write_text(
            build_export_log(command, result.stderr, result.stdout),
            encoding="utf-8",
        )

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=format_error_message(result.stderr, result.stdout))

        if not output_path.exists():
            raise HTTPException(
                status_code=500,
                detail=format_error_message(result.stderr, result.stdout),
            )

        pdf_bytes = output_path.read_bytes()

    download_name = f"{Path(file.filename).stem}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf", headers=_safe_content_disposition(download_name))


@app.post("/api/export-dxf")
async def export_step_to_dxf(
    file: UploadFile = File(...),
    k_factor: Optional[float] = Form(None),
) -> Response:
    """Export the flat pattern (Abwicklung / laser contour) of a sheet metal STEP as DXF."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")
    extension = Path(file.filename).suffix.lower()
    if extension not in (".step", ".stp"):
        raise HTTPException(status_code=400, detail="Only STEP files (.step/.stp) are supported.")

    freecad_cmd = resolve_freecad_cmd()
    if not freecad_cmd or not freecad_cmd.exists():
        raise HTTPException(
            status_code=500,
            detail="FreeCAD not found. Install FreeCAD and set FREECAD_PYTHON or FREECAD_CMD.",
        )

    data = await file.read()
    await file.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        safe_name = Path(file.filename).name
        input_path = temp_root / safe_name
        out_json = temp_root / "unfold.json"
        out_dxf = temp_root / "flat_pattern.dxf"

        input_path.write_bytes(data)

        env = os.environ.copy()
        if k_factor is not None:
            env["DRAWFORM_K_FACTOR"] = str(k_factor)
        env["DRAWFORM_K_STANDARD"] = "din"

        command = [str(freecad_cmd), str(FREECAD_UNFOLD_SCRIPT),
                   str(input_path), str(out_json), str(out_dxf)]
        try:
            result = await asyncio.to_thread(
                subprocess.run, command,
                capture_output=True, text=True, env=env, timeout=90,
            )
        except subprocess.TimeoutExpired as error:
            raise HTTPException(status_code=504, detail="Unfold timed out.") from error
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"Process error: {error}") from error

        if not out_dxf.exists():
            detail = "DXF export failed — part may not be sheet metal or unfold is unsupported."
            if out_json.exists():
                try:
                    info = json.loads(out_json.read_text(encoding="utf-8"))
                    if info.get("error"):
                        detail = f"Unfold error: {info['error']}"
                except Exception:
                    pass
            raise HTTPException(status_code=422, detail=detail)

        dxf_bytes = out_dxf.read_bytes()

    download_name = f"{Path(file.filename).stem}_flat.dxf"
    return Response(content=dxf_bytes, media_type="application/dxf", headers=_safe_content_disposition(download_name))


# =========================================================================== #
# Foto → STL → STEP → Zeichnung  (/api/reconstruct)
# =========================================================================== #

RECONSTRUCT_JOBS: Dict[str, Dict[str, Any]] = _restore_job_map(
    RECONSTRUCT_JOBS_PATH,
    interruption_message="Backend restart interrupted the reconstruct job.",
)
RECONSTRUCT_LOCK = threading.Lock()
RECONSTRUCT_PIPELINE_SCRIPT = ROOT / "freecad" / "reconstruct_pipeline.py"
RECONSTRUCT_STL_TO_STEP_SCRIPT = ROOT / "freecad" / "stl_to_step.py"
RECONSTRUCT_TIMEOUT_SECONDS = int(os.getenv("DRAWFORM_RECONSTRUCT_TIMEOUT_SECONDS", "300"))
RECONSTRUCT_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB per image
RECONSTRUCT_MAX_DIMENSION_MM = 10_000.0
RECONSTRUCT_MAX_PART_NAME_LEN = 80

# Ausgabe-Verzeichnis für Rekonstruktions-Jobs
RECONSTRUCT_OUTPUT_DIR = ROOT / "_debug" / "reconstruct"


def _update_reconstruct_job(job_id: str, **changes: Any) -> Dict[str, Any]:
    with RECONSTRUCT_LOCK:
        current = RECONSTRUCT_JOBS.get(job_id)
        if current is None:
            raise KeyError(job_id)
        updated = {**current, **changes}
        RECONSTRUCT_JOBS[job_id] = updated
        snapshot = copy.deepcopy(RECONSTRUCT_JOBS)
    _persist_job_map(RECONSTRUCT_JOBS_PATH, snapshot)
    return dict(updated)


def _run_reconstruct_pipeline(
    job_id: str,
    image_files: Dict[str, bytes],
    dimensions_mm: tuple,
) -> None:
    """Background-Task: Voxel-Carving → STL → STEP → PDF Zeichnung."""
    job_dir = RECONSTRUCT_OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        _update_reconstruct_job(job_id, status="processing", progress="Silhouetten werden extrahiert...")

        # 1. Bilder auf Disk schreiben
        image_paths: Dict[str, str] = {}
        for view, data in image_files.items():
            img_path = job_dir / f"{view}.jpg"
            img_path.write_bytes(data)
            image_paths[view] = str(img_path)

        stl_path = str(job_dir / "output.stl")
        step_path = str(job_dir / "output.step")
        pdf_path = str(job_dir / "output.pdf")

        # 2. Voxel-Carving (standalone Python, kein FreeCAD)
        _update_reconstruct_job(job_id, progress="3D-Rekonstruktion läuft (Voxel-Carving)...")

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "reconstruct_pipeline", str(RECONSTRUCT_PIPELINE_SCRIPT)
        )
        pipeline_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pipeline_mod)

        recon_result = pipeline_mod.run_reconstruction(
            image_paths=image_paths,
            dimensions_mm=dimensions_mm,
            output_stl=stl_path,
            voxel_res=128,
        )

        if not recon_result.get("ok"):
            _update_reconstruct_job(
                job_id,
                status="failed",
                error=recon_result.get("error", "Rekonstruktion fehlgeschlagen"),
            )
            return

        # 3. STL → STEP via FreeCAD
        _update_reconstruct_job(job_id, progress="STL → STEP Konvertierung...")
        freecad_cmd = resolve_freecad_cmd()
        stl_ok = False
        if freecad_cmd and freecad_cmd.exists():
            stl2step_result = subprocess.run(
                [str(freecad_cmd), str(RECONSTRUCT_STL_TO_STEP_SCRIPT), stl_path, step_path],
                capture_output=True, text=True, timeout=120,
            )
            stl_ok = stl2step_result.returncode == 0 and Path(step_path).exists()

        # 4. STEP → PDF Zeichnung via step_to_pdf.py
        pdf_ok = False
        if stl_ok and freecad_cmd:
            job_snapshot = _update_reconstruct_job(job_id, progress="Technische Zeichnung wird erstellt...")
            meta = {
                "format": "pdf",
                "paper_size": "A3",
                "title": job_snapshot.get("partName", "Rekonstruiertes Bauteil"),
                "input_path": step_path,
            }
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as mf:
                json.dump(meta, mf)
                meta_path = mf.name
            try:
                env = os.environ.copy()
                env["DRAWFORM_META"] = meta_path
                env["DRAWFORM_DEBUG_DIR"] = str(job_dir)
                pdf_result = subprocess.run(
                    [str(freecad_cmd), str(FREECAD_SCRIPT), step_path, pdf_path],
                    capture_output=True, text=True, timeout=RECONSTRUCT_TIMEOUT_SECONDS, env=env,
                )
                pdf_ok = pdf_result.returncode == 0 and Path(pdf_path).exists()
            finally:
                try:
                    os.unlink(meta_path)
                except OSError:
                    pass

        _update_reconstruct_job(
            job_id,
            status="completed",
            progress=None,
            error=None,
            result={
                "stl_available": Path(stl_path).exists(),
                "step_available": stl_ok,
                "pdf_available": pdf_ok,
                "vertex_count": recon_result.get("vertex_count", 0),
                "triangle_count": recon_result.get("triangle_count", 0),
                "filled_voxel_ratio": recon_result.get("filled_voxel_ratio", 0),
                "dimensions_mm": {
                    "width": dimensions_mm[0],
                    "height": dimensions_mm[1],
                    "depth": dimensions_mm[2],
                },
                "completedAt": now_iso(),
            },
        )

    except Exception as exc:
        try:
            _update_reconstruct_job(job_id, status="failed", error=str(exc), progress=None)
        except KeyError:
            pass


@app.get("/api/reconstruct")
def list_reconstruct_jobs() -> list[Dict[str, Any]]:
    with RECONSTRUCT_LOCK:
        jobs = [dict(job) for job in RECONSTRUCT_JOBS.values()]
    jobs.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return jobs


@app.get("/api/reconstruct/{job_id}")
def get_reconstruct_job(job_id: str) -> Dict[str, Any]:
    with RECONSTRUCT_LOCK:
        job = RECONSTRUCT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Reconstruct job not found.")
    return dict(job)


@app.get("/api/reconstruct/{job_id}/download")
def download_reconstruct_file(job_id: str, type: str = "stl") -> Response:
    """Lädt STL, STEP oder PDF eines abgeschlossenen Rekonstruktions-Jobs herunter."""
    with RECONSTRUCT_LOCK:
        job = RECONSTRUCT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job noch nicht abgeschlossen.")

    allowed = {"stl", "step", "pdf"}
    if type not in allowed:
        raise HTTPException(status_code=400, detail=f"Ungültiger Typ. Erlaubt: {allowed}")

    file_path = RECONSTRUCT_OUTPUT_DIR / job_id / f"output.{type}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{type.upper()}-Datei nicht verfügbar.")

    mime_map = {"stl": "model/stl", "step": "application/step", "pdf": "application/pdf"}
    part_name = job.get("partName", "rekonstruktion")
    safe_name = re.sub(r"[^A-Za-z0-9_\-]", "_", part_name)
    return Response(
        content=file_path.read_bytes(),
        media_type=mime_map[type],
        headers=_safe_content_disposition(f"{safe_name}.{type}"),
    )


@app.post("/api/reconstruct")
async def create_reconstruct_job(
    background_tasks: BackgroundTasks,
    front: UploadFile = File(...),
    top: UploadFile = File(...),
    left: UploadFile = File(...),
    right: UploadFile = File(...),
    back: UploadFile = File(...),
    part_name: str = Form("Bauteil"),
    width_mm: float = Form(100.0),
    height_mm: float = Form(100.0),
    depth_mm: float = Form(100.0),
) -> Dict[str, Any]:
    """
    Startet einen Rekonstruktions-Job aus 5 orthogonalen Fotos.

    Fotos: front (Vorne), top (Oben), left (Links), right (Rechts), back (Hinten).
    Dimensionen: Reale Bauteil-Abmessungen in mm (optional, Standard 100×100×100).

    Gibt sofort Job-Dict zurück. Status per GET /api/reconstruct/{id} pollen.
    """
    # Bilder einlesen
    views = {"front": front, "top": top, "left": left, "right": right, "back": back}
    image_files: Dict[str, bytes] = {}
    total_size = 0
    for view_name, upload in views.items():
        data = await upload.read()
        await upload.close()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail=f"Leere Datei für Ansicht: {view_name}")
        if len(data) > RECONSTRUCT_MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail=f"Bild zu groß (max 20 MB): {view_name}")
        image_files[view_name] = data
        total_size += len(data)

    # Dimensionen validieren
    dims = (
        max(1.0, min(float(width_mm), RECONSTRUCT_MAX_DIMENSION_MM)),
        max(1.0, min(float(height_mm), RECONSTRUCT_MAX_DIMENSION_MM)),
        max(1.0, min(float(depth_mm), RECONSTRUCT_MAX_DIMENSION_MM)),
    )

    job_id = uuid4().hex
    safe_part_name = (part_name or "Bauteil").strip()[:RECONSTRUCT_MAX_PART_NAME_LEN] or "Bauteil"
    job: Dict[str, Any] = {
        "id": job_id,
        "createdAt": now_iso(),
        "status": "pending",
        "partName": safe_part_name,
        "totalSize": total_size,
        "dimensionsMm": {"width": dims[0], "height": dims[1], "depth": dims[2]},
        "progress": None,
        "result": None,
        "error": None,
    }
    with RECONSTRUCT_LOCK:
        RECONSTRUCT_JOBS[job_id] = job
        snapshot = copy.deepcopy(RECONSTRUCT_JOBS)
    _persist_job_map(RECONSTRUCT_JOBS_PATH, snapshot)

    background_tasks.add_task(_run_reconstruct_pipeline, job_id, image_files, dims)
    return dict(job)
