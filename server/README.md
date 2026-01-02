# Drawform Local Backend (STEP -> PDF)

This service converts STEP files into an A3 landscape manufacturing drawing (PDF) using FreeCAD.

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

## Notes

- The export layout is A3 landscape with views: top, front, right, iso.
- The drawing includes an ISO7200-style title block and overall dimensions.
