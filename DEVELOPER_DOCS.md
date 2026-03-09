# DrawformApp Developer Documentation

Dieses Dokument ist die technische Uebergabe fuer Entwickler, die am Drawform-Export weiterarbeiten.

## 1) Ziel und aktueller Scope

DrawformApp erzeugt automatisiert technische Zeichnungen aus STEP-Dateien nach DIN EN ISO.

Aktueller Funktionsumfang (Backend):
- Ansichten: Front, Top, Left, Iso (First-Angle, ISO 7200 Schriftfeld)
- **Deterministische Bemaszung via Dimension Strategy Engine (DSE)** — plan-gesteuert, regelbasiert
- Feature-Callouts (Bohrungen, Gewindekernloecher, Biegeradien)
- Titelblock auf A3/A2 (auto-sheet)
- Layoutprofile `milling` vs `sheet_metal` mit automatischer Klassifizierung
- **Echte Abwicklung (Flat Pattern)** via FreeCAD SheetMetal Addon (V2 Unfolder)
- **DXF-Export** der Abwicklung via `/api/export-dxf`
- **Foto-zu-3D Rekonstruktion** via `/api/reconstruct` (Voxel-Carving → STL → STEP)
- Normnahe Darstellung (Linienhierarchie, DIN ISO 2768-mK Toleranz, ISO 129-1 Masse)
- Pre-Export-Qualitaetscheck mit `OK/WARNUNG` im Report JSON
- LLM-Override-Hook: strukturierte JSON-Instruktionen ueberschreiben DSE-Baseline

Aktueller Funktionsumfang (Frontend):
- Glassmorphism-UI (iOS 26 Glass Look), React 19 + TypeScript + Vite 7
- Auth-Flow via LocalStorage (Stub, kein echtes Backend)
- Dashboard mit AI-Insights (OpenAI), SVG-Performance-Chart
- Bemaessungslabor (`/analyzer`): CAD/Bild-Upload, Backend-Job-Polling, Dimensionsanzeige
- Rekonstruktion (`/reconstruct`): 5-Foto-Upload (5 Ansichten), Backend-Job-Polling, Download (STL/STEP/PDF)
- Export-Center (`/export`): PDF + DXF Export, Inline-Preview, Log-Viewer
- Projektseite (`/projects`): Demo-Daten (noch kein echtes Backend)
- Profil (`/profile`): Avatar-URL, Passwortwechsel

Nicht im aktuellen Scope:
- Vollstaendiges GD&T
- Komplexe Form- und Lagetoleranzen
- Datumssymbole und Positionen im Schriftfeld
- Echte Datenbank-Auth (OAuth, JWT) — noch LocalStorage-basiert

---

## 2) Architektur und Exportfluss

```
Frontend (React/Vite, src/)
    |
    v
Backend (FastAPI, server/main.py)
    |
    +-- 1. step_feature_probe.py        (FreeCAD subprocess)
    |       Geometrieanalyse: Blechdicke, Bohrungen, Biegungen,
    |       Flaechentypen → feature_payload JSON
    |
    +-- 2. DSE (rules/dimension_strategy.py)   (pure Python, kein FreeCAD)
    |       select_layout_profile_standalone() → "milling" | "sheet_metal"
    |       build_dimension_plan()             → DimensionPlan JSON
    |       Schreibt features + dimension_plan in meta.json
    |
    +-- 3. step_unfold.py               (FreeCAD subprocess, nur bei sheet_metal)
    |       FreeCAD SheetMetal V2 Unfolder → unfold_result JSON
    |       (flat_length, flat_width, bend_lines, outline_svg)
    |
    +-- 4. step_to_pdf.py               (FreeCAD subprocess)
            Liest dimension_plan aus meta.json
            Plan-gesteuerte Zeichnungsgenerierung: Projektionen, Masse, Titelblock,
            Abwicklung → SVG → PDF
            Fallback: hardcoded Logik wenn kein Plan vorhanden
```

### Wichtige Skripte

