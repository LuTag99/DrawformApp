# DrawformApp Developer Documentation

This document explains how to set up, run, and extend the DrawformApp frontend and local export backend.

## 1) Project overview

DrawformApp is a React + TypeScript frontend with a local FastAPI service that converts STEP files into A3 landscape manufacturing drawings (SVG -> PDF) using FreeCAD.

High level components:
- Frontend (React/Vite): UI, export screen, preview, local auth (LocalStorage)
- Backend (FastAPI): /api/export endpoint, calls FreeCAD Python to generate SVG/PDF
- FreeCAD Python: geometry import, view projection, layout, dimension lines

## 2) Repository layout

```
.
├─ src/                    # React app
│  ├─ components/          # UI components (buttons, cards, inputs)
│  ├─ layouts/             # Auth layout + app shell
│  ├─ pages/               # Auth, dashboard, projects, export, profile
│  ├─ providers/           # AuthContext (LocalStorage)
│  ├─ services/            # API services (export, AI stub)
│  └─ styles/              # Global styles
├─ server/                 # FastAPI backend + FreeCAD pipeline
│  ├─ freecad/             # STEP -> SVG -> PDF pipeline
│  ├─ templates/           # ISO 7200 drawing frame
│  ├─ _debug/              # Debug SVG output
│  └─ README.md            # Backend setup
├─ public/                 # Static assets
├─ deploy/                 # Deployment notes
├─ docker-compose.yml      # Optional local backend via Docker
└─ README.md               # Project overview
```

## 3) Prerequisites

Frontend:
- Node.js 18+ (or 20+ recommended)

Backend:
- Python 3.10+
- FreeCAD installed (0.21+ recommended, 1.0.x works)

## 4) Frontend setup

Install dependencies:

```powershell
cd C:\Projects\DrawformApp
npm install
```

Run dev server:

```powershell
npm run dev
```

Build:

```powershell
npm run build
```

## 5) Backend setup (Windows)

Create venv and install requirements:

```powershell
cd C:\Projects\DrawformApp\server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set FreeCAD Python path (adjust version/path if needed):

```powershell
setx FREECAD_PYTHON "C:\Program Files\FreeCAD 1.0\bin\python.exe"
```

Run backend:

```powershell
cd C:\Projects\DrawformApp\server
.venv\Scripts\Activate.ps1
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

## 6) Docker (optional)

```powershell
# from repo root
docker compose up --build
```

Backend will be at http://localhost:8000

## 7) Export pipeline (backend)

The export path is:

1) POST /api/export with a STEP file
2) FastAPI writes the file to a temp folder
3) FreeCAD Python loads the STEP shape
4) Projections are generated (Front, Top, Left/Side, Iso)
5) Layout on A3 landscape SVG with ISO 7200 title block
6) SVG is converted to PDF (ReportLab)

Main file to inspect:
- server/freecad/step_to_pdf.py

Debug output:
- server/_debug/*.svg (set DRAWFORM_DEBUG_DIR env var to enable)

## 8) Environment variables

Frontend:
- VITE_OPENAI_API_KEY (optional, see README)

Backend:
- FREECAD_PYTHON (required, points to FreeCAD python.exe)
- DRAWFORM_DEBUG_DIR (optional, path to dump debug SVG)

## 9) Common tasks

Run frontend + backend:

```powershell
# Terminal 1
cd C:\Projects\DrawformApp\server
.venv\Scripts\Activate.ps1
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000

# Terminal 2
cd C:\Projects\DrawformApp
npm run dev
```

Quick export test:

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" http://localhost:8000/api/export -o drawing.pdf
```

## 10) Troubleshooting

- Export shows empty PDF:
  - Check server/_debug output SVG to verify views are present.
  - Ensure FreeCAD is installed and FREECAD_PYTHON is correct.

- Frontend cannot reach backend:
  - Verify backend is running on port 8000.
  - Check browser console and server logs.

- Missing python package (reportlab, etc):
  - Activate venv and run: pip install -r requirements.txt

## 11) Local auth

Auth is local only (LocalStorage). There is no real backend auth.
The login page can be simplified for MVP and replaced later with a real auth provider.

## 12) Release and deployment

- Frontend builds to dist/
- Backend can be deployed separately or run in Docker

For more deployment notes see deploy/ and README.md.
