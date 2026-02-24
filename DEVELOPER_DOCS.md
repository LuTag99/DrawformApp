# DrawformApp Developer Documentation

Dieses Dokument ist die technische Uebergabe fuer Entwickler, die am Drawform-Export weiterarbeiten.

## 1) Ziel und aktueller Scope

DrawformApp erzeugt automatisiert technische Zeichnungen aus STEP-Dateien nach DIN EN ISO.

Aktueller Funktionsumfang:
- Ansichten: Front, Top, Left, Iso (First-Angle, ISO 7200 Schriftfeld)
- Grundbemaszung inkl. Feature-Callouts (Bohrungen, Radien, Gewindekernloecher)
- Titelblock auf A3/A2 (auto-sheet)
- Layoutprofile `milling` vs `sheet_metal` mit automatischer Klassifizierung
- **Echte Abwicklung (Flat Pattern)** via FreeCAD SheetMetal Addon (V2 Unfolder)
- Normnahe Darstellung (Linienhierarchie, DIN ISO 2768-mK Toleranz, ISO 129-1 Masse)
- Pre-Export-Qualitaetscheck mit `OK/WARNUNG` im Report JSON

Nicht im aktuellen Scope:
- Vollstaendiges GD&T
- Komplexe Form- und Lagetoleranzen
- Datumserkennung aus Quelldaten

---

## 2) Architektur und Exportfluss

```
Frontend (React/Vite, src/)
    |
    v
Backend (FastAPI, server/main.py)
    |
    +-- 1. step_feature_probe.py  (FreeCAD subprocess)
    |       Geometrieanalyse: Blechdicke, Bohrungen, Biegungen,
    |       Flaechentypen -> feature_payload JSON
    |
    +-- 2. step_unfold.py         (FreeCAD subprocess, nur bei sheet_metal)
    |       FreeCAD SheetMetal V2 Unfolder -> unfold_result JSON
    |       (flat_length, flat_width, bend_lines, outline_svg)
    |
    +-- 3. step_to_pdf.py         (FreeCAD subprocess)
            Zeichnungsgenerierung: Projektionen, Masse, Titelblock,
            Abwicklung -> SVG -> PDF
```

### Wichtige Skripte

| Datei | Zweck |
|-------|-------|
| `server/freecad/step_to_pdf.py` | ~3700 Zeilen, Kern-Zeichnungslogik |
| `server/freecad/step_feature_probe.py` | Feature-Extraktion (Bohrungen, Dicke, Flachbettmuster) |
| `server/freecad/step_unfold.py` | Headless SheetMetal Unfold via FreeCAD V2-Unfolder |
| `server/main.py` | FastAPI Endpunkte, Subprocess-Orchestrierung |
| `server/test_views.py` | Regressionstests (20 Baseline-Teile) |
| `server/sample_catalog.py` | Sample-Sets `baseline|real|all` mit Deduplizierung |

---

## 3) Verzeichnisstruktur

```
server/
  freecad/
    step_to_pdf.py            # Haupt-Zeichnungslogik
    step_feature_probe.py     # Geometrieanalyse (FreeCAD Python)
    step_unfold.py            # SheetMetal Unfold (FreeCAD Python)
    _SheetMetal_addon/        # FreeCAD SheetMetal Addon (Quellcode, Git-Klon)
  templates/                  # Zeichenrahmen SVG (ISO7200 A3/A2, neutral)
  sample_catalog.py           # Sample-Sets mit Deduplizierung
  benchmark_real_parts.py     # Benchmark gegen reale Referenzzeichnungen
  _samples/
    Sheetmetals/              # Reale Blechteile (STEP + Referenz-PDFs)
    milling parts/            # Reale Fraesteile
    _debug/                   # Debug-Artefakte (SVG, PDF, report.json)
    _baseline/                # 20 Baseline-Geometrien fuer Regression
  _golden/
    views_baseline.json       # Goldenes Baseline (20 Teile, --update-golden)
  knowledge/
    knowledge_base.json       # Wissenbasis Fertigungshinweise
    QUALITY_GUIDE.md          # Qualitaetsleitfaden
  rules/
    rule_engine.py            # Regelwerk Bemaszungsentscheidungen
  test_views.py               # Haupt-Regression
  run_quality_gate.py         # Lokaler Gate-Runner
```

---

## 4) Stand der Zeichenlogik

### 4.1 Layoutprofil-Klassifizierung (`select_layout_profile`)

