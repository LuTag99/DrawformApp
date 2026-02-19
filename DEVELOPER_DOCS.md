# DrawformApp Developer Documentation

Dieses Dokument ist die technische Uebergabe fuer Entwickler, die am Drawform-Export weiterarbeiten.

## 1) Ziel und aktueller Scope

DrawformApp erzeugt automatisiert technische Zeichnungen aus STEP-Dateien.

Aktueller Funktionsumfang:
- Ansichten: Front, Top, Left, Iso
- Grundbemaszung inkl. Feature-Callouts
- Titelblock auf A3/A2 (auto-sheet)
- Normnahe Darstellung (Linienhierarchie, Toleranzhinweise)
- Pre-Export-Qualitaetscheck mit `OK/WARNUNG`

Nicht im aktuellen Scope:
- Vollstaendiges GD&T
- Komplexe Form- und Lagetoleranzen
- Datumserkennung aus Quelldaten

## 2) Architektur

- Frontend: React/Vite (`src/`)
- Backend: FastAPI (`server/main.py`)
- CAD-Export: FreeCAD-Skript (`server/freecad/step_to_pdf.py`)

Exportfluss:
1. `/api/export` nimmt STEP + Metadaten an
2. STEP wird durch FreeCAD geladen
3. Projektionen und Blattlayout werden berechnet
4. SVG wird aufgebaut (Geometrie, Masse, Titelblock)
5. SVG wird nach PDF gerendert
6. Debug-Artefakte + Report werden geschrieben

## 3) Relevante Verzeichnisse

```
server/
  freecad/                  # Kernlogik STEP -> SVG -> PDF
  templates/                # Zeichenrahmen (ISO7200-aehnlich)
  sample_catalog.py         # Baseline/Real/All Sample-Sets mit Deduplizierung
  benchmark_real_parts.py   # Lokaler PDF-Benchmark gegen reale Referenzzeichnungen
  _samples/                 # Referenzteile fuer Regression
  _golden/                  # Golden-Baseline fuer Views/Qualitaet
  _debug/                   # Debug SVG/PDF/Reports
  knowledge/                # Wissensbasis + Datenqualitaetsregeln
  rules/                    # Rule-Engine fuer Bemaszungsentscheidungen
  test_views.py             # Haupt-Regression inkl. Norm-/Qualitaetschecks
  run_quality_gate.py       # Lokaler Gate-Runner (Loops)
```

## 4) Stand der Zeichenlogik (wichtig)

Datei: `server/freecad/step_to_pdf.py`

Aktueller Stand:
- First-angle Projektion mit deterministischem Tie-Break
- Arc- und Circle-basierte Mittellinien
- Feature-Callouts mit Kollisionsvermeidung
- Linienstaerkenprofil (sichtbar/verdeckt/mittellinie/masz)
- Auto-Sheet-Logik (`sheet=auto`) mit A3->A2 Umschaltung bei grossen Teilen
- Layoutprofile `milling` vs `sheet_metal`
- Sheet-metal Flat-Pattern Fallback-Bereich (wenn SheetMetal-Modul nicht verfuegbar)
- Toleranznormalisierung (`ISO 2768-f/m/c`, Default `ISO 2768-m`)
- Zusatzeintraege im Schriftfeldbereich:
  - Material (optional)
  - Entgrathinweis
  - Projektion
  - Allgemeintoleranz
- Pre-Export-Pruefung im Report:
  - fehlende Aussenmasse
  - fehlende Durchmesserangabe
  - doppelte Masse
  - moegliche Ueberlagerung
  - fehlende Mittellinien bei Bohrungen

## 5) Wissensbasis / Rule-Engine

Ziel: reproduzierbare Entscheidungen, welche Masse gesetzt werden.

- Daten: `server/knowledge/knowledge_base.json`
- Qualitaetsleitfaden: `server/knowledge/QUALITY_GUIDE.md`
- Validator: `server/knowledge/validate_knowledge_base.py`
- Engine: `server/rules/rule_engine.py`

Beispiele:

```powershell
cd server
python knowledge/validate_knowledge_base.py
python rules/rule_engine.py --feature hole --ctx visible=true
```

## 6) Tests und Qualitaetsgate

Wichtigste Tests:

```powershell
cd server
python test_views.py --sample-set baseline
python test_views.py --sample-set baseline --stability-runs 3 --stability-sleep-ms 100
python test_views.py --sample-set baseline --update-golden
python test_views.py --sample-set real --update-golden
python test_views.py --sample-set all --update-golden
python benchmark_real_parts.py --sample-set real
python -m unittest test_sample_catalog.py
python run_quality_gate.py --stability-runs 2 --iterations 3
```

Was `test_views.py` aktuell prueft:
- Ausrichtung/Orientierung
- Feature-Erwartungen
- Zeichnungsflaechen-Fit und Overflow
- Normmarker im SVG
- Unitless-Masztexte
- Mittellinien bei Bohrungsfeatures
- Stabilitaet ueber Mehrfachlaeufe

## 7) Lokales Setup (Kurzfassung)

```powershell
cd C:\Projects\DrawformApp\server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000
```

Frontend:

```powershell
cd C:\Projects\DrawformApp
npm install
npm run dev
```

## 8) Bekannte Stolpersteine

- `Permission denied` beim PDF-Export:
  - PDF ist oft im Viewer gelockt; neuen Dateinamen verwenden oder Viewer schliessen.
- Leere/fehlerhafte Ausgabe:
  - `server/_debug/*_debug.svg` und `*_report.json` pruefen.
- Abhaengigkeitsprobleme im Gate:
  - `run_quality_gate.py` sollte `.venv` automatisch verwenden.

## 9) Nächste sinnvolle Schritte

1. Echte Abwicklung fuer Blechteile aktivieren, sobald FreeCAD SheetMetal-Modul verfuegbar ist
2. Redundanzlogik fuer Masse weiter schaerfen (noch weniger Doppelinfos)
3. Regelwerk aus realen Fertigungsfaellen anreichern
4. CI-Lauf auf GitHub fuer finale Absicherung nutzen
