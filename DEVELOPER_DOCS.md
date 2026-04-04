# Drawform Developer Documentation

Diese Datei ist die technische Langform fuer Entwickler, die an Export,
Zeichnungslogik, Wissensbasis oder den zugehoerigen Frontend-Flows arbeiten.

## 1) Ziel und Scope

Drawform erzeugt aus 3D-Modellen moeglichst brauchbare 2D-Fertigungszeichnungen.
Im aktuellen MVP ist nicht die Dateierzeugung das Ziel, sondern die fachliche
Zeichnungsqualitaet.

Aktiver Scope im Repo:

- PDF-Export aus STEP via `/api/export`
- DXF-Export fuer Blech-Abwicklung via `/api/export-dxf`
- Analyzer-Jobs via `/api/analyze` mit Backend-Sync und lokalem Fallback im Frontend
- Rekonstruktionsjobs via `/api/reconstruct` aus 5 Fotos
- Regelbasierte Bemaessung ueber die Dimension Strategy Engine (DSE)
- Wissensbasis und Hilfslogik fuer Zeichnungs- und Fertigungsregeln unter `server/knowledge/`
- Normkonforme Annotationen als Infrastruktur: GD&T, Schnittansichten, Oberflaechenangaben, Schweisssymbole, Fasenbemassung

Nicht belastbar als "fertig":

- Vollstaendige Normabdeckung
- Vollstaendige Turning-Strategie
- Produktive Sicherheit fuer Auth und OpenAI-Zugriff
- Vollautomatische Schnittansichts-Erzeugung

## 2) Kanonische Quellen

Verwende diese Besitzverhaeltnisse konsequent:

- `AGENTS.md`: Workflow, Path-Typen, Gates, Failure Classes
- `REPO_SYNC_POLICY.md`: Besitzverhaeltnisse zwischen Doku, `.claude`, `.github`, `.vscode`
- `DEVELOPER_DOCS.md`: technische Architektur und stabile Systemvertraege
- `server/README.md`: kanonische Backend-Kommandos
- `server/_debug/agent_runs/<run_id>/run_state.json`: aktueller Lauf- und Freigabestatus

Wichtig:

- Diese Datei beschreibt Architektur und technische Vertraege.
- Sie ist **nicht** die kanonische Quelle fuer Live-Pass/Fail-Zahlen.
- Fuer Live-Status gelten Commands, CI und aktive `run_state.json`-Artefakte.

## 3) Arbeitsmodus und Handoffs

Der verbindliche Prozess steht in `AGENTS.md`.

Kurzfassung:

- `FAST-PATH`: kleine Aenderungen ohne sinnvollen Einfluss auf Zeichnungslogik oder Benchmark-Verhalten
- `MEDIUM-PATH`: vorhersagbare Output-Aenderungen ohne neue Kern-Renderlogik
- `FULL-PATH`: Pflicht fuer Zeichnungslogik, Heuristiken, Bemaessung, Layout, Benchmark-Verhalten und Freigaben
- `LONG-RUN`: verschaerfter `FULL-PATH` fuer stabile, release-nahe Mehrfachlaeufe

Ab `FULL-PATH` gilt:

- ein gemeinsamer `run_id`
- ein gemeinsamer Artefaktordner unter `server/_debug/agent_runs/<run_id>/`
- exakte Commands
- `*_debug.svg`, `*_preview.png`, `*_report.json`
- `run_state.json`

## 4) Systemueberblick

### Frontend

- Stack: React 19, TypeScript, Vite 7
- Einstieg: `src/main.tsx`
- Router: `src/App.tsx`
- Geschuetzter Bereich: `AuthProvider` + `ProtectedRoute`
- Wichtige Seiten:
  - `src/pages/dashboard/DashboardPage.tsx`
  - `src/pages/analyzer/AnalyzerPage.tsx`
  - `src/pages/reconstruct/ReconstructPage.tsx`
  - `src/pages/export/ExportPage.tsx`
  - `src/pages/projects/ProjectsPage.tsx`
  - `src/pages/profile/ProfilePage.tsx`

### Backend

- Stack: FastAPI in `server/main.py`
- FreeCAD-Subprozesse:
  - `server/freecad/step_to_pdf.py` - Hauptrenderer und groesster Hotspot
  - `server/freecad/step_feature_probe.py` - Geometrieanalyse
  - `server/freecad/step_unfold.py` - Sheet-Metal-Unfold
- Regel- und Planlogik:
  - `server/rules/dimension_strategy.py`
  - `server/rules/dimension_plan_schema.py`
  - `server/rules/rule_engine.py`

### Verfuegbare API-Endpunkte

- `GET /api/health`
- `GET /api/logs/last`
- `GET /api/analyze`, `GET /api/analyze/{job_id}`, `POST /api/analyze`
- `POST /api/export`, `POST /api/export-dxf`
- `POST /api/ai-insight`
- `GET /api/reconstruct`, `GET /api/reconstruct/{job_id}`, `GET /api/reconstruct/{job_id}/download`, `POST /api/reconstruct`

## 5) Zeichnungs- und Exportpipeline

### PDF-Export

Hauptfluss fuer `/api/export`:

1. Upload und Metadatenvalidierung in `server/main.py`
2. Temporaere STEP-Datei schreiben
3. Feature-Probe ueber `server/freecad/step_feature_probe.py`
4. Layoutprofil und `DimensionPlan` ueber `server/rules/dimension_strategy.py`
5. FreeCAD-Renderer `server/freecad/step_to_pdf.py`
6. SVG/PDF in `server/_debug/` und Rueckgabe als HTTP-Response

### Blechteil-Erkennung und Abwicklung

Ein Teil wird als `sheet_metal` behandelt, wenn Wanddicke, Planflaechenanteil
und gegebenenfalls Biegegeometrie dafuer sprechen. Die Abwicklung wird nur
erzeugt, wenn:

- `layout_profile == "sheet_metal"`
- `include_flat_pattern == True`
- der Subtyp fachlich eine Abwicklung braucht

### DSE-Pfad

`build_dimension_plan()` entscheidet **was** bemaesst wird, nicht **wie** es
gerendert wird. Der Renderer liest den Plan aus `meta.json`.

## 6) Dimension Strategy Engine (DSE)

Die DSE ist deterministisch und wissensbasisgetrieben.

Sie verarbeitet:

- `feature_payload`
- `layout_profile`
- `detail_level`

und erzeugt einen `DimensionPlan`.

Wichtige Regeln:

- KB-Regeln steuern bevorzugt die Bemaessungsentscheidung
- Fallback-Logik bleibt fuer Rueckwaertskompatibilitaet erhalten
- Overrides duerfen additiv auf dem deterministischen Plan liegen

Wichtige Dateien:

- `server/rules/dimension_plan_schema.py`
- `server/rules/dimension_strategy.py`
- `server/tests/test_dimension_strategy.py`
- `server/knowledge/knowledge_base.json`

## 7) Wissensbasis

Die Wissensbasis lebt in `server/knowledge/knowledge_base.json`.

Quellenmodell:

- `tier_1`: offizielle Norm- und Standardquellen
- `tier_2`: interne Baselines und Review-Artefakte
- `tier_3`: Shopfloor-Feedback und Beobachtungswissen

Begleitdokumente:

- `server/knowledge/QUALITY_GUIDE.md`
- `server/knowledge/LITERATURE_FERTIGUNGSZEICHNUNGEN_2026_03.md`
- `server/knowledge/reference_learning/README.md`
- `server/knowledge/reference_learning/priority_backlog.md`

## 8) Test- und Qualitaetsinfrastruktur

### Kern-Checks

- `server/tests/test_dimension_strategy.py` - DSE-Unit-Tests
- `server/test_views.py` - View-Regression und Zeichnungsqualitaetschecks
- `server/run_quality_gate.py` - lokales Schnell- und Volllauf-Gate
- `.github/workflows/quality-gate.yml` - GitHub-CI
- `scripts/validate_repo_sync.py` - Doku- und Governance-Sync-Check

### Golden- und Referenzbasis

- `server/_golden/views_baseline.json`
- `server/_golden/views_real_priority.json`
- `server/reference_learning_gate.py`
- `server/knowledge/reference_learning/reference_drawings_index.json`

### Debug- und Review-Artefakte

- `server/_debug/*_debug.svg`
- `server/_debug/*_preview.png`
- `server/_debug/*_report.json`
- `server/_debug/agent_runs/<run_id>/run_state.json`

## 9) Entwicklungsrisiken

### 1. Renderer-Monolith

`server/freecad/step_to_pdf.py` ist gross und seiteneffektanfaellig.
Jede Aenderung kann View-Auswahl, Massstab, Bemaessung und Annotationen treffen.

### 2. Trigger-Logik fuer neue Annotationen

Renderer fuer GD&T, Section, Detail und weitere Normelemente sind vorhanden,
aber die automatische Entscheidung "wann einfuegen" ist nur teilweise umgesetzt.

### 3. Duale Klassifizierungs-Codepfade

`select_layout_profile_standalone()` in der DSE und die Legacy-/Renderseite in
`step_to_pdf.py` muessen fachlich synchron bleiben.

### 4. Sicherheitsstand

Behoben:

- OpenAI-Key nicht mehr im Browser
- CORS-Middleware fuer localhost-Origins
- Upload-Groessenlimits

Offen:

- Auth-Credentials in `localStorage`

### 5. Frontend kaschiert Backend-Ausfaelle

Der Analyzer kann lokal simulieren. Dadurch kann das UI "funktionieren", obwohl
der echte Backend-Worker fehlt.

## 10) Relevante Befehle

Die kanonischen Befehle stehen in `server/README.md`.

Typische Kernbefehle:

```powershell
python scripts/validate_repo_sync.py
server\.venv\Scripts\python.exe -m pytest server\tests\test_dimension_strategy.py -q
server\.venv\Scripts\python.exe server\test_views.py
```

## 11) Entwicklungspraxis

- Fuer Aufgaben mit Zeichnungs-, Benchmark- oder Agentenlogik zuerst den Pfad in `AGENTS.md` waehlen
- Nach `step_to_pdf.py`-Aenderungen immer mindestens einen gezielten Renderfall fahren
- Erfolge nicht ueber Export, sondern ueber Zeichnungsqualitaet begruenden
- Spiegel-Dokumente frei von Live-Statuszahlen halten
- Bei Governance-Aenderungen immer auch `scripts/validate_repo_sync.py` und CI mitdenken
