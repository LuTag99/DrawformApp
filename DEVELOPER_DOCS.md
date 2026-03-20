# Drawform Developer Documentation

Diese Datei ist die technische Uebergabe fuer Entwickler, die an Export, Zeichnungslogik, Wissensbasis oder den zugehoerigen Frontend-Flows weiterarbeiten.

## 1) Ziel und Scope

Drawform erzeugt aus 3D-Modellen moeglichst brauchbare 2D-Fertigungszeichnungen. Im aktuellen MVP ist nicht die Dateierzeugung das Ziel, sondern die fachliche Zeichnungsqualitaet.

Aktiver Scope im Repo:

- PDF-Export aus STEP via `/api/export`
- DXF-Export fuer Blech-Abwicklung via `/api/export-dxf`
- Analyzer-Jobs via `/api/analyze` mit Backend-Sync und lokalem Fallback im Frontend
- Rekonstruktionsjobs via `/api/reconstruct` aus 5 Fotos
- Regelbasierte Bemaessung ueber die Dimension Strategy Engine (DSE)
- Wissensbasis und Hilfslogik fuer Zeichnungs- und Fertigungsregeln unter `server/knowledge/`

Nicht belastbar als "fertig":

- Vollstaendige Normabdeckung
- Vollstaendige Turning-Strategie
- Stabile Golden-Baseline fuer alle View-Regressionen
- Produktive Sicherheit fuer Auth und OpenAI-Zugriff

## 2) Arbeitsmodus und Handoffs

Der verbindliche Prozess steht in `AGENTS.md`.
Wichtige Kurzfassung fuer Entwickler:

- `FAST-PATH`: nur fuer kleine Aenderungen ohne sinnvollen Einfluss auf Zeichnungslogik, Benchmark-Verhalten oder fachliche Qualitaet
- `FULL-PATH`: Pflicht fuer Zeichnungslogik, Heuristiken, Scoring, Benchmark-Verhalten und Agentenfreigaben
- `LONG-RUN`: verschaerfter `FULL-PATH` fuer stabile, release-nahe Mehrfachlaeufe

Ab `FULL-PATH` wird derselbe Laufkontext ueber alle Handoffs gefuehrt:

- `run_id`
- `revision`
- Iteration
- Target Case
- Benchmark Set
- Artifact Dir
- Previous Verdict
- Previous Failure Classes
- Required Commands

Standardpfad fuer laufbezogene Evidenz:

- `server/_debug/agent_runs/<run_id>/`

Erwartete Artefakte ab `FULL-PATH`:

- `run_state.json`
- aktuelles `*_debug.svg`
- aktuelles `*_preview.png`
- aktuelles `*_report.json`
- kurze Run-Zusammenfassung mit exakten Commands und Ergebnissen

Wichtig:

- `run_state.json` ist logisch ein Single-Writer-Artefakt
- Stage-Wechsel sollen gegen erwartete Stage, Iteration und Revision geprueft werden, damit ein veralteter Handoff nicht in denselben Lauf schreibt

Der aktuell dokumentierte Referenzlauf fuer die neue Agentenstruktur liegt unter:

- `server/_debug/agent_runs/agent_workflow_contract_20260320_1906/`

Das erste technische Orchestrierungsgeruest liegt unter:

- `server/orchestration/run_schema.py`
- `server/orchestration/artifacts.py`
- `server/orchestration/orchestrator.py`

## 3) Verifizierter Snapshot (2026-03-20)

Die folgenden Aussagen wurden waehrend dieser Doku-Aktualisierung lokal verifiziert:

- `server/.venv/Scripts/python.exe -c "from server.sample_catalog import resolve_sample_set; ..."` -> `baseline=20`, `real=28`, `all=48`
- `server/.venv/Scripts/python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2` -> FAIL gegen Golden Baseline
- `server/.venv/Scripts/python.exe run_quality_gate.py --iterations 1 --stability-runs 2` -> FAIL
- Im Quality-Gate-Lauf waren `tests.test_dimension_strategy`, `test_sample_catalog`, `test_norm_profile.py` und `test_api_endpoints.py` OK
- Im selben Lauf waren `View regression` und `View stability loop` rot
- Der Baseline-Teil des Quality Gates lag in diesem Worktree bei `10/20` bestanden
- `server/freecad/step_to_pdf.py` hat aktuell `7831` Zeilen

Konkrete lokal beobachtete Abweichungen:

- `complex_bracket` scheitert in `test_views.py`, weil die aktuellen Papiermasse fuer Front, Left, Top und Iso nicht mehr zur Golden Baseline passen
- Die rote View-Regression ist nicht auf einen einzelnen Spot-Check beschraenkt, sondern betrifft mehrere Baseline-Teile
- `run_quality_gate.py` ist aktueller als aeltere Doku-Staende und enthaelt bereits DSE-Tests und Sample-Katalog-Tests

