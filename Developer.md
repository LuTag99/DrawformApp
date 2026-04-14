# Drawform Developer Entry

Diese Datei ist der schnelle Einstieg fuer Entwickler und KI-Agenten.

## Lies zuerst

1. `AGENTS.md`
2. `REPO_SYNC_POLICY.md`
3. `DEVELOPER_DOCS.md`
4. `.github/copilot-instructions.md`

## Repository Orientation

- Repo-Struktur: React 19 + TypeScript + Vite 7 im Root, FastAPI + FreeCAD-Pipeline unter `server/`
- Frontend-Routen laut `src/App.tsx`: `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus Auth-Seiten
- Backend-Endpunkte laut `server/main.py`: `/api/health`, `/api/logs/last`, `/api/analyze`, `/api/export`, `/api/export-dxf`, `/api/ai-insight`, `/api/reconstruct`
- Sample-Sets werden in `server/sample_catalog.py` definiert; aktuelle Zaehler immer per Command aufloesen
- Baseline-Samples liegen in Kategorie-Unterordnern: `_samples/Fraesteile/`, `_samples/Drehteile/`, `_samples/Blechteile/`, `_samples/Baugruppen/`
- `server/freecad/step_to_pdf.py` bleibt der groesste technische Hotspot
- Die Wissensbasis lebt unter `server/knowledge/knowledge_base.json`

### Status Discipline

- Vertraue hier keinen fest eingeschriebenen Pass/Fail-Zahlen.
- Live-Status kommt aus Commands, CI und `server/_debug/agent_runs/<run_id>/run_state.json`.
- Die kanonischen Sync-Regeln stehen in `REPO_SYNC_POLICY.md`.
- Die technische Langform steht in `DEVELOPER_DOCS.md`.

### Neue Features seit 2026-03-22

- **Dimension Placement Bounds Checking**: Iterative Offset-Reduktion fuer Overall-Dims via `transform_local_bounds_to_paper()`, Feature-Dim-Suppression bei Out-of-Bounds, Post-Placement Safety Net (50mm-Schwelle)
- **Sample Catalog Reorganisation**: Baseline-Samples in Kategorie-Unterordner (`Fraesteile/`, `Drehteile/`, `Blechteile/`, `Baugruppen/`), `discover_baseline_samples()` und `_is_real_sample_path()` aktualisiert
- **Reference Learning Gate**: `reference_learning_gate.py` fuer kuratierte Real-Part-Vergleiche, `real_priority_samples.json` Manifest
- **GD&T / Formtoleranzen (ISO 1101)**: Toleranzrahmen-Renderer mit 14 Charakteristiken, Datum-Flags, Leader-Lines
- **Schnittansichten (ISO 128-40)**: Section-Cut-Engine, Cross-Hatching (ISO 128-50), Schnittlinien-Anzeige
- **Detailansichten**: Detail-Kreis, Zoom-Clip-Path, "Detail Z (2:1)"-Label
- **Diagonale Massfuehrung**: Diagonal-, Winkel- und Fasenbemassungen (ISO 129-1)
- **Schweisssymbole (ISO 2553)**: Kehlnaht, V-Naht, Stumpfnaht mit Ergaenzungssymbolen
- **Oberflaechenangaben (ISO 1302)**: Ra/Rz-Symbole mit Normzeichen
- **Massefeld (ISO 7200)**: Automatische Masseberechnung aus `shape.Volume` + Stahldichte
- **ISO 5455 Skalenlabel**: 10% Toleranz-Snap auf Normskalen inkl. DIN-Ergaenzungsskalen
- **Fasen-Erkennung**: `_detect_chamfers()` im Feature Probe
- **Langloch-Erkennung**: `collect_slot_data()` im Feature Probe (2 Halbkreisbogen + 2 Geraden)
- **Vollstaendige KB-Steuerung der DSE**: alle Bemassung-Gates jetzt KB-getrieben mit Fallback, `_kb_wants_dimension()` Hilffunktion
- **Slot-Bemaessung in DSE**: `slot_width`, `slot_length`, `slot_location`, `feature_count` aus KB-Regel `slot_complete_definition`
- **Abwicklung-Toggle in UI**: Checkbox "Abwicklung - In Zeichnung einfuegen" in ExportPage; steuert `include_flat_pattern` im Backend
- **Parallele Tests**: `--parallel N` Flag fuer ThreadPoolExecutor-basierte Testausfuehrung
- **DSE-Meta-Pipeline in Tests**: test_views.py spiegelt jetzt den Produktionspfad aus main.py

## Wofuer welche Datei?

- `AGENTS.md`: globaler Arbeitsvertrag fuer FAST-PATH, MEDIUM-PATH, FULL-PATH, LONG-RUN und Freigabelogik
- `REPO_SYNC_POLICY.md`: Besitzverhaeltnisse und Synchronisationsregeln fuer Repo-Doku, `.claude`, `.github` und `.vscode`
- `DEVELOPER_DOCS.md`: technische Uebergabe mit Architektur, Pipeline und stabilen Systemvertraegen
- `.github/copilot-instructions.md`: kompakte Repo-Instruktionen fuer KI-gestuetzte Bearbeitung
- `Agent_planner.md`, `Agent_builder.md`, `Agent_artifact_steward.md`, `Agent_visual_review.md`, `Agent_critic.md`, `Agent_regression.md`, `Agent_report.md`: rollenbezogene Prompts
- `server/orchestration/`: CLI-Grundgeruest fuer Run-State, Artefakt-Sync und Stage-Steuerung

## Arbeitsweise ab jetzt

- Fuer Aufgaben mit Zeichnungs-, Benchmark- oder Agentenlogik zuerst in `AGENTS.md` den korrekten Pfad waehlen
- Ab `FULL-PATH` denselben `run_id` ueber alle Handoffs halten und Artefakte unter `server/_debug/agent_runs/<run_id>/` sammeln
- Zu jedem relevanten Lauf gehoeren exakte Commands, `*_debug.svg`, `*_preview.png`, `*_report.json` und ein `run_state.json`
- Jede Iteration mit frischen Render- oder Preview-Artefakten braucht vor dem `Critic` eine dokumentierte visuelle Review
- `step_to_pdf.py`-Aenderungen sind Hochrisiko; nach jeder Aenderung mindestens einen gezielten `test_views.py`-Case ausfuehren

## Pflichttests nach Aenderungstyp

- Reine Test-/Doku-/Logging-Aenderung ohne Einfluss auf Zeichnungslogik: `FAST-PATH`; mindestens `cd server && .venv\\Scripts\\python.exe -m unittest discover`
- DSE-Regeln, Schema, KB oder Feature-Probe ohne direkte Layout-Aenderung: `MEDIUM-PATH`; `cd server && .venv\\Scripts\\python.exe -m pytest tests/test_dimension_strategy.py` plus mindestens ein gezielter Renderfall und visuelle Delta-Pruefung
- API-/Orchestrierungslogik ohne Renderer-Eingriff: `FAST-PATH`; `cd server && .venv\\Scripts\\python.exe -m unittest discover`, bei neuen Routen zusaetzlich gezielte Endpoint-Tests
- Render-, Layout-, View-Selection-, Bemaessungs- oder `step_to_pdf.py`-Aenderung: `FULL-PATH`; gezielter Renderlauf mit Artefakten plus `cd server && .venv\\Scripts\\python.exe test_views.py --sample-set baseline` und Visual-Review-Handoff vor dem `Critic`
- Lokales Schnell-Gate fuer Backend-Aenderungen: `cd server && .venv\\Scripts\\python.exe run_quality_gate.py --mode fast`
- Lokales volles Gate vor riskanten Freigaben: `cd server && .venv\\Scripts\\python.exe run_quality_gate.py --mode full --stability-runs 2`

## Teststruktur in 3 Ebenen

- `server/_golden/views_baseline.json`: synthetische technische Baseline
- `server/_golden/views_real_priority.json`: kuratierte Real-Part-Golden fuer den kleinen release-nahen Real-Gate-Satz
- `server/knowledge/reference_learning/reference_drawings_index.json` plus `reference_learning_gate.py`: Vergleich gegen echte STEP/PDF-Referenzen und deren Layout-/Font-/Blattmetriken

## Wichtige Klarstellung

Live-Status muss immer neu verifiziert werden. Nutze `REPO_SYNC_POLICY.md`,
die Commands aus `server/README.md`, den aktiven `run_id` und die aktuellen
Artefakte statt alter, ausgeschriebener Pass/Fail-Staende.
