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
- Normkonforme Annotationen: GD&T (ISO 1101), Schnittansichten (ISO 128-40), Oberflaechenangaben (ISO 1302), Schweisssymbole (ISO 2553), Fasenbemassungen

Nicht belastbar als "fertig":

- Vollstaendige Normabdeckung
- Vollstaendige Turning-Strategie
- Produktive Sicherheit fuer Auth und OpenAI-Zugriff
- Automatische Schnittansichts-Erzeugung (Infrastruktur steht, Trigger-Logik fehlt)

## 2) Arbeitsmodus und Handoffs

Der verbindliche Prozess steht in `AGENTS.md`.
Wichtige Kurzfassung fuer Entwickler:

- `FAST-PATH`: nur fuer kleine Aenderungen ohne sinnvollen Einfluss auf Zeichnungslogik, Benchmark-Verhalten oder fachliche Qualitaet
- `MEDIUM-PATH`: fuer Aenderungen mit vorhersagbarem Einfluss (Title-Block, Labels, Annotationstext)
- `FULL-PATH`: Pflicht fuer Zeichnungslogik, Heuristiken, Scoring, Benchmark-Verhalten und Agentenfreigaben
- `LONG-RUN`: verschaerfter `FULL-PATH` fuer stabile, release-nahe Mehrfachlaeufe

Ab `FULL-PATH` wird derselbe Laufkontext ueber alle Handoffs gefuehrt:

- `run_id`, `revision`, Iteration, Target Case, Benchmark Set, Artifact Dir

Standardpfad fuer laufbezogene Evidenz:

- `server/_debug/agent_runs/<run_id>/`

## 3) Verifizierter Snapshot (2026-04-02)

- `server/sample_catalog.py` → `baseline=20`, `real=91`, `all=111`
- Baseline-Samples in Kategorie-Unterordner: `_samples/Fraesteile/`, `_samples/Drehteile/`, `_samples/Blechteile/`, `_samples/Baugruppen/`
- `server/freecad/step_to_pdf.py` hat aktuell `~10.000` Zeilen
- DSE Unit Tests: **64/64** bestanden
- Baseline Regression: `20/20` bestanden (Golden Baseline regeneriert 2026-04-02)
- All-Samples: `96/111` (15 Failures: ~5 dim-outside-bounds mit <50mm Overflow, Rest Timeouts/Crashes/Golden-Mismatches)
- Vorher: ~25 dim-outside-bounds Failures; reduziert auf ~5 durch Overall-Dim-Clamping + Feature-Dim-Suppression
- `server/freecad/step_feature_probe.py` erkennt: Bohrungen, Gewinde, Biegeradien, Blechindikatoren, Fasen, **Langlocher (Slots)**
- `server/knowledge/knowledge_base.json` v0.2.1 — **21 Quellen, 50 Regeln**

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
  - `src/pages/export/ExportPage.tsx` — inkl. Abwicklung-Toggle (`includeFlatPattern`)
  - `src/pages/projects/ProjectsPage.tsx`
  - `src/pages/profile/ProfilePage.tsx`

### Backend

- Stack: FastAPI in `server/main.py`
- FreeCAD-Subprozesse:
  - `server/freecad/step_to_pdf.py` — Hauptrenderer (~10.000 Zeilen)
  - `server/freecad/step_feature_probe.py` — Geometrie-Analyse inkl. Fasen- und Langloch-Erkennung
  - `server/freecad/step_unfold.py` — Sheet-Metal-Unfold (nur wenn `include_flat_pattern=true`)
- Regel- und Planlogik:
  - `server/rules/dimension_strategy.py` — DSE: Layoutprofil, Dimension Plan, Overrides, KB-Steuerung
  - `server/rules/dimension_plan_schema.py` — Pydantic-Modelle (DimensionPlan, GDTCallout, SectionViewPlan, DetailViewPlan)
  - `server/rules/rule_engine.py` — Wissensbasis-Regelevaluierung

### Verfuegbare API-Endpunkte

Laut `server/main.py`:

- `GET /api/health`
- `GET /api/logs/last`
- `GET /api/analyze`, `GET /api/analyze/{job_id}`, `POST /api/analyze` (max 50 MB)
- `POST /api/export` (max 100 MB), `POST /api/export-dxf` (max 100 MB)
- `POST /api/ai-insight` (Backend-Proxy fuer AI-Insights)
- `GET /api/reconstruct`, `GET /api/reconstruct/{job_id}`, `GET /api/reconstruct/{job_id}/download`, `POST /api/reconstruct`