Wichtig:

- Aeltere Aussagen wie "20/20 Baseline gruen" oder "test_sample_catalog ist nicht Teil des Quality Gate" sind fuer den Stand vom 2026-03-20 nicht mehr belastbar
- Fuer reproduzierbare Backend-Laeufe die Projekt-`.venv` benutzen

## 4) Systemueberblick

### Frontend

- Stack: React 19, TypeScript, Vite 7
- Einstieg: `src/main.tsx`
- Router: `src/App.tsx`
- Geschuetzter Bereich: `AuthProvider` + `ProtectedRoute`
- Feature-Seiten:
  - `src/pages/dashboard/DashboardPage.tsx`
  - `src/pages/analyzer/AnalyzerPage.tsx`
  - `src/pages/reconstruct/ReconstructPage.tsx`
  - `src/pages/export/ExportPage.tsx`
  - `src/pages/projects/ProjectsPage.tsx`
  - `src/pages/profile/ProfilePage.tsx`

### Backend

- Stack: FastAPI in `server/main.py`
- FreeCAD-Subprozesse:
  - `server/freecad/step_to_pdf.py`
  - `server/freecad/step_feature_probe.py`
  - `server/freecad/step_unfold.py`
- Regel- und Planlogik:
  - `server/rules/dimension_strategy.py`
  - `server/rules/dimension_plan_schema.py`
  - `server/rules/rule_engine.py`

### Verfuegbare API-Endpunkte

Laut `server/main.py`:

- `GET /api/health`
- `GET /api/logs/last`
- `GET /api/analyze`
- `GET /api/analyze/{job_id}`
- `POST /api/analyze`
- `POST /api/export`
- `POST /api/export-dxf`
- `GET /api/reconstruct`
- `GET /api/reconstruct/{job_id}`
- `GET /api/reconstruct/{job_id}/download`
- `POST /api/reconstruct`

## 5) Zeichnungs- und Exportpipeline

### PDF-Export

Der Hauptfluss fuer `/api/export`:

1. Upload und Metadatenvalidierung in `server/main.py`
2. Temporaere STEP-Datei schreiben
3. Feature-Probe ueber `server/freecad/step_feature_probe.py`
4. Layoutprofil und `DimensionPlan` ueber `server/rules/dimension_strategy.py`
5. FreeCAD-Renderer `server/freecad/step_to_pdf.py`
6. SVG/PDF in `server/_debug/` und Rueckgabe als HTTP-Response

Wichtige Hinweise:

- Die DSE entscheidet, was bemaesst wird
- `step_to_pdf.py` entscheidet, wie die Planinhalte auf dem Blatt landen
- Fuer Blechteile kann `step_to_pdf.py` ueber `step_unfold.py` eine echte Abwicklung anfordern
- Falls die DSE oder die Feature-Probe scheitert, existieren Fallback-Pfade. Diese koennen funktional exportieren, aber zeichnerisch schlechter sein

### DXF-Export

- `/api/export-dxf` ist separat in `server/main.py` implementiert
- Zweck ist der Flat-Pattern-Export fuer Blechteile
- Die gleiche Klassifikation und Abwicklungslogik beeinflusst die Qualitaet der Ausgabe

### Analyzer

Frontend und Backend sind hier gemischt:

- `src/services/analyzerService.ts` schreibt Jobs in `localStorage`
- Beim Laden wird gegen `GET /api/analyze` synchronisiert
- Neue Jobs gehen an `POST /api/analyze`
- Polling laeuft gegen `GET /api/analyze/{job_id}`
- Falls das Backend nicht erreichbar ist, springt eine lokale Fallback-Simulation an

Fazit: Der Analyzer ist nicht "nur lokal", aber das Frontend kann Backend-Ausfaelle kaschieren.

### Rekonstruktion

- `src/services/reconstructService.ts` spricht das Backend direkt an
- Upload: `POST /api/reconstruct`
- Polling: `GET /api/reconstruct/{job_id}`
- Download: `GET /api/reconstruct/{job_id}/download?type=stl|step|pdf`

## 6) Zentrale Dateien und Module

### Exportkern

- `server/main.py`
  - FastAPI-Endpunkte
  - Metadatenvalidierung
  - DSE-Orchestrierung
  - Subprozess-Steuerung

- `server/freecad/step_to_pdf.py`
  - groesster technischer Hotspot
  - Blattlayout, View-Erzeugung, Titleblock, Dimension-Rendering
  - lokale DSE-Fallback-Integration