3-stufiges System in `step_to_pdf.py`:

| Stufe | Kriterium | Hinweis |
|-------|-----------|---------|
| Tier 0 | Dateiname enthaelt `sheetmetal` | Override, rueckwaertskompatibel |
| Tier 1 | `is_sheet_metal_by_faces=True` **und** `measured_thickness_mm <= 5mm` | Dicke-Guard noetig! Ohne Guard werden dicke Fraesteile mit Verrundungen falsch klassifiziert |
| Tier 2 | BBox-Verhaeltnis (Dicke/mittlere Dim < 0.15) | Fallback |

**Kritisch:** Tier 1 ohne Dicke-Guard fuehrt zu Fehlklassifizierung.

### 4.2 Blechdicken-Messung (`measure_wall_thickness`)

Antiparallele Plane-Flaechenpaare finden, minimalen Abstand messen.
Ergebnis: `measured_thickness_mm` in Feature-Payload.
Vorteil: exakter als BBox-Minimalwert (der oft die gebogene Gesamttiefe zeigt).

### 4.3 Bohrungserkennung (`collect_circle_data`)

**50%-Umfangsfilter** (kein Achsrichtungsfilter!):
- Akzeptiert: Vollbohrungen (100%), Langloch-Halbkreise (50%)
- Verwirft: Biegeboegen (25%), Fasen/Verrundungen (<=45%)
- **Nicht unter 50% gehen** — bei 49% Regressionen in `complex_bracket` + `flanged_manifold`
- **Kein Achsfilter** — zu streng fuer Wellen/Zylinder (Endkreise parallel zur Laengsachse)

### 4.4 Echte Abwicklung via FreeCAD SheetMetal Addon

