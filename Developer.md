# Drawform Developer Entry

Diese Datei ist der schnelle Einstieg fuer Entwickler und KI-Agenten.

## Lies zuerst

1. `AGENTS.md`
2. `DEVELOPER_DOCS.md`
3. `.github/copilot-instructions.md`

## Verifizierter Snapshot (2026-03-30)

- Repo-Struktur: React 19 + TypeScript + Vite 7 im Root, FastAPI + FreeCAD-Pipeline unter `server/`
- Frontend-Routen laut `src/App.tsx`: `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus Auth-Seiten
- Backend-Endpunkte laut `server/main.py`: `/api/health`, `/api/logs/last`, `/api/analyze`, `/api/export`, `/api/export-dxf`, `/api/ai-insight`, `/api/reconstruct`
- Sample-Sets laut `server/sample_catalog.py`: `baseline=20`, `real=91`, `all=111`
- `server/freecad/step_to_pdf.py` hat aktuell `~9200` Zeilen und bleibt der groesste technische Hotspot
- Wissensbasis: `server/knowledge/knowledge_base.json` v0.2.1 — **21 Quellen, 50 Regeln**

### Aktuelle Teststatus

- DSE Unit Tests: **64/64** bestanden
- Baseline Regression: `20/20` bestanden (Golden Baseline regeneriert 2026-03-22)
- All-Samples: `~105/111` (6 Failures: 1 Textueberlappung, 2 Timeouts, 2 Dim-Out-of-Bounds, 1 FreeCAD-Fehler)

### Neue Features seit 2026-03-22

- **GD&T / Formtoleranzen (ISO 1101)**: Toleranzrahmen-Renderer mit 14 Charakteristiken, Datum-Flags, Leader-Lines
- **Schnittansichten (ISO 128-40)**: Section-Cut-Engine, Cross-Hatching (ISO 128-50), Schnittlinien-Anzeige
- **Detailansichten**: Detail-Kreis, Zoom-Clip-Path, "Detail Z (2:1)"-Label
- **Diagonale Massfuehrung**: Diagonal-, Winkel- und Fasenbemassungen (ISO 129-1)
- **Schweisssymbole (ISO 2553)**: Kehlnaht, V-Naht, Stumpfnaht mit Ergaenzungssymbolen
- **Oberflaechenangaben (ISO 1302)**: Ra/Rz-Symbole mit Normzeichen
- **Massefeld (ISO 7200)**: Automatische Masseberechnung aus shape.Volume + Stahldichte
- **ISO 5455 Skalenlabel**: 10% Toleranz-Snap auf Normskalen inkl. DIN-Ergaenzungsskalen
- **Fasen-Erkennung**: `_detect_chamfers()` im Feature Probe
- **Langloch-Erkennung**: `collect_slot_data()` im Feature Probe (2 Halbkreisbogen + 2 Geraden)
- **Vollstaendige KB-Steuerung der DSE**: alle Bemassung-Gates jetzt KB-getrieben mit Fallback, `_kb_wants_dimension()` Hilffunktion
- **Slot-Bemaessung in DSE**: `slot_width`, `slot_length`, `slot_location`, `feature_count` aus KB-Regel `slot_complete_definition`
- **Abwicklung-Toggle in UI**: Checkbox "Abwicklung — In Zeichnung einfuegen" in ExportPage; steuert `include_flat_pattern` im Backend
- **Parallele Tests**: `--parallel N` Flag fuer ThreadPoolExecutor-basierte Testausfuehrung
- **DSE-Meta-Pipeline in Tests**: test_views.py spiegelt jetzt den Produktionspfad aus main.py

### KB-Aenderungen (2026-03-30)

- URL-Typo in ISO 129-1 Quelle behoben (`stanedard` → `standard`)
- ISO 2768-2 als WITHDRAWN markiert, ISO 22081:2021 als Nachfolger eingetragen
- Neue Tier-1-Quelle `iso_22081_catalog` hinzugefuegt
- ISO 261/965 Scope: Feingewinde-Pflicht (M8×1.0 statt M8) dokumentiert
- 4 Regel-Prioritaeten auf `must` hochgestuft: `hole_callout_complete_for_special_holes`, `thread_callout_complete`, `bend_radius_required`, `gdt_feature_control_frame`
- 12 neue Regeln: Senkung, Stufenbohrung, Blindgewinde-Tiefe, K-Faktor, Min-Biegeradius, GD&T Datumssystem + Lochbild-Position + Runout, Oberflaechenrauheit-Prozess-Defaults, Werkstoff-Pflicht, Schweissnaht-Vollstaendigkeit, Blechteil-Klassifizierungsschutz

### Schema-Erweiterungen (dimension_plan_schema.py)

- `GDTCallout`: Feature-Control-Frame mit Charakteristik, Toleranz, Modifier, Datum-Refs
- `SectionViewPlan`: Schnittansichts-Definition (Label, Eltern-View, Schnittposition)
- `DetailViewPlan`: Detailansichts-Definition (Label, Zoom-Faktor, Radius)
- `DimensionItem`: neue dim_types `slot_width`, `slot_length`, `slot_location`, `feature_count`, `total_span`, `chamfer`, `angle`, `diagonal`; axis `D`; `angle_deg`-Feld
- `ProcessNote`: neuer note_type `weld`, `surface_finish`

### Fixes seit 2026-03-20

- CORS-Middleware fuer localhost-Origins hinzugefuegt (`server/main.py`)
- Upload-Groessenlimits fuer `/api/analyze` (50 MB) und `/api/export` (100 MB) (`server/main.py`)
- OpenAI-Key aus Browser entfernt — `aiService.ts` nutzt jetzt Backend-Proxy `/api/ai-insight`
- `normalize_export_metadata()` bewahrt jetzt `dimension_plan` und `features` Felder
- ISO 5455 Snap-Overflow-Kaskade revertiert; nur Label-Snap mit 10% Toleranz behalten
- Simplify-Review-Fixes in DSE und Feature Probe: tote Funktionen entfernt, `collect_slot_data()` refactored, Running-Min/Max statt Liste

## Wofuer welche Datei?

- `AGENTS.md`: globaler Arbeitsvertrag fuer FAST-PATH, MEDIUM-PATH, FULL-PATH, LONG-RUN und Freigabelogik
- `DEVELOPER_DOCS.md`: technische Uebergabe mit Architektur, Pipeline, Quality-Status und aktuellen Risiken
- `.github/copilot-instructions.md`: kompakte Repo-Instruktionen fuer KI-gestuetzte Bearbeitung
- `Agent_planner.md`, `Agent_builder.md`, `Agent_artifact_steward.md`, `Agent_critic.md`, `Agent_regression.md`, `Agent_report.md`: rollenbezogene Prompts
- `server/orchestration/`: CLI-Grundgeruest fuer Run-State, Artefakt-Sync und Stage-Steuerung

## Arbeitsweise ab jetzt

- Fuer Aufgaben mit Zeichnungs-, Benchmark- oder Agentenlogik zuerst in `AGENTS.md` den korrekten Pfad waehlen
- Ab `FULL-PATH` denselben `run_id` ueber alle Handoffs halten und Artefakte unter `server/_debug/agent_runs/<run_id>/` sammeln
- Zu jedem relevanten Lauf gehoeren exakte Commands, `*_debug.svg`, `*_preview.png`, `*_report.json` und ein `run_state.json`
- `step_to_pdf.py`-Aenderungen sind Hochrisiko — nach jeder Aenderung mindestens einen gezielten `test_views.py`-Case ausfuehren

## Pflichttests nach Aenderungstyp

- Reine Test-/Doku-/Logging-Aenderung ohne Einfluss auf Zeichnungslogik: `FAST-PATH`; mindestens `cd server && .venv\Scripts\python.exe -m unittest discover`
- DSE-Regeln, Schema, KB oder Feature-Probe ohne direkte Layout-Aenderung: `MEDIUM-PATH`; `cd server && .venv\Scripts\python.exe -m pytest tests/test_dimension_strategy.py` plus mindestens ein gezielter Renderfall
- API-/Orchestrierungslogik ohne Renderer-Eingriff: `FAST-PATH`; `cd server && .venv\Scripts\python.exe -m unittest discover`, bei neuen Routen zusaetzlich gezielte Endpoint-Tests
- Render-, Layout-, View-Selection-, Bemaessungs- oder `step_to_pdf.py`-Aenderung: `FULL-PATH`; gezielter Renderlauf mit Artefakten plus `cd server && .venv\Scripts\python.exe test_views.py --sample-set baseline`
- Lokales Schnell-Gate fuer Backend-Aenderungen: `cd server && .venv\Scripts\python.exe run_quality_gate.py --mode fast`
- Lokales volles Gate vor riskanten Freigaben: `cd server && .venv\Scripts\python.exe run_quality_gate.py --mode full --stability-runs 2`

## Teststruktur in 3 Ebenen

- `server/_golden/views_baseline.json`: synthetische technische Baseline fuer die 20 kontrollierten Referenzteile
- `server/_golden/views_real_priority.json`: kuratierte Real-Part-Golden fuer den kleinen release-nahen Real-Gate-Satz
- `server/knowledge/reference_learning/reference_drawings_index.json` plus `reference_learning_gate.py`: Vergleich gegen echte STEP/PDF-Referenzen und deren Layout-/Font-/Blattmetriken

## Wichtige Klarstellung

Alte Statusaussagen wie "Baseline 20/20" oder veraltete Quality-Gate-Beschreibungen sind fuer den aktuellen Stand nicht belastbar. Nutze die datierten Angaben in `DEVELOPER_DOCS.md`, den aktiven `run_id` und die aktuellen Artefakte.