- `server/freecad/step_feature_probe.py`
  - Geometrieanalyse fuer BBox, Bohrungen, Blechindikatoren, Lagehinweise

- `server/freecad/step_unfold.py`
  - Headless SheetMetal-Unfold fuer Blechteile

### Regel- und Wissenslogik

- `server/rules/dimension_strategy.py`
  - `select_layout_profile_standalone()`
  - `build_dimension_plan()`
  - `apply_overrides()`

- `server/rules/dimension_plan_schema.py`
  - Pydantic-Modelle fuer den JSON-Vertrag

- `server/rules/rule_engine.py`
  - Evaluierung von Wissensbasis-Regeln

- `server/knowledge/knowledge_base.json`
  - regelgetriebene Fachbasis

### Debug- und Review-Artefakte

- `server/_debug/*_debug.svg`
- `server/_debug/*_preview.png`
- `server/_debug/*_report.json`
- `server/_debug/agent_runs/<run_id>/run_state.json`
- `server/_golden/views_baseline.json`

## 7) Test- und Qualitaetslage

### Direkt lokal bestaetigt

```powershell
cd C:\Projects\DrawformApp\server

.venv\Scripts\python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2
.venv\Scripts\python.exe run_quality_gate.py --iterations 1 --stability-runs 2
```

Ergebnis:

- `complex_bracket` erzeugt aktuelle Artefakte, scheitert aber an der bestehenden Golden Baseline
- `run_quality_gate.py` ist insgesamt rot
- Gruen im Gate: DSE-Tests, Sample-Katalog-Tests, Normprofil-Tests, API-Endpoint-Tests, PDF-Review-Checklist
- Rot im Gate: `View regression`, `View stability loop`

### Was der Quality Gate Runner aktuell tut

`server/run_quality_gate.py` fuehrt derzeit aus:

1. `tests.test_dimension_strategy`
2. `test_sample_catalog`
3. `test_norm_profile.py`
4. `test_api_endpoints.py`
5. optional `test_views.py --update-golden`
6. `test_views.py --sample-set baseline`
7. `test_views.py --sample-set baseline --stability-runs N`
8. `generate_pdf_review_checklist.py`

Wichtig:

- Ein gruener Quality-Gate-Lauf wuerde weiterhin nicht automatisch bedeuten, dass die Zeichnung fachlich freigegeben ist; dafuer gelten die Critic- und Regression-Gates aus `AGENTS.md`
- Ein roter View-Regression-Lauf blockiert im aktuellen Stand jede belastbare Release-Aussage zur Zeichnungsqualitaet

## 8) Aktuelle Entwicklungsrisiken

### 1. Golden-Baseline-Drift in den View-Tests

Symptom:

- Der aktuelle Gate-Lauf war nur bei `10/20` Baseline-Teilen gruen

Vermutete Wirkorte:

- `server/freecad/step_to_pdf.py`
- `server/test_views.py`
- Layout-, Scale- oder SVG-Heuristiken

Folge:

- Historische Aussagen ueber stabile Baselines sind ohne erneuten Komplettlauf nicht belastbar

### 2. Renderer-Monolith bleibt ein Wartungsrisiko

Symptom:

- `server/freecad/step_to_pdf.py` ist aktuell `7831` Zeilen gross

Folge:

- Kleine Aenderungen koennen Seiteneffekte auf View-Auswahl, Scale, Dimensionierung und Debug-Artefakte haben

### 3. Tooling kann echte Domain-Probleme von Umgebungsproblemen entkoppeln, aber nicht ersetzen

Symptom:

- Die Projekt-`.venv` liefert reproduzierbare Testlaeufe, trotzdem bleibt die fachliche View-Baseline rot

Folge:

- Ein sauberer Test-Runner ersetzt keine visuelle und fachliche Critic-Pruefung

### 4. Frontend kaschiert Backend-Ausfaelle teilweise

Symptom:

- Analyzer faellt auf eine lokale Simulation zurueck

Wirkorte:

- `src/services/analyzerService.ts`
- `src/pages/analyzer/AnalyzerPage.tsx`

Folge:

- UI kann "funktionieren", obwohl der echte Backend-Worker ausgefallen ist

### 5. Sicherheitsluecken bleiben dokumentationsrelevant

Symptom:

- OpenAI-Key wird im Browser verwendet
- Auth-Credentials liegen in `localStorage`, inklusive Passwort im Klartext

Wirkorte:

- `src/services/aiService.ts`
- `src/providers/AuthProvider.tsx`

Folge:

- Nicht produktionsreif, muss in jeder ernsthaften Deployment-Doku klar benannt werden

## 9) Empfohlene naechste Schritte