**Addon:** [shaise/FreeCAD_SheetMetal](https://github.com/shaise/FreeCAD_SheetMetal)
**Installiert in:** `C:\Users\Startklar\AppData\Roaming\FreeCAD\Mod\SheetMetal\`
**Quellkopie:** `server/freecad/_SheetMetal_addon/`
**Abhaengigkeit:** `networkx` (in FreeCAD Python installiert)

Ablauf in `step_unfold.py`:
1. STEP importieren, Shape mit `removeSplitter()` verfeinern
2. Groesste ebene Flaeche als Basisflaeche bestimmen
3. `SheetMetalNewUnfolder.getUnfold(bac, obj, face_name)` aufrufen
4. Aus 3D-BoundBox: Masse sortieren (XYZ) → `flat_length` (groesste), `flat_width` (mittlere), `thickness` (kleinste)
5. Biegelinien + SVG-Umriss exportieren

Integration in `step_to_pdf.py`:
- `_run_unfold_subprocess()` startet `step_unfold.py` als FreeCAD-Subprocess
- `build_flat_pattern_overlay()` erhalt `unfold_result` Parameter
- Priority 1: echte SVG-Kontur rendern wenn `unfold_result.ok == True`
- Fallback: mathematische Naeherung bei `complex_geometry=False`
- Text-only bei `complex_geometry=True`

**Gemessene Ergebnisse:**
- Halteblech Lackierpistole: **105,54 × 47,77 mm**, 4 Biegungen
- Abdeckblech Motorstecker 2: **166,54 × 115,0 mm**, 2 Biegungen

### 4.5 Bauteilname aus Dateinamen (`_extract_part_name`)

Regex: `re.sub(r"^\d+_", "", stem)` → Praefixzahl entfernen (beliebig lang)
Dann: `re.sub(r"_V\d+[\.\d]*$", "", stem, flags=re.IGNORECASE)` → Versionssuffix entfernen

Beispiel: `202500521_Halteblech Lackierpistole_V1.0.STEP` → `Halteblech Lackierpistole`

### 4.6 Normen und Symbole

| Eigenschaft | Wert |
|-------------|------|
| Toleranzstring | `DIN ISO 2768-mK` (Masz + Form K-Klasse) |
| Durchmessersymbol | `\u00D8` (Oe, U+00D8) — **nicht** `\u2300` (rendert als Kaestchen in FreeCAD PDF-Fonts) |
| Projektionsmethode | DIN EN ISO (First-Angle) |
| Biegelinie-Strichtyp | `stroke-dasharray="2.5 1.0"`, blau `rgb(40,40,160)` |
| Pfeilspitzen Masse | ISO 129-1: `<polygon>` gefuellt, Laenge 3×Strichbreite |

### 4.7 Normkonforme Bemaßung (ISO 129-1)

- Kein „LOCHABSTAND"-Label auf Masslinien (nicht normkonform, entfernt)
- Nur Zahlen als Masstext (kein beschreibender Text)
- K-Faktor erscheint einmal in `process_lines`, nicht doppelt

---

## 5) Wissensbasis / Rule-Engine

Ziel: reproduzierbare Entscheidungen, welche Masse gesetzt werden.

- Daten: `server/knowledge/knowledge_base.json`
- Qualitaetsleitfaden: `server/knowledge/QUALITY_GUIDE.md`
- Validator: `server/knowledge/validate_knowledge_base.py`
- Engine: `server/rules/rule_engine.py`

```powershell
cd server
python knowledge/validate_knowledge_base.py
python rules/rule_engine.py --feature hole --ctx visible=true
```

---

## 6) Tests und Qualitaetsgate

### Baseline-Tests (20 Teile)

```powershell
cd server
# Schnelltest
python test_views.py --sample-set baseline

# Stabilitaetstest (3 Laeufe)
python test_views.py --sample-set baseline --stability-runs 3

# Golden-Baseline aktualisieren (nach bewussten Aenderungen)
python test_views.py --sample-set baseline --update-golden

# Real-Part-Benchmark
python benchmark_real_parts.py --sample-set real

# Vollstaendiger Quality-Gate
python run_quality_gate.py --stability-runs 2 --iterations 3
```

**Aktueller Stand: 20/20 (Feb 2026)**

### Was `test_views.py` prueft

- Hauptachse und Ausrichtung
- Feature-Erwartungen (Bohrungen, Flat-Pattern-Flag)
- Zeichnungsflaechen-Fit und kein Overflow
- Normmarker im SVG
- Einheitenlose Masstexte
- Mittellinien bei Bohrungsfeatures
- Stabilitaet ueber Mehrfachlaeufe

### Golden-Baseline aktualisieren

Nach absichtlichen Aenderungen der Zeichnungslogik (z.B. neue Erkennungsregeln):
```powershell
python test_views.py --sample-set baseline --update-golden
```
Dadurch wird `_golden/views_baseline.json` neu geschrieben. Dann regulaer testen.

---

## 7) Lokales Setup

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

## 8) Bekannte Stolpersteine

| Problem | Loesung |
|---------|---------|
| `Permission denied` beim PDF-Export | PDF im Viewer gelockt; neuen Dateinamen oder Viewer schliessen |
| Leere/fehlerhafte Ausgabe | `server/_debug/*_debug.svg` und `*_report.json` pruefen |
| `feature_probe_unavailable` in step_to_pdf.py | Direkt-Aufruf ohne Feature-Probe; in Produktion laeuft Probe zuerst |
| Abwicklung zeigt falschen Wert (zu gross) | `compute_flat_pattern()` in probe.py: Normalenbuckets pruefen, kein Summen-Fehler |
| SheetMetal Unfold schlaegt fehl | Geometrie nicht erkannt als SheetMetal-Topologie; fallback auf mathematische Naeherung |
| Durchmesserzeichen als Kaestchen im PDF | `\u2300` statt `\u00D8` verwendet; nur U+00D8 verwenden |
| Dicke Fraesteile als `sheet_metal` klassifiziert | Tier-1 ohne `measured_thickness_mm <= 5mm` Guard; Guard immer pruefen |
| Regressionsfehler `NoneType.get` bei sheet_metal | `feature_payload.get("flat_pattern")` kann `None` sein; immer `or {}` verwenden |

---

## 9) Naechste sinnvolle Schritte

1. **Masslinien-Alignment verbessern** — Extension Lines sollen genau an die View-Kanten anschliessen (bekanntes visuelles Problem)
2. **Mittellinien bei Bohrungen verbessern** — ISO 128-2 konforme Strich-Punkt-Linie
3. **Abwicklungs-SVG-Kontur optimieren** — FreeCAD-SVG-Ausgabe hat teils unnoetigen transform="scale(1,-1)"; normalisieren
4. **Gewindeerkennung ausbauen** — Kernloecher (M5=4,2mm, M6=5,0mm, M8=6,8mm) bereits erkannt; Gewinde-Annotation noch fehlend
5. **Regelwerk anreichern** — weitere reale Fertigungsfaelle einarbeiten
6. **CI auf GitHub** — automatischen Test-Lauf einrichten
