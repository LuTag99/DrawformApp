# Drawform Local Backend (STEP -> PDF)

This service converts STEP files into DIN/ISO-style manufacturing drawings (PDF) using FreeCAD.

## Requirements

- FreeCAD installed (0.21+ recommended)
- Python 3.10+ for FastAPI

## Setup (Windows)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the FreeCAD Python path (adjust the version as needed):

```powershell
setx FREECAD_PYTHON "C:\Program Files\FreeCAD 1.0\bin\python.exe"
```

## Run

```powershell
uvicorn main:app --reload --port 8000
```

## Health check

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

## Debug SVG (wenn PDF leer ist)

Das Backend schreibt eine Debug-SVG nach `server/_debug`.
Oeffne die Datei im Browser, um zu sehen, ob die Ansichten gerendert wurden.

## Docker (empfohlen)

```powershell
# im Repo-Root
docker compose up --build
```

Der Service laeuft danach auf `http://localhost:8000`.

## Test

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" http://localhost:8000/api/export -o drawing.pdf
```

Norm profile parameters (optional, validated):

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" `
  -F "scale=1:2" `
  -F "projection=1. Winkel (DIN EN ISO 5456-2)" `
  -F "standard=DIN EN ISO 128/129-1" `
  -F "general_tolerance=DIN ISO 2768-mK" `
  -F "unit=mm" `
  -F "sheet=auto" `
  http://localhost:8000/api/export -o drawing.pdf
```

Unit tests for norm profile:

```powershell
cd server
python -m unittest test_norm_profile.py
python -m unittest test_sample_catalog.py
```

API endpoint tests (mocked FreeCAD subprocess):

```powershell
cd server
python -m unittest test_api_endpoints.py
```

View regression tests (with golden baseline):

```powershell
cd server
python test_views.py --sample-set baseline
```

Create/update golden baseline (after intentional layout/geometry changes):

```powershell
cd server
python test_views.py --sample-set baseline --update-golden
```

View stability loop (repeat marked samples):

```powershell
cd server
python test_views.py --sample-set baseline --stability-runs 3
```

Real-world local regression set (14 unique STEP/PDF pairs from `_samples/Sheetmetals` + `_samples/milling parts`):

```powershell
cd server
python test_views.py --sample-set real --update-golden
python test_views.py --sample-set all --update-golden
```

Local visual benchmark against real reference PDFs:

```powershell
cd server
python -m pip install pymupdf
python benchmark_real_parts.py --sample-set real
```

Norm and drawing-quality checks are part of `test_views.py`:
- title-block norm markers
- unitless dimension values
- dashed centerlines for circular features
- drawing-area overflow checks

Generate complex regression samples (5 feature-rich parts):

```powershell
& "C:\Program Files\FreeCAD 1.0\bin\python.exe" server\freecad\generate_complex_reference_parts.py
```

Run full local quality gate (self-check loop):

```powershell
cd server
python run_quality_gate.py --stability-runs 2
python run_quality_gate.py --stability-runs 2 --iterations 2
```

`run_quality_gate.py` uses `server/.venv/Scripts/python.exe` automatically when available.

Knowledge base for dimensioning decisions:

```powershell
cd server
python knowledge/validate_knowledge_base.py
python rules/rule_engine.py --feature hole --ctx visible=true
```

Knowledge data and quality process:
- Data file: `server/knowledge/knowledge_base.json`
- Quality guide: `server/knowledge/QUALITY_GUIDE.md`
- Rule engine: `server/rules/rule_engine.py`

Analyzer (Phase 3, Feature-Erkennung):

```powershell
curl -F "file=@C:\path\model.step" -F "units=mm" -F "scale=1" http://localhost:8000/api/analyze
```

## Notes

- The export layout supports `sheet=auto|A3|A2`; `auto` starts with A3 and promotes to A2 for large/low-scale parts.
- Views are generated as top/front/left/iso with an additional local flat-pattern fallback area for sheet-metal profiles.
- The drawing includes an ISO7200-style title block and overall dimensions.
- `/api/analyze` supports backend jobs (pending/processing/completed/failed).
- For CAD files (`.step/.stp/.iges/.igs/.stl/.brep`) a FreeCAD feature probe derives dimensions and hole/bend hints.
- Norm baseline for DE/AT technical drawings: `server/docs/DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`.