## 5) Zeichnungs- und Exportpipeline

### PDF-Export

Der Hauptfluss fuer `/api/export`:

1. Upload und Metadatenvalidierung in `server/main.py`
2. Temporaere STEP-Datei schreiben
3. Feature-Probe ueber `server/freecad/step_feature_probe.py` (BBox, Bohrungen, Gewinde, Fasen, Blechindikatoren, Langlocher)
4. Layoutprofil (`milling` / `sheet_metal` / `turning`) und `DimensionPlan` ueber `server/rules/dimension_strategy.py`
5. FreeCAD-Renderer `server/freecad/step_to_pdf.py` (empfaengt Plan via `meta.json` + `DRAWFORM_META` Env-Var)
6. SVG/PDF in `server/_debug/` und Rueckgabe als HTTP-Response

### Blechteil-Erkennung und Abwicklung

Die Klassifizierung als `sheet_metal` erfordert drei Kriterien (siehe KB-Regel `sheet_metal_classification_guard`):

1. Wanddicke ≤ 10 mm
2. ≥ 60 % Planflaechen (plane-type faces)
3. Optional: Echtbiege-Erkennung (bend_count > 0)

Dicke Platten (> 8 mm Minimalausdehnung) werden immer als `milling` klassifiziert, auch wenn sie flach sind.

Die Abwicklung (Abwicklung-Column im Layout) wird nur erzeugt wenn:
- `layout_profile == "sheet_metal"` UND
- `include_flat_pattern == True` (neu, Default: True)
- UND `sheet_metal_subtype == "biegeteil"` (bend_count > 0 nach Unfold)

Wird `include_flat_pattern=False` gesetzt (UI-Checkbox deaktiviert oder API-Parameter `include_flat_pattern=0`), ueberspringt das Backend den Unfold-Subprozess komplett und `sheet_metal_subtype` wird intern auf `"laserteil"` gesetzt.

### Normkonforme Annotationen (Infrastruktur vorhanden)

step_to_pdf.py enthaelt Renderer fuer:

- **GD&T (ISO 1101)**: `_build_gdt_frame_svg()`, `_build_datum_flag_svg()` — Toleranzrahmen mit 14 Charakteristiken
- **Schnittansichten (ISO 128-40)**: `_compute_section_cut()`, `_generate_section_view_svg()`, `_build_section_line_svg()`, Cross-Hatching (ISO 128-50)
- **Detailansichten**: `_build_detail_circle_svg()`, `_generate_detail_view_svg()` — Clip-Path-basierte Vergroesserung
- **Diagonale Massfuehrung (ISO 129-1)**: `build_diagonal_dimension_svg()`, `build_angle_dimension_svg()`, `build_chamfer_dimension_svg()`
- **Schweisssymbole (ISO 2553)**: `_iso2553_weld_symbol_svg()` — Kehlnaht, V-Naht, Stumpfnaht, Schraeganschluss
- **Oberflaechenangaben (ISO 1302)**: `_iso1302_symbol_svg()`, `_build_surface_finish_symbol()`
- **Massefeld (ISO 7200)**: Automatische Berechnung aus `shape.Volume` × Stahldichte (7.85 g/cm³)
- **ISO 5455 Skalenlabel**: DIN-Ergaenzungsskalen, 10% Toleranz-Snap in `format_actual_scale_label()`

Diese Renderer sind als Infrastruktur vorhanden. Die automatische Trigger-Logik (wann wird eine Schnittansicht erzeugt, wann ein GD&T-Frame platziert) ist teil-implementiert und wird durch die DSE-Plan-Felder (`section_views`, `detail_views`, `gdt_callouts`) gesteuert.

### DSE-Schema (dimension_plan_schema.py)

Aktuelle Modelle:

- `DatumSystem` — A/B/C Bezugssystem
- `DimensionItem` — Einzelbemassungsintent (H/V/D-Achse, 22 dim_types inkl. slot_width/length/location, feature_count, chamfer/angle/diagonal)
- `GDTCallout` — ISO 1101 Feature-Control-Frame (14 Charakteristiken, MMC/LMC Modifier, Datum-Refs)
- `ProcessNote` — Fertigungshinweis (8 note_types inkl. weld, surface_finish)
- `SectionViewPlan` — Schnittansichts-Definition
- `DetailViewPlan` — Detailansichts-Definition
- `ViewPlan` — Ansichtsplan mit Dimensions + GDT-Callouts
- `DimensionPlan` — Gesamtplan mit Views, Sections, Details, ProcessNotes

## 6) Dimension Strategy Engine (DSE)

### KB-Steuerung

Alle Bemassung-Entscheidungen in `_plan_milling()`, `_plan_sheet_metal()` und `_plan_turning()` sind KB-getrieben:

```python
rule_id = _kb_wants_dimension(kb, "feature_type", "dimension_key", context)
if rule_id is not None:
    # KB mandatiert diese Dimension — DimensionItem erhaelt rule_id fuer Traceability
else:
    # Fallback auf hardcodierte Logik (Rueckwaertskompatibilitaet)
```

Die Funktion `_kb_wants_dimension(kb, feature, dimension_key, context)` gibt die `rule_id` zurueck wenn eine passende Regel feuert (priority `must`/`should`), oder `None` falls kein Match.

### Unterstuetzte Features und ihre KB-Regeln

| Feature | KB-Regel ID | dim_types |
|---------|-------------|-----------|
| Aussenkontur | `overall_dimensions_required` | overall_length, overall_height, overall_depth |
| Bohrung (sichtbar) | `hole_diameter_required` | hole_diameter |
| Lochbild | `hole_location_required` | hole_pitch, hole_location_x/y |
| Gewinde | `thread_callout_required` | thread_callout |
| Langloch | `slot_complete_definition` | slot_width, slot_length, slot_location, feature_count |
| Blechteil Abwicklung | `flat_pattern_dimensions_required` | flat_length, flat_width |
| Blechdicke | `sheet_thickness_required` | sheet_thickness |
| Biegungsradius | `bend_radius_required` | bend_radius |
| Drehteil Durchmesser | `turning_diameter_overall_required` | overall_height (mit Ø-Symbol) |

### Layoutprofil-Klassifizierung

Das Layoutprofil (`milling` / `sheet_metal` / `turning`) wird an zwei Stellen identisch berechnet:

- `dimension_strategy.py:select_layout_profile_standalone()` — DSE-Pfad (in main.py)
- `step_to_pdf.py:_legacy_select_layout_profile()` — Render-Pfad (in FreeCAD-Subprozess)

**Beide Codepfade muessen synchron gehalten werden.** FreeCAD-Python kennt kein pydantic, daher kein direkter Import des DSE-Moduls. `step_to_pdf.py:select_layout_profile()` versucht den DSE-Import und faellt auf Legacy zurueck.

Klassifizierungsreihenfolge:
1. Tier 0: Dateiname-Override (`sheetmetal` im Pfad)
2. Tier 1: Gesichtserkennung (`is_sheet_metal_by_faces` + thickness ≤ 5 mm Guard)
3. Tier 1.5: Biegegeometrie (bend_count > 0)
4. Tier 2: Gemessene Wanddicke + flaches BBox-Verhaeltnis
5. Tier 3: BBox-Verhaeltnis (> 8 mm Mindestdim → immer `milling`)
6. Coaxiale Mehrdurchmesser-Zylinder → `turning` (Guard vor Sheet-Metal-Tiers)

## 7) Wissensbasis (knowledge_base.json)

**Ort**: `server/knowledge/knowledge_base.json`
**Version**: 0.2.1 — 21 Quellen, 50 Regeln

### Quellen-Hierarchie

| Tier | Bedeutung | Beispiele |
|------|-----------|-----------|
| tier_1 | Offizielle ISO/DIN-Normen | ISO 128, 129-1, 286, 1101, 2768, 22081, ... |
| tier_2 | Interne Baselines und Review-Ergebnisse | din_iso_baseline_drawform, golden_samples_review |
| tier_3 | Shopfloor-Feedback | Fertigungs- und QA-Rueckmeldungen |

### Neue Regeln (2026-03-30)