| Datei | Zweck |
|-------|-------|
| `server/freecad/step_to_pdf.py` | ~3600 Zeilen, Kern-Zeichnungslogik |
| `server/freecad/step_feature_probe.py` | Feature-Extraktion (Bohrungen, Dicke, Flachbettmuster) |
| `server/freecad/step_unfold.py` | Headless SheetMetal Unfold via FreeCAD V2-Unfolder |
| `server/main.py` | FastAPI Endpunkte, DSE-Orchestrierung, Subprocess-Steuerung |
| `server/rules/dimension_strategy.py` | DSE: `build_dimension_plan()`, `select_layout_profile_standalone()`, `apply_overrides()` |
| `server/rules/dimension_plan_schema.py` | Pydantic-Schema: `DimensionPlan`, `ViewPlan`, `DimensionItem`, `ProcessNote` |
| `server/rules/rule_engine.py` | Wissensbasis-Regelwerk (ISO/DIN-Regeln → Bemaszungsentscheidungen) |
| `server/test_views.py` | Regressionstests (48 Teile: 20 Baseline + 28 Real) |
| `server/tests/test_dimension_strategy.py` | 35 DSE-Unit-Tests |
| `server/sample_catalog.py` | Sample-Sets `baseline=20 | real=27 | all=47` mit Deduplizierung |

---

## 3) Verzeichnisstruktur

```
server/
  freecad/
    step_to_pdf.py            # Haupt-Zeichnungslogik
    step_feature_probe.py     # Geometrieanalyse (FreeCAD Python)
    step_unfold.py            # SheetMetal Unfold (FreeCAD Python)
    _SheetMetal_addon/        # FreeCAD SheetMetal Addon (Quellkopie)
  rules/
    rule_engine.py            # Wissensbasis-Regelauswertung
    dimension_strategy.py     # DSE — build_dimension_plan(), apply_overrides()
    dimension_plan_schema.py  # Pydantic-Schema fuer DimensionPlan
    README.md                 # Dokumentation rules/
  tests/
    __init__.py
    test_dimension_strategy.py  # 35 DSE-Unit-Tests
  templates/                  # Zeichenrahmen SVG (ISO7200 A3/A2)
  knowledge/
    knowledge_base.json       # Wissensbasis ISO/DIN Regelwerk
    QUALITY_GUIDE.md          # Qualitaetsleitfaden Datenqualitaet
  docs/
    DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md
  _samples/
    *.stp                     # 20 Baseline-Geometrien
    Sheetmetals/              # Reale Blechteile (STEP)
    milling parts/            # Reale Fraesteile
  _golden/
    views_baseline.json       # Goldenes Baseline (--update-golden)
  _debug/                     # Debug-Artefakte (SVG, PDF, report JSON, PNG-Preview)
  sample_catalog.py
  test_views.py               # Haupt-Regression
  run_quality_gate.py         # Lokaler Gate-Runner
  main.py                     # FastAPI App
```

---

## 4) Dimension Strategy Engine (DSE)

Die DSE ist das Herzstück der Bemaszungslogik. Sie laeuft in `main.py` **vor** dem FreeCAD-Subprocess und erzeugt einen `DimensionPlan` — einen JSON-Vertrag, der beschreibt *was* bemaßt wird (nicht *wie*).

### Grundsatz

```
Deterministisch:  gleicher Input → immer gleicher Plan
Testbar:          35 Unit-Tests, kein FreeCAD noetig
LLM als Override: Baseline unveraendert, KI liefert nur Korrekturen
```

### DimensionPlan-Format

```json
{
  "part_type": "milling",
  "detail_level": 1,
  "datum_system": {"A": "Z", "B": "X", "C": "Y"},
  "views": [
    {
      "view_name": "Front",
      "dimensions": [
        {"dim_type": "overall_length", "axis": "H", "value_mm": 200.0, "rule_id": "overall_dimensions_required"},
        {"dim_type": "hole_diameter",  "value_mm": 14.0, "label": "Ø14", "rule_id": "hole_diameter_required"},
        {"dim_type": "hole_pitch",     "axis": "H", "value_mm": 180.0, "priority": "must"}
      ]
    },
    {
      "view_name": "Top",
      "dimensions": [
        {"dim_type": "overall_depth", "axis": "V", "value_mm": 12.0}
      ]
    }
  ],
  "process_notes": [],
  "overrides_applied": []
}
```

