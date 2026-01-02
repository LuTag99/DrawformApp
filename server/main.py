from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parent
FREECAD_SCRIPT = ROOT / "freecad" / "step_to_pdf.py"

app = FastAPI(title="Drawform Local API", version="0.1.0")


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


def build_metadata(
    title: Optional[str],
    drawing_no: Optional[str],
    revision: Optional[str],
    author: Optional[str],
    company: Optional[str],
) -> Dict[str, Any]:
    today = dt.date.today().isoformat()
    return {
        "title": title or "Manufacturing Drawing",
        "drawing_no": drawing_no or "DF-0001",
        "revision": revision or "A",
        "author": author or "Drawform AI",
        "company": company or "Drawform",
        "date": today,
        "unit": "mm",
        "sheet": "A3",
        "scale": "auto",
        "views": ["Top", "Front", "Right", "Iso"],
    }


def format_error_message(stderr: str, stdout: str) -> str:
    details = stderr.strip() or stdout.strip()
    if details:
        return f"FreeCAD failed: {details}"
    return "FreeCAD failed without details."


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/logs/last")
def last_export_log() -> Response:
    log_path = ROOT / "_debug" / "last_export.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No export log found yet.")
    return Response(content=log_path.read_text(encoding="utf-8"), media_type="text/plain")


@app.post("/api/export")
async def export_step_to_pdf(
    file: UploadFile = File(...),
    format: str = Form("pdf"),
    title: Optional[str] = Form(None),
    drawing_no: Optional[str] = Form(None),
    revision: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    company: Optional[str] = Form(None),
) -> Response:
    if format.lower() != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF is supported right now.")

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
        output_path = temp_root / "drawing.pdf"
        meta_path = temp_root / "meta.json"

        input_path.write_bytes(data)
        meta_path.write_text(
            json.dumps(
                build_metadata(title, drawing_no, revision, author, company),
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
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        log_path = debug_dir / "last_export.log"
        log_content = "\n".join(
            [
                f"[drawform] command: {' '.join(command)}",
                "[drawform] --- stderr ---",
                result.stderr.strip(),
                "[drawform] --- stdout ---",
                result.stdout.strip(),
            ]
        ).strip()
        log_path.write_text(log_content, encoding="utf-8")

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=format_error_message(result.stderr, result.stdout))

        if not output_path.exists():
            raise HTTPException(
                status_code=500,
                detail=format_error_message(result.stderr, result.stdout),
            )

        pdf_bytes = output_path.read_bytes()

    download_name = f"{Path(file.filename).stem}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