| Regel-ID | Feature | Prioritaet | Inhalt |
|----------|---------|-----------|--------|
| `hole_countersink_callout` | hole | must | Senkung: Ø + Winkel (z.B. Ø10,5 / 90°) |
| `hole_counterbore_callout` | hole | must | Stufenbohrung: Ø + Toleranz + Tiefe (z.B. Ø12 h9 / t4) |
| `hole_blind_thread_depth` | thread | must | Blindgewinde: nutzbare Gewindelaenge Pflicht (M8-6H TIEF 15) |
| `sheet_metal_k_factor_specification` | sheet_metal | should | K-Faktor bei engen Abwicklungs-Toleranzen |
| `sheet_metal_min_bend_radius_check` | sheet_metal | should | R_inner ≥ t Pruefung |
| `gdt_datum_system_establishment` | critical_feature | must | ISO 5459 Datumssystem wenn GD&T verwendet |
| `gdt_position_for_dense_hole_patterns` | hole_pattern | should | Position-Toleranz ab 4 Loechern |
| `gdt_runout_for_rotating_features` | critical_feature | should | Runout fuer rotierende Zylinder |
| `surface_roughness_process_defaults` | surface | should | Prozessabhaengige Ra-Defaults im Titelblock |
| `material_designation_unique` | title_block | must | Werkstoff muss Normbez. haben (z.B. S355J2+N) |
| `welding_symbol_complete_if_structural` | weld_joint | should | ISO 4063 Verfahrenscode + ISO 5817 Gueteklasse |
| `sheet_metal_classification_guard` | sheet_metal | must | Pruefung ob Klassifizierung korrekt (thickness ≤10mm + ≥60% Planflaechen) |

### Prioritaetskorrekturen (2026-03-30)

| Regel | Alt | Neu | Begruendung |
|-------|-----|-----|-------------|
| `hole_callout_complete_for_special_holes` | should | **must** | Falscher Bohrungstyp ohne vollstaendigen Callout |
| `thread_callout_complete` | should | **must** | Linksgewinde/Feinsteigung/Tiefe sind nicht optional |
| `bend_radius_required` | should | **must** | Bestimmt Abwicklungslaenge direkt |
| `gdt_feature_control_frame` | should | **must** | Massstoleranzen allein definieren keine Lage/Form |

### Quellen-Korrekturen (2026-03-30)

- ISO 129-1: URL-Typo `stanedard` → `standard` behoben
- ISO 2768: Part 2 als WITHDRAWN markiert, Nachfolger ISO 22081:2021 in Scope eingetragen
- ISO 261/965: Feingewinde-Pflicht explizit dokumentiert (M8×1.0 Pflicht wenn nicht Normsteigung)
- Neue Quelle `iso_22081_catalog` (Tier 1) hinzugefuegt

## 8) Zentrale Dateien und Module

### Exportkern

- `server/main.py` — FastAPI-Endpunkte, Metadatenvalidierung, DSE-Orchestrierung, `include_flat_pattern` Parameter
- `server/freecad/step_to_pdf.py` — Blattlayout, View-Erzeugung, Titleblock, Dimension-Rendering, Normkonforme Annotationen (~10.000 Zeilen)
- `server/freecad/step_feature_probe.py` — BBox, Bohrungen, Gewinde, Fasen, Blechindikatoren, Langlocher
- `server/freecad/step_unfold.py` — Headless SheetMetal-Unfold (nur wenn include_flat_pattern=true)
- `server/freecad/sheet_metal_feature_helpers.py` — Biege-Geometrie-Helfer

### Regel- und Wissenslogik

- `server/rules/dimension_strategy.py` — `select_layout_profile_standalone()`, `build_dimension_plan()`, `_kb_wants_dimension()`, `apply_overrides()`
- `server/rules/dimension_plan_schema.py` — Pydantic-Modelle fuer den JSON-Vertrag
- `server/rules/rule_engine.py` — Evaluierung von Wissensbasis-Regeln
- `server/knowledge/knowledge_base.json` — regelgetriebene Fachbasis (v0.2.1, 50 Regeln)

### Frontend-Services

- `src/services/exportService.ts` — `PdfExportOptions` inkl. `includeFlatPattern`, `requestPdfExport()`
- `src/pages/export/ExportPage.tsx` — Abwicklung-Checkbox, vollstaendiges Export-Profil

### Test-Infrastruktur