Der Plan beschreibt Absichten — der Renderer in `step_to_pdf.py` entscheidet wie (Position, Pfeil, Textgroesse).

### Detail-Level

| Level | Name | Inhalt |
|-------|------|--------|
| 1 | Manufacturing-minimal (default) | L × B × H, Loch-Ø, Lochabstand, Biegeradius |
| 2 | Inspection-ready | + Left-View-Tiefe, Lochpositionen von Datum |
| 3 | Customer-spec | + alle Prozessnotizen (t, Ri, K-Faktor) |

### Teiltypen

| Teiltyp | Hauptbemaßungsflaeche | Besonderheiten |
|---------|----------------------|----------------|
| `milling` | Front: L+H; Top: Tiefe | Lochkoordinaten von Datum A/B |
| `sheet_metal` | Abwicklung: flat_length, flat_width | Prozessnotizen (t, Ri, K); 3D-Ansicht sekundaer |
| `turning` | Front: Ø + Laengen | Placeholder; Symmetrieachse als Datum |

### Datumssystem

Wird automatisch aus der Geometrie abgeleitet:
- **A** = Flaeche senkrecht zur `thickness_axis` (groesste ebene Aufspannflaeche)
- **B** = Flaeche senkrecht zur `longest_axis` (Referenzkante)
- **C** = dritte orthogonale Achse

### LLM-Overrides

```python
from rules.dimension_strategy import apply_overrides

plan = apply_overrides(plan, [
    # Dimension hinzufuegen
    {"action": "add",    "target_view": "Front",
     "dimension": {"dim_type": "pocket_depth", "target_view": "Front", "value_mm": 5.0}},
    # Dimension entfernen
    {"action": "remove", "target_view": "Front", "dim_type": "hole_pitch"},
    # Dimension aendern
    {"action": "modify", "target_view": "Front", "dim_type": "hole_diameter",
     "changes": {"label": "Ø14 H7"}},
])
# Jeder Override ist in plan.overrides_applied protokolliert
```

### Integration in step_to_pdf.py

`step_to_pdf.py` liest den Plan aus `meta["dimension_plan"]`:

```python
dim_plan = meta.get("dimension_plan")  # dict oder None
if dim_plan:
    # Plan-gesteuert: show_horizontal/show_vertical aus Plan
    view_plan = next((v for v in dim_plan["views"] if v["view_name"] == name), None)
    show_horizontal = any(d["axis"]=="H" and d["dim_type"].startswith("overall") ...)
else:
    # Fallback: bestehende hardcoded Logik (rueckwaertskompatibel)
```

**Wichtig:** `step_to_pdf.py` laeuft in FreeCADs Python-Umgebung — **kein Pydantic** dort. Der Plan kommt als plain dict via `model_dump()`.

---

## 5) Stand der Zeichenlogik

### 5.1 Layoutprofil-Klassifizierung

4-stufiges System (in `step_to_pdf.py` und `rules/dimension_strategy.py`):

| Stufe | Kriterium | Hinweis |
|-------|-----------|---------|
| Tier 0 | Dateiname enthaelt `sheetmetal` | Override, rueckwaertskompatibel |
| Tier 1 | `is_sheet_metal_by_faces=True` **und** `measured_thickness_mm ≤ 5 mm` | Dicke-Guard noetig! Ohne Guard werden dicke Fraesteile falsch klassifiziert |
| Tier 1.5 | `flat_pattern.bend_count > 0` | Staerkstes Signal, kein Guard noetig |
| Tier 2 | `measured_thickness_mm` in [0,3 … 5] + kein Konus + `pocket_ratio ≤ 3` | Lasetrteile ohne Biegung |
| Tier 3 | BBox-Verhaeltnis (`thickness / mid_dim < 0,15`) | Fallback |

