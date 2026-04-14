# CLAUDE.md

(Manuell editierbar. Der Block unten wird vom Agent Architect verwaltet.)

<!-- agent-architect:start -->
# CLAUDE.md
Diese Datei wird von **Agent Architect** teilweise verwaltet (Managed Block).
Alles ausserhalb des Blocks ist manuell editierbar.
## Projekt-Kontext
**Name:** Drawform
**Beschreibung:** CAD-to-Technical-Drawing conversion platform. STEP -> FreeCAD -> SVG -> PDF. Normkonforme 2D-Fertigungszeichnungen (DIN EN ISO, First-Angle Projection, ISO 7200 Schriftfeld).
## Tech-Stack
- **frontend**: React 19 + TypeScript (Vite 7)
- **backend**: FastAPI (Python)
- **rendering**: FreeCAD subprocess pipeline
## Erlaubte Befehle
- `npm install` / `npm run dev` / `npm run build` / `npm run lint` (Frontend)
- `cd server && python -m pytest tests/` (DSE Unit Tests)
- `cd server && python test_views.py` (View Regression)
- `cd server && python test_views.py --update-golden` (Golden Baseline regenerieren)
- `cd server && python run_quality_gate.py` (Quality Gate Runner)
## Regeln
- Workflow, Gates und Failure Classes stehen in `AGENTS.md`.
- Sync-Regeln stehen in `REPO_SYNC_POLICY.md`.
- Backend-Befehle und Setup stehen in `server/README.md`.
- Aenderungen klein halten; jede Aenderung mit Akzeptanzkriterien abschliessen.
- `step_to_pdf.py` ist High-Risk: nach jeder Aenderung mindestens einen gezielten `test_views.py`-Fall ausfuehren.
<!-- agent-architect:end -->

