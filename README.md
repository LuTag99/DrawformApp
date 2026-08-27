# Drawform

### From 3D CAD models to technical drawings.

Drawform is a functional prototype that automates parts of the technical drawing workflow for mechanical engineering.

The project started from a problem I experienced firsthand as a mechanical designer: once a 3D model was finished, creating the corresponding 2D manufacturing drawing was often repetitive and time-consuming.

I started building Drawform to explore how much of that workflow can be automated.

## What works today

- STEP/STP file import
- Geometry processing with FreeCAD
- Automatic orthographic and isometric projections
- Rule-based selection of basic dimensions
- Automatic drawing layout
- Technical PDF export
- Drawing-quality checks before export

## Current status

Drawform is a **functional prototype**, not a production-ready engineering tool.

Complex section views, complete tolerancing, GD&T, surface specifications and full manufacturing-documentation reliability are not yet implemented.

Generated drawings currently require engineering review.

## How I built it

My background is mechanical engineering, not software development.

I built Drawform largely through AI-assisted development using **Codex and Claude**, combining AI coding tools with my own experience in CAD, automation and manufacturing.

That is one of the ideas behind the project:

> **What becomes possible when domain experts can use AI to build software for problems they know firsthand?**

## Workflow

```text
STEP / STP Model
      ↓
Geometry Analysis
      ↓
Rule-Based Drawing Logic
      ↓
Views + Basic Dimensions
      ↓
Technical PDF
```

## Built with

React · TypeScript · FastAPI · Python · FreeCAD · Electron

---

**Status:** Prototype / Work in Progress

## Development setup

### Frontend

```bash
npm install
npm run dev
```

The Vite development server runs on port `5173` by default.

### Backend

```powershell
cd C:\Projects\DrawformApp\server
.venv\Scripts\Activate.ps1
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000
```

The local backend provides the STEP-to-PDF pipeline and the Analyzer and reconstruction endpoints.

## Firebase setup

1. Register a Firebase web application and add the `VITE_FIREBASE_*` values to `.env.local`.
2. Enable `Email/Password` and `Google` under Firebase Authentication.
3. Create a Firebase Storage bucket.
4. Create a service account for the backend and set `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_PATH` or `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_JSON`.
5. Set `DRAWFORM_FIREBASE_PROJECT_ID` if the project ID cannot be resolved from the credentials.

The frontend uses Firebase Authentication for protected routes and Firebase Storage for optional artifact and avatar uploads. The application does not currently use Firestore as a project database.

### Backend authentication modes

Protected endpoints such as `/api/export`, `/api/analyze`, `/api/reconstruct`, and `/api/ai-insight` support two modes.

#### Firebase authentication - default

`DRAWFORM_REQUIRE_FIREBASE_AUTH=1` is the default. Requests require a Firebase ID token:

```bash
TOKEN="<Firebase ID token>"
curl -X POST http://localhost:8000/api/export \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@part.step" \
  -F "format=pdf"
```

#### Local development without Firebase authentication

```powershell
$env:DRAWFORM_REQUIRE_FIREBASE_AUTH="0"
uvicorn main:app --reload --port 8000
```

This mode uses a local stub user and is intended only for development and testing.

## Implemented backend capabilities

- **STEP/STP to PDF:** imports real geometry through FreeCAD and generates projected drawing views.
- **Feature probe:** extracts bounding dimensions and heuristic hole, bend, chamfer, slot, pocket, and rotational information.
- **Dimension Strategy Engine:** applies deterministic rules for milling, turning, and sheet-metal profiles.
- **Drawing layout:** places views, dimensions, annotations, and a fixed A3/A2 title block.
- **Quality checks:** can reject an export when structural or layout problems are detected.
- **Conditional sheet-metal DXF:** requires the FreeCAD SheetMetal workbench to be installed separately.
- **Experimental photo reconstruction:** processes five silhouette views into STL, a tessellated STEP shell, and optionally a PDF.

The `/api/ai-insight` endpoint is currently keyword-based and does not call an AI model. Unsupported Analyzer inputs can fall back to simulated measurements.

## Main API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Backend health check |
| `POST /api/export` | STEP/STP to PDF export |
| `POST /api/export-dxf` | Conditional sheet-metal DXF export |
| `POST /api/analyze` | Geometry probe or simulated Analyzer job |
| `POST /api/reconstruct` | Start a five-photo reconstruction job |
| `GET /api/reconstruct/{job_id}` | Read reconstruction status |
| `GET /api/reconstruct/{job_id}/download` | Download an available reconstruction artifact |
| `POST /api/ai-insight` | Return a rule-based status message |

## Project structure

```text
src/
  components/        Reusable UI components
  layouts/           Authentication and application layouts
  pages/             Dashboard, Analyzer, Export, Projects, Profile, Reconstruct
  providers/         Firebase authentication context
  services/          Backend API and Firebase Storage clients
  styles/            Global application styles

server/
  main.py            FastAPI routes and job orchestration
  freecad/           STEP probing, drawing generation, unfolding, reconstruction
  rules/             Dimension planning, quality scoring, and rule schemas
  knowledge/         Drawing-rule knowledge base and reference-learning data
  tests/             Backend and drawing-strategy tests
  _debug/            Generated previews, reports, logs, and run artifacts
  _golden/           Managed regression baselines
  _samples/          STEP sample models
  test_views.py      Drawing regression and quality checks

electron/
  main.cjs           Desktop shell and local backend launcher
```

## Verification

Backend unit and API tests:

```powershell
cd server
python -m pytest tests test_api_endpoints.py test_norm_profile.py test_sample_catalog.py -q
```

Dimension-strategy tests:

```powershell
cd server
python -m pytest tests/test_dimension_strategy.py -q
```

Drawing smoke test:

```powershell
cd server
python test_views.py --sample-set baseline --stability-runs 1
```

Primary drawing-quality gate:

```powershell
cd server
python test_views.py --sample-set real20 --stability-runs 1
```

Current pass/fail numbers are intentionally not embedded in this README. Check CI and the latest artifacts under `server/_debug/visual_reviews/`.

## Available scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Start the Vite development server |
| `npm run build` | Type-check and build the frontend |
| `npm run preview` | Preview the production frontend build |
| `npm run lint` | Run ESLint |
| `npm run dist:win` | Build Windows NSIS and portable Electron packages |

## Deployment

The repository includes:

- A Dockerfile and Docker Compose configuration for the Python backend
- Electron Builder configuration for Windows desktop packages
- Apache/Plesk SPA routing configuration
- GitHub Actions workflows for frontend, backend, and drawing checks

Build the frontend with:

```bash
npm run build
```

The generated `dist/` directory can be served as a static single-page application. API routes must be forwarded to the FastAPI backend.