- `server/test_views.py` — View-Regression, Golden-Baseline, DSE-Meta-Pipeline, `--parallel N` Flag
- `server/tests/test_dimension_strategy.py` — 64 DSE Unit Tests
- `server/_golden/views_baseline.json` — Golden Baseline (20 Teile)
- `server/_golden/views_real_priority.json` — Kuratierte Real-Part-Golden fuer release-nahen Gate-Satz
- `server/sample_catalog.py` — Sample-Sets (baseline=20, real=91, all=111), Kategorie-Unterordner
- `server/reference_learning_gate.py` — Vergleich gegen echte STEP/PDF-Referenzen

### Debug- und Review-Artefakte

- `server/_debug/*_debug.svg`, `*_preview.png`, `*_report.json`
- `server/_debug/agent_runs/<run_id>/run_state.json`
- `server/_golden/views_baseline.json`

## 9) Test- und Qualitaetslage

### Status (2026-04-02)

| Test-Suite | Ergebnis |
|------------|----------|
| DSE Unit Tests | **64/64** bestanden |
| Baseline Regression | `20/20` bestanden (Golden Baseline regeneriert 2026-04-02) |
| All-Samples | `96/111` (15 Failures: ~5 dim-outside-bounds <50mm, Rest Timeouts/Crashes/Golden-Mismatches) |
| API Endpoint Tests | bestanden |
| Sample Catalog Tests | bestanden |

### Dimension Placement Bounds Checking (2026-04-02)

- **Overall-Dim-Clamping**: `build_dimension_svg()` reduziert iterativ den Offset via `transform_local_bounds_to_paper()` bis die Bemaessung innerhalb der Zeichenflaeche liegt
- **Feature-Dim-Suppression**: `_allocate_outside_leader_band()` gibt `suppress: True` zurueck wenn keine Position innerhalb der Zeichenflaeche moeglich ist; Loecher, Gewinde, Biegeradien und Blechdicke pruefen dieses Flag
- **Post-Placement Safety Net**: nach `build_feature_dimension_svg()` wird der zusammengefuehrte Bounding-Box gegen die Zeichenflaeche geprueft; bei Overflow > 50mm werden alle Feature-Dims fuer diese Ansicht verworfen
- 50mm-Schwelle empirisch gewaehlt: erfasst Extremfaelle (128mm, 114mm Overflow) ohne moderate Faelle zu unterdruecken

### Relevante Befehle

```powershell
cd C:\Projects\DrawformApp\server

# DSE Unit Tests (pytest)
.venv\Scripts\python.exe -m pytest tests/test_dimension_strategy.py -v

# View-Regression
.venv\Scripts\python.exe test_views.py --sample-set baseline
.venv\Scripts\python.exe test_views.py --sample-set baseline --single complex_bracket
.venv\Scripts\python.exe test_views.py --sample-set all
.venv\Scripts\python.exe test_views.py --sample-set baseline --parallel 4

# Golden Baseline regenerieren
.venv\Scripts\python.exe test_views.py --sample-set baseline --update-golden

# Quality Gate
.venv\Scripts\python.exe run_quality_gate.py --mode fast
.venv\Scripts\python.exe run_quality_gate.py --mode full --stability-runs 2

# KB validieren
.venv\Scripts\python.exe rules/rule_engine.py --validate
```

## 10) Aktuelle Entwicklungsrisiken

### 1. Renderer-Monolith

- `server/freecad/step_to_pdf.py` hat ~10.000 Zeilen
- Jede Aenderung kann Seiteneffekte auf View-Auswahl, Scale, Dimensionierung und Annotationen haben
- Neue Annotation-Renderer (GD&T, Section, Detail) erhoehen die Komplexitaet weiter

### 2. Trigger-Logik fuer neue Annotationen

- GD&T-Frames, Schnittansichten und Detailansichten haben Renderer, aber die automatische Entscheidung "wann einfuegen" ist noch nicht vollstaendig implementiert
- Die DSE-Plan-Felder (`section_views`, `detail_views`, `gdt_callouts`) sind vorbereitet, muessen aber von `build_dimension_plan()` befuellt werden

### 3. Duale Klassifizierungs-Codepfade

- `select_layout_profile_standalone()` (DSE) und `_legacy_select_layout_profile()` (step_to_pdf.py) muessen manuell synchron gehalten werden
- Bei Aenderungen an der Klassifizierungslogik: **immer beide Codepfade anpassen**