`select_layout_profile_standalone()` in `dimension_strategy.py` ist die pure-Python-Version (nutzt `fp["bbox_mm"]` statt FreeCAD BoundBox).

### 5.2 Blechdicken-Messung (`measure_wall_thickness`)

Antiparallele Plane-Flaechenpaare finden, minimalen Abstand messen.
Ergebnis: `measured_thickness_mm` in Feature-Payload.
Vorteil: exakter als BBox-Minimalwert (der oft die gebogene Gesamttiefe zeigt).

### 5.3 Bohrungserkennung (`collect_circle_data`)

**50%-Umfangsfilter** (kein Achsrichtungsfilter!):
- Akzeptiert: Vollbohrungen (100%), Langloch-Halbkreise (50%)
- Verwirft: Biegeboegen (25%), Fasen/Verrundungen (≤45%)
- **Nicht unter 50% gehen** — bei 49% Regressionen in `complex_bracket` + `flanged_manifold`
- **Kein Achsfilter** — zu streng fuer Wellen/Zylinder (Endkreise parallel zur Laengsachse)

### 5.4 Echte Abwicklung via FreeCAD SheetMetal Addon

**Addon:** [shaise/FreeCAD_SheetMetal](https://github.com/shaise/FreeCAD_SheetMetal)
**Installiert in:** `C:\Users\Startklar\AppData\Roaming\FreeCAD\Mod\SheetMetal\`
**Quellkopie:** `server/freecad/_SheetMetal_addon/`
**Abhaengigkeit:** `networkx` (in FreeCAD Python installiert)

Ablauf in `step_unfold.py`:
1. STEP importieren, Shape mit `removeSplitter()` verfeinern
2. Groesste ebene Flaeche als Basisflaeche bestimmen
3. `SheetMetalNewUnfolder.getUnfold(bac, obj, face_name)` aufrufen
4. Aus 3D-BoundBox: Masse sortieren (XYZ) → `flat_length` (groesste), `flat_width` (mittlere)
5. Koordinatensystem normalisieren: XMin=YMin=0 vor SVG-Projektion
6. Biegelinien + SVG-Umriss exportieren

Integration in `step_to_pdf.py`:
- `_run_unfold_subprocess()` startet `step_unfold.py` als FreeCAD-Subprocess
- `build_flat_pattern_overlay()` erhaelt `unfold_result` Parameter
- Priority 1: echte SVG-Kontur rendern wenn `unfold_result.ok == True`
- Fallback: mathematische Naeherung bei `complex_geometry=False`
- Text-only bei `complex_geometry=True`

### 5.5 Bauteilname aus Dateinamen (`_extract_part_name`)

Regex: `re.sub(r"^\d+_", "", stem)` → Praefixzahl entfernen (beliebig lang)
Dann: `re.sub(r"_V\d+[\.\d]*$", "", stem, flags=re.IGNORECASE)` → Versionssuffix entfernen

Beispiel: `202500521_Halteblech Lackierpistole_V1.0.STEP` → `Halteblech Lackierpistole`

### 5.6 Normen und Symbole

| Eigenschaft | Wert |
|-------------|------|
| Toleranzstring | `DIN ISO 2768-mK` (Masz + Form K-Klasse) |
| Durchmessersymbol | `\u00D8` (Ø, U+00D8) — **nicht** `\u2300` (rendert als Kaestchen in FreeCAD PDF-Fonts) |
| Projektionsmethode | DIN EN ISO (First-Angle) |
| Biegelinie-Strichtyp | `stroke-dasharray="2.5 1.0"`, blau `rgb(40,40,160)` |
| Pfeilspitzen Masse | ISO 129-1: `<polygon>` gefuellt, Laenge 3×Strichbreite |
| Masszahl | Deutsch formatiert (Komma als Dezimalzeichen) via `format_de_number()` |

### 5.7 Normkonforme Bemaßung (ISO 129-1)

- Kein „LOCHABSTAND"-Label auf Masslinien (nicht normkonform, entfernt)
- Nur Zahlen als Masstext (kein beschreibender Text)
- K-Faktor erscheint einmal in `process_lines`, nicht doppelt
- DSE verhindert Doppelbemaszung via `_deduplicate()`: gleiche (dim_type, value_mm) nur einmal

---

## 6) Wissensbasis / Rule-Engine

Ziel: reproduzierbare, nachvollziehbare Entscheidungen, welche Masse gesetzt werden.

- Daten: `server/knowledge/knowledge_base.json`
- Qualitaetsleitfaden: `server/knowledge/QUALITY_GUIDE.md`
- Validator: `server/knowledge/validate_knowledge_base.py`
- Engine: `server/rules/rule_engine.py`
- DSE: `server/rules/dimension_strategy.py`

Regeln benoetigen mind. 2 Reviewer und `tier_1`- oder `tier_2`-Quelle.
Jede Bemaszungsentscheidung traegt `rule_id` fuer Rueckverfolgbarkeit.

```powershell
cd server
python knowledge/validate_knowledge_base.py
python rules/rule_engine.py --feature hole --ctx visible=true
python rules/rule_engine.py --validate
```

---

## 7) Tests und Qualitaetsgate

### Uebersicht (Stand Feb 2026)

| Test-Suite | Ergebnis | Kommando |
|-----------|----------|---------|
| DSE Unit-Tests | **35/35** | `python -m unittest tests.test_dimension_strategy -v` |
| Norm-Profil | 7/7 | `python -m unittest test_norm_profile` |
| API-Endpoints | 3/3 | `python -m unittest test_api_endpoints` |
| Regression Baseline | **20/20** | `python test_views.py --sample-set baseline` |
| Regression Real+All | **41/48** | `python test_views.py --sample-set all` |

Real-Parts-Failures (41/48, vorbestehend, nicht DSE-bedingt):
- 5× Abwicklungs-Flange-Sum-Validator zu streng fuer komplexe Blechteile
- 2× FreeCAD-Crash (exit `0xC0000409` = Stack Overflow bei Schweiss-/Einpress-Geometrien)

### Testkommandos

```powershell
cd server

# DSE Unit-Tests
python -m unittest tests.test_dimension_strategy -v

# View-Regression
python test_views.py --sample-set baseline          # 20 Baseline-Teile
python test_views.py --sample-set real              # 27 reale Kundenteile
python test_views.py --sample-set all               # alle 48 Teile

# Golden-Baseline aktualisieren (nach bewussten Aenderungen)
python test_views.py --sample-set all --update-golden

# Stabilitaetstest (3 Laeufe)
python test_views.py --sample-set baseline --stability-runs 3

# Vollstaendiger Quality-Gate
python run_quality_gate.py --stability-runs 2 --iterations 3
```

### Was `test_views.py` prueft

- Hauptachse und Ausrichtung (longest_axis, alignment)
- Feature-Erwartungen (Bohrungen, Flat-Pattern-Flag)
- Zeichnungsflaechen-Fit und kein Overflow
- Normmarker im SVG, einheitenlose Masstexte
- Mittellinien bei Bohrungsfeatures
- **DSE-Plan-Check** (`check_dimension_plan()`) — aktivierbar per `"dse_check": True` im EXPECTED-Dict
- Abwicklungs-Qualitaet (Kontur, Biegelinien, Dimensionierung)
- Titelblock (ISO 7200 Pflichtfelder, Datumsformat, Masstabsformat)
- Stabilitaet ueber Mehrfachlaeufe

### DSE-Check fuer einzelne Teile aktivieren

Im `EXPECTED`-Dict in `test_views.py`:
```python
EXPECTED = {
    "flange": {
        "dse_check": True,   # Aktiviert check_dimension_plan()
        "min_hole_count": 6,
        ...
    },
}
```

---

## 8) Lokales Setup

### Backend

```powershell
cd C:\Projects\DrawformApp\server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000
```

### Frontend

```powershell
cd C:\Projects\DrawformApp
npm install
npm run dev
```

### FreeCAD SheetMetal Addon (bereits installiert)

```powershell
# Addon liegt in:
# C:\Users\Startklar\AppData\Roaming\FreeCAD\Mod\SheetMetal\
# Quellkopie: server/freecad/_SheetMetal_addon/

# networkx (in FreeCAD Python, bereits installiert):
# "C:\Program Files\FreeCAD 1.0\bin\python.exe" -m pip install networkx
```

---

## 9) Bekannte Stolpersteine

| Problem | Loesung |
|---------|---------|
| `Permission denied` beim PDF-Export | PDF im Viewer gelockt; neuen Dateinamen oder Viewer schliessen |
| Leere/fehlerhafte Ausgabe | `server/_debug/*_debug.svg` und `*_report.json` pruefen |
| `feature_probe_unavailable` in step_to_pdf.py | Direkt-Aufruf ohne Feature-Probe; in Produktion laeuft Probe zuerst |
| DSE-Plan fehlt im Report | `main.py` konnte Feature-Probe nicht ausfuehren → DSE-Fehler ist non-fatal, Fallback greift |
| Abwicklung zeigt falschen Wert | `compute_flat_pattern()` in probe.py: Normalenbuckets pruefen |
| SheetMetal Unfold schlaegt fehl | Geometrie nicht erkannt als SheetMetal-Topologie; Fallback auf Naeherung |
| Durchmesserzeichen als Kaestchen im PDF | `\u2300` statt `\u00D8` verwendet; nur U+00D8 (Ø) verwenden |
| Dicke Fraesteile als `sheet_metal` klassifiziert | Tier-1 ohne `measured_thickness_mm ≤ 5mm` Guard; Guard immer pruefen |
| FreeCAD-Crash exit `3221226505` | Stack Overflow in FreeCAD (0xC0000409); Geometrie zu komplex fuer TechDraw |
| Pydantic-Import in FreeCAD schlaegt fehl | DSE laeuft in `main.py` (venv), nicht in FreeCAD-Python; Plan als dict via `model_dump()` uebergeben |

---

## 10) Naechste sinnvolle Schritte

### Backend
1. **DSE in test_views.py aktivieren** — `"dse_check": True` fuer konkrete Teile im EXPECTED-Dict eintragen und golden baseline damit aktualisieren
2. **LLM-Override-Endpoint** — `/api/export` um `overrides: list[dict]` Parameter erweitern; DSE-Plan vor Subprocess patchen
3. **Abwicklungs-Flange-Sum-Validator fixen** — 5 Failures bei komplexen Blechteilen: Validator-Logik an tatsaechliche SVG-Segmente anpassen
4. **FreeCAD-Crash-Teile** — `logiBOT_02_Abdeckblech Hinten_Einpress` und `_Schweiss`: Ursache Stack Overflow pruefen; ggf. Geometrie vereinfachen vor Import
5. **Turning-Teiltyp ausbauen** — DSE hat Placeholder; Symmetrieachse als Datum, Ø-Dominanz implementieren
6. **Regelwerk anreichern** — weitere ISO/DIN-Regeln in `knowledge_base.json` eintragen (Taschen, Stufen, Passungen)
7. **CI auf GitHub** — automatischen Test-Lauf einrichten (`tests.test_dimension_strategy` und ggf. Mock-basierte Regression)

### Frontend
8. **Auth-Backend anbinden** — `AuthProvider` gegen echtes OAuth/JWT austauschen (Google + Microsoft via `authlib`)
9. **Passwort-Sicherheit** — Passwort nicht im Klartext in localStorage (aktuelles `credentials.password` ist unverschluesselt)
10. **OpenAI-Key absichern** — `VITE_OPENAI_API_KEY` laeuft im Browser-Bundle; Server-Proxy einrichten damit Key serverseitig bleibt
11. **InputField Accessibility** — `<label>` mit `htmlFor` + `id` am `<input>` verbinden (aktuell keine implizite Verknuepfung)
12. **Projektseite** — Demo-Daten durch echten `/api/projects`-Endpunkt ersetzen
13. **Docker** — FreeCAD + FastAPI containerisieren (Xvfb-Wrapper fuer PDF-Export benoetigt)
