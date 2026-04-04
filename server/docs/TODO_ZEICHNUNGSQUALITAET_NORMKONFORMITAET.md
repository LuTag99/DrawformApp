# To-do: Zeichnungsqualitaet und Normkonformitaet

Stand: 2026-04-04

## P0 - Muss vor naechstem Release

1. [x] Mittellinien robust fuer Kreise + Kreisboegen rendern
- Umgesetzt: Kreisquellen aus `<circle>` und aus SVG-Arc-Pfaden (`A/a`) zusammengefuehrt.
- Verifiziert: `python server/test_views.py` (20/20) und aktualisierte Baseline.

2. [x] Bemaessungs-Kollisionserkennung verbessern
- Umgesetzt: Label-Kollisionsboxen gegen Geometrie, Masslinien, Leader und Pfeile.
- Umgesetzt: adaptive Re-Positionierung mit Prioritaets-Offsets.
- Verifiziert: visuelle Stichprobe fuer komplexe Samples in `server/_debug/*_debug.review.png`.

3. [x] Norm-Checks in Tests weiter schaerfen
- Umgesetzt in `test_views.py`:
- Mindestanzahl `centerline_total` fuer komplexe Teile (`min_centerline_count`)
- strengere unitless-Masspruefung (kein `mm` in Einzelmass-Texten)
- Pflichtmarker fuer Norm/Projektion/Toleranz
- Verifiziert: `python server/test_views.py --stability-runs 3 --stability-sleep-ms 100` (20/20).

4. [x] Low-Confidence-Fallback finalisieren
- Bereits im aktuellen Stand enthalten (deterministische Candidate-Tie-Breaks, Confidence-Basis/Gap im Report).

5. [ ] CI-Ergebnis auf GitHub validieren
- Offen: `quality-gate.yml` auf PR ausfuehren.
- Lokal bereits gruener Nachweis:
- `python server/run_quality_gate.py --stability-runs 2 --iterations 3`

## P1 - Sehr sinnvoll direkt danach

6. [ ] Linienstaerken auf ISO-128 Gruppen konsolidieren
- Sichtkanten (dick), Bemaessung/Schraffur/Mittellinien (duenn) klar trennen.
- Einheitliche Ratio dokumentieren und als Konstanten pflegen.

7. [ ] Feature-Callout-Stil normnah harmonisieren
- Einheitliche Schreibweisen fuer:
- Durchmesser `D ...`
- Gewinde `M..`
- Lochabstandstexte
- Einheitliche Schriftgroessen und Leader-Winkel.

8. [x] Visuelle Review-Checkliste als Pflicht-Gate
- `server/_debug/PDF_REVIEW_CHECKLIST.md` wird lokal im Gate erzeugt.
- Gate-Check mehrfach validiert (3 Iterationen).

9. [ ] API-Error-Contract normieren
- `/api/export` und `/api/analyze` Fehlerantworten standardisieren:
- feste `code`-Felder
- reproduzierbare Fehlermeldungen fuer Frontend.

10. [ ] Fraesteil-Featurelogik vervollstaendigen
- Teilweise umgesetzt:
- projizierte Lochzentren und Centerlines fuer `milling`
- 2-Loch-Pitch nicht mehr unnoetig unterdruecken
- dritte Gesamtabmessung auf linker Ansicht
- Verifiziert an:
- `21631_03_141_gripper finger_486.STEP`
- `complex_bracket`
- `feature_test_part`
- `housing`
- Noch offen:
- Bohrungstyp `durch/blind`
- Bohrtiefe
- Taschen-/Stufen-/Chamfer-Logik
- Layout-Warnung `Front vs Top` bei gedrehten Milling-Frontansichten

## P2 - Ausbau nach stabiler Basis

10. [ ] GD&T-Roadmap vorbereiten
- Datenmodell fuer Form- und Lagetoleranzen definieren.
- Rendering von Toleranzrahmen planen.

11. [ ] Erweiterte Normangaben
- Oberflaechenzeichen / Kantenangaben in Metadaten und SVG-Layer vorbereiten.

12. [x] Golden-Korpus weiter ausbauen
- Umgesetzt: 14 reale Fertigungsteile (STEP+PDF) aus `server/_samples/Sheetmetals` und `server/_samples/milling parts` als dedupliziertes Real-Set.
- Umgesetzt: Sample-Katalog mit `--sample-set baseline|real|all`.
- Umgesetzt: lokale Golden-Dateien fuer `real` und `all` in `server/_debug/`.
- Umgesetzt: lokaler visueller Vergleich per `python server/benchmark_real_parts.py --sample-set real`.

## Definition of Done (naechster Milestone)

1. [x] `python server/test_views.py --stability-runs 3` ist gruen.
2. [x] Keine kritische Masszahl-Kollision in allen 20 Samples (lokale visuelle Stichprobe).
3. [x] Normmarker und unitless Masszahlen in Debug-SVGs vorhanden (automatischer Test).
4. [ ] CI `Quality Gate` auf GitHub komplett gruen (noch offen).
