# Copilot Instructions - DrawformApp

## Architecture

Two decoupled parts share one repo:

- Frontend (`src/`): React 19 + TypeScript SPA on Vite 7. Main routes are `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus auth pages. Entry path: `src/main.tsx` -> `BrowserRouter` -> `AuthProvider` -> `App`.
- Backend (`server/`): FastAPI service in `server/main.py`. Primary endpoints are `/api/export`, `/api/export-dxf`, `/api/analyze`, `/api/reconstruct`, `/api/health`, and `/api/logs/last`. Geometry work is delegated to FreeCAD subprocess scripts in `server/freecad/`.

Vite proxies `/api` to `http://localhost:8000` in dev via `vite.config.ts`.

## Working Contract

- Read `AGENTS.md` first for path selection and quality gates.
- Use `FAST-PATH` only for changes without meaningful drawing-quality or benchmark impact.
- Use `FULL-PATH` for drawing logic, heuristics, scoring, benchmark behavior, and agent workflow changes.
- Use `LONG-RUN` when the work must be stable across repeated runs or is release-facing.
- From `FULL-PATH` onward, keep a shared `RUN CONTEXT` with one `run_id`, exact commands, and artifacts under `server/_debug/agent_runs/<run_id>/`.
- Treat `run_state.json` as a single-writer artifact and use stage / iteration / revision guards when advancing a run.
- Use `server/orchestration/orchestrator.py` and the `Agent_artifact_steward.md` role as the first-class run-state / artifact sync skeleton.

## Current Reality Checks

As verified locally on 2026-03-20:

- `server/sample_catalog.py` currently resolves `20` baseline samples, `28` real samples, and `48` total.
- `server/freecad/step_to_pdf.py` is currently about `7.8k` lines and remains the highest-risk hotspot.
- `server/.venv/Scripts/python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2` fails against the current golden baseline due to paper-size drift.
- `server/.venv/Scripts/python.exe run_quality_gate.py --iterations 1 --stability-runs 2` fails.
- Inside that quality-gate run, DSE tests, sample catalog tests, norm profile tests, and API endpoint tests pass.
- The failing steps are `View regression` and `View stability loop`; baseline status in that run was `10/20` passed.

Do not repeat older blanket claims such as "baseline 20/20 is green" without rerunning the current suite.

## Key Data Flows

1. STEP -> PDF export: `ExportPage` -> `exportService.requestPdfExport()` -> `POST /api/export` -> `server/main.py` -> feature probe + DSE -> FreeCAD renderer `server/freecad/step_to_pdf.py` -> PDF response.
2. STEP -> DXF export: `ExportPage` -> `exportService.requestDxfExport()` -> `POST /api/export-dxf`.
3. Analyzer jobs: `analyzerService.ts` persists jobs in `localStorage`, syncs from `GET /api/analyze`, uploads to `POST /api/analyze`, polls `GET /api/analyze/{job_id}`, and falls back to a local worker simulation if the backend is unavailable.
4. Reconstruction jobs: `reconstructService.ts` posts 5 photos to `POST /api/reconstruct`, polls `GET /api/reconstruct/{job_id}`, and downloads via `GET /api/reconstruct/{job_id}/download`.
5. AI insights: `aiService.ts` calls the OpenAI Chat Completions API directly from the browser when `VITE_OPENAI_API_KEY` is present.
6. Auth: `AuthProvider.tsx` keeps credentials and session state in `localStorage`.

## Important Files

- `server/main.py`: FastAPI app, validation, DSE orchestration, subprocess control
- `server/freecad/step_to_pdf.py`: main drawing renderer, current monolith hotspot
- `server/freecad/step_feature_probe.py`: geometry feature extraction
- `server/freecad/step_unfold.py`: sheet-metal unfold subprocess
- `server/rules/dimension_strategy.py`: `select_layout_profile_standalone()`, `build_dimension_plan()`, `apply_overrides()`
- `server/test_views.py`: view regression and drawing-quality checks
- `server/run_quality_gate.py`: unit + regression + stability runner
- `server/orchestration/orchestrator.py`: run-state CLI for agent workflow orchestration
- `server/orchestration/artifacts.py`: artifact sync helpers for active target cases
- `server/_debug/agent_runs/`: persistent artifact folders for `FULL-PATH` and `LONG-RUN` work
- `src/services/exportService.ts`: PDF and DXF requests
- `src/services/analyzerService.ts`: backend-backed analyzer store with local fallback
- `src/services/reconstructService.ts`: reconstruction polling/download flow
- `src/providers/AuthProvider.tsx`: local auth stub

## Dev Commands

```powershell
npm run dev
npm run build
npm run lint

cd server
.venv\Scripts\python.exe -m unittest tests.test_dimension_strategy
.venv\Scripts\python.exe -m unittest test_sample_catalog
.venv\Scripts\python.exe -m unittest test_norm_profile.py
.venv\Scripts\python.exe -m unittest test_api_endpoints.py
.venv\Scripts\python.exe test_views.py --sample-set baseline
.venv\Scripts\python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2
.venv\Scripts\python.exe run_quality_gate.py --iterations 1 --stability-runs 2
```

Prefer the project `.venv` for backend commands.

## Working Rules

- UI copy is German. Keep code identifiers and most technical docs in English.
- For drawing-quality work, inspect `server/_debug/*_debug.svg`, `*_preview.png`, and `*_report.json` before claiming success.
- For `FULL-PATH` and `LONG-RUN`, also persist the latest artifacts and a `run_state.json` under `server/_debug/agent_runs/<run_id>/`.
- Do not describe the analyzer as "local-only". It has a real backend path plus a local fallback.
- Do not claim the current view baseline is green unless you have rerun it.
- Treat `step_to_pdf.py` edits as high-risk. Re-run at least a targeted `test_views.py` case after touching it.
- `VITE_OPENAI_API_KEY` is browser-visible and auth credentials are stored in `localStorage`; these are known MVP shortcuts, not production-safe designs.