1. Die globale Paper-Size- und Layout-Drift in `test_views.py` und `step_to_pdf.py` zuerst an einem einfachen Baseline-Fall isolieren
2. Danach denselben Fix gegen `baseline` und bei Bedarf `real` neu laufen lassen, statt einzelne gruene Spot-Checks zu ueberbewerten
3. Fuer alle groesseren Zeichen- oder Agentenaenderungen einen `FULL-PATH`- oder `LONG-RUN`-Lauf mit `run_id` und `server/_debug/agent_runs/<run_id>/` fuehren
4. Backend-Fallbacks im Analyzer fuer QA sichtbar halten, damit lokale Simulation nicht als echter Worker-Erfolg missverstanden wird
5. Sicherheitsrelevante Frontend-Shortcuts weiterhin als bewusste MVP-Schulden markieren

## 10) Moegliche Erweiterungen der Agentenstruktur

Die aktuelle Struktur `Planner -> Builder -> Agent_artifact_steward -> Critic -> Regression -> Report` ist fuer den MVP brauchbar, hat aber noch Ausbaupotenzial fuer laengere und qualitativ hoeher abgesicherte Laeufe.

### A. Sinnvolle Zusatzrollen

1. `Agent_triage`
   - sitzt vor dem Planner
   - waehlt Zielgeometrie, Benchmark-Set und vermutete Failure Classes
   - verhindert, dass Planner und Builder mit einem zu unscharfen Ziel starten

2. `Agent_artifact_steward`
   - verwaltet `run_id`, `run_state.json`, Artefaktpfade und Iterationsvergleich
   - entlastet Builder und Report von Zustandsverwaltung
   - macht lange Laeufe robuster gegen Kontextverlust
   - erste technische Basis ist jetzt in `server/orchestration/` angelegt

3. `Agent_norm_review`
   - spezialisiert auf normnahe Zeichnungspruefung, Titelblock, Bemaessungsstil und Lochbilddarstellung
   - sinnvoll, wenn Drawform staerker Richtung DIN/ISO-Naehe ausgebaut wird

4. `Agent_release`
   - nimmt nur die Outputs von Critic, Regression und Report entgegen
   - trifft ein explizites Go/No-Go fuer Merge oder Release
   - verhindert, dass ein technischer Gruenlauf mit einer fachlichen Freigabe verwechselt wird

### B. Prozessverbesserungen ohne neue Rollen

1. Failure-Class-Historie pro Teil
   - pro `target_case` die letzten Failure Classes und Scores speichern
   - hilft bei Root-Cause-Erkennung und verhindert wiederholte Scheinfixes

2. Vergleich Vorlauf vs. Neulauf
   - `run_state.json` sollte immer auch Referenzen auf den direkten Vorgaengerlauf enthalten
   - Critic und Regression koennen dann nicht nur absolut, sondern auch relativ urteilen

3. Feste Kommandovorlagen
   - pro Path-Type klare Standard-Commands fuer Spot-Check, Baseline, Stability und Real-Samples
   - reduziert Diskussionen ueber "welcher Nachweis reicht"

4. Trennung von Domain-Review und Code-Review
   - der aktuelle Critic ist stark domainorientiert
   - optional koennte ein technischer `Code Reviewer` vor Regression greifen, um riskante Seiteneffekte frueher zu finden

### C. Priorisierte Ausbaurichtung

Wenn nur drei Verbesserungen als naechstes umgesetzt werden sollen, dann in dieser Reihenfolge:

1. `Agent_artifact_steward` weiter von Prompt + Hilfsmodul zu einem echten, durchgaengigen Controller ausbauen
2. Failure-Class-Historie pro `target_case`
3. `Agent_release` als separates, explizites Freigabegate

Diese drei Punkte verbessern lange Laeufe mehr als weitere freie Text-Prompts, weil sie Zustandsverlust, uneinheitliche Freigaben und fehlende Vergleichbarkeit direkt adressieren.

## 11) Relevante Befehle

```powershell
cd C:\Projects\DrawformApp\server

# Reproduzierbare Tests
.venv\Scripts\python.exe -m unittest tests.test_dimension_strategy
.venv\Scripts\python.exe -m unittest test_sample_catalog
.venv\Scripts\python.exe -m unittest test_norm_profile.py
.venv\Scripts\python.exe -m unittest test_api_endpoints.py

# View-Regression
.venv\Scripts\python.exe test_views.py --sample-set baseline
.venv\Scripts\python.exe test_views.py --sample-set baseline --single complex_bracket --stability-runs 2
.venv\Scripts\python.exe test_views.py --sample-set all

# Quality Gate
.venv\Scripts\python.exe run_quality_gate.py --iterations 1 --stability-runs 2
```