### 4. Sicherheitsstand

Behoben:
- OpenAI-Key nicht mehr im Browser — Backend-Proxy `/api/ai-insight`
- CORS-Middleware fuer localhost-Origins
- Upload-Groessenlimits konfigurierbar

Offen:
- Auth-Credentials in `localStorage` inkl. Passwort im Klartext (`src/providers/AuthProvider.tsx`)

### 5. Frontend kaschiert Backend-Ausfaelle

- Analyzer faellt auf lokale Simulation zurueck (`src/services/analyzerService.ts`)
- UI kann "funktionieren", obwohl der echte Backend-Worker ausgefallen ist

## 11) Empfohlene naechste Schritte

1. **Trigger-Logik fuer Annotationen**: `build_dimension_plan()` soll automatisch `section_views` erzeugen wenn `section_recommended=True`, und `gdt_callouts` fuer funktionskritische Bohrungen und Passflaechen
2. **K-Faktor in DSE**: KB-Regel `sheet_metal_k_factor_specification` an `_plan_sheet_metal()` anschliessen — ProcessNote mit `k_factor` erzeugen
3. **Docker + CI**: Dockerfile fuer FastAPI + FreeCAD + Xvfb, docker-compose mit Redis + PostgreSQL
4. **Auth-Migration**: localStorage → echtes JWT via Google/Microsoft OAuth
5. **PWA**: manifest.json + Service Worker (Vite PWA Plugin)
6. **Deployment**: VPS + Docker + HTTPS + Reverse Proxy

## 12) KB-Regelkreis (Closed-Loop Learning)

Ab 2026-03-31 schliesst der Agent-Workflow den Regelkreis:

```
Rendern → Critic bewertet → Failure Class → KB-Regelvorschlag → Genehmigung → KB-Update → naechster Run profitiert
```

### Wie es funktioniert

1. **Agent_critic.md** gibt fuer jede Failure mit Severity MAJOR oder SHOWSTOPPER einen strukturierten `KB_PROPOSAL` aus:
   - `MISSING_RULE` — neuer JSON-Block im `knowledge_base.json`-Format
   - `EXISTING_RULE_NOT_APPLIED` — bestehende Regel hat nicht gefeuert (Bug oder fehlender Kontext)
   - `CODE_BUG` — kein KB-Eintrag noetig, stattdessen Code-Fix

2. **Agent_report.md** sammelt alle Vorschlaege in einer `PROPOSED KB RULES`-Tabelle:
   - `READY_TO_APPLY` — direkt einpflegbar
   - `NEEDS_REVIEW` — plausibel, aber Format/Kontext unklar
   - `CODE_BUG` — Code-Fix statt KB-Eintrag
   - `DUPLICATE` — bestehende Regel deckt den Fall ab

3. Entwickler genehmigt oder lehnt ab → genehmigte Regeln werden in `knowledge_base.json` eingepflegt

### Effekt

- Jede FULL-PATH Iteration produziert nicht nur eine verbesserte Zeichnung, sondern auch neue Regeln
- Qualitaetsverbesserungen akkumulieren sich ueber Iterationen
- Bekannte Fehler werden systematisch in Regeln ueberfuehrt statt nur dokumentiert

## 13) Moegliche Erweiterungen der Agentenstruktur

Die aktuelle Struktur `Planner -> Builder -> Artifact Steward -> Critic -> Regression -> Report` ist fuer den MVP brauchbar.

### Sinnvolle Zusatzrollen

1. `Agent_triage` — sitzt vor Planner, waehlt Zielgeometrie und vermutete Failure Classes
2. `Agent_norm_review` — spezialisiert auf normnahe Zeichnungspruefung und Titelblock
3. `Agent_release` — explizites Go/No-Go Gate nach Critic + Regression
4. `Agent_knowledge_curator` — konvertiert Konstrukteur-Feedback in strukturierte KB-Regeln (bei steigendem Feedback-Volumen)

### Prozessverbesserungen

1. Failure-Class-Historie pro `target_case`
2. Vergleich Vorlauf vs. Neulauf in `run_state.json`
3. Trennung von Domain-Review und Code-Review
4. Test-Validity-Check im Regression-Agent (Baseline Freshness, Tolerance Drift, Dead Tests)
