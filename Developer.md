# Drawform Developer Entry

Diese Datei ist der schnelle Einstieg fuer Entwickler und KI-Agenten.

## Lies zuerst

1. `AGENTS.md`
2. `DEVELOPER_DOCS.md`
3. `.github/copilot-instructions.md`

## Verifizierter Snapshot (2026-03-20)

- Repo-Struktur: React 19 + TypeScript + Vite 7 im Root, FastAPI + FreeCAD-Pipeline unter `server/`
- Frontend-Routen laut `src/App.tsx`: `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus Auth-Seiten
- Backend-Endpunkte laut `server/main.py`: `/api/health`, `/api/logs/last`, `/api/analyze`, `/api/export`, `/api/export-dxf`, `/api/reconstruct`
- Sample-Sets laut `server/sample_catalog.py`: `baseline=20`, `real=28`, `all=48`
- `server/freecad/step_to_pdf.py` hat aktuell `7831` Zeilen und bleibt der groesste technische Hotspot

## Lokal geprueft am 2026-03-20

- `server\\.venv\\Scripts\\python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2` -> FAIL gegen Golden Baseline, Paper-Size-Drift in Front, Top, Left und Iso
- `server\\.venv\\Scripts\\python.exe run_quality_gate.py --iterations 1 --stability-runs 2` -> FAIL
- Innerhalb dieses Quality-Gate-Laufs waren `tests.test_dimension_strategy`, `test_sample_catalog`, `test_norm_profile.py` und `test_api_endpoints.py` gruen
- Rot waren `View regression` und `View stability loop`; der Baseline-Lauf lag in diesem Worktree bei `10/20` bestanden

## Wofuer welche Datei?

- `AGENTS.md`: globaler Arbeitsvertrag fuer FAST-PATH, FULL-PATH, LONG-RUN, `RUN CONTEXT` und Freigabelogik
- `DEVELOPER_DOCS.md`: technische Uebergabe mit Architektur, Pipeline, Quality-Status und aktuellen Risiken
- `.github/copilot-instructions.md`: kompakte Repo-Instruktionen fuer KI-gestuetzte Bearbeitung
- `Agent_planner.md`, `Agent_builder.md`, `Agent_artifact_steward.md`, `Agent_critic.md`, `Agent_regression.md`, `Agent_report.md`: rollenbezogene Prompts auf Basis des neuen Laufkontexts
- `server/orchestration/`: erstes CLI-Grundgeruest fuer Run-State, Artefakt-Sync und Stage-Steuerung

## Arbeitsweise ab jetzt

- Fuer Aufgaben mit Zeichnungs-, Benchmark- oder Agentenlogik zuerst in `AGENTS.md` den korrekten Pfad waehlen
- Ab `FULL-PATH` denselben `run_id` ueber alle Handoffs halten und Artefakte unter `server/_debug/agent_runs/<run_id>/` sammeln
- Zu jedem relevanten Lauf gehoeren exakte Commands, `*_debug.svg`, `*_preview.png`, `*_report.json` und ein `run_state.json` mit `revision`
- Derselbe `run_state.json` ist logisch ein Single-Writer-Artefakt; stale Stage-Transitions sollen ueber Stage/Iteration/Revision geblockt werden
- Der zuletzt dokumentierte Referenzlauf liegt unter `server/_debug/agent_runs/agent_workflow_contract_20260320_1906/`

## Wichtige Klarstellung

Alte Statusaussagen wie "Baseline 20/20" oder veraltete Quality-Gate-Beschreibungen sind fuer den aktuellen Stand nicht belastbar. Nutze die datierten Angaben in `DEVELOPER_DOCS.md`, den aktiven `run_id` und die aktuellen Artefakte.
