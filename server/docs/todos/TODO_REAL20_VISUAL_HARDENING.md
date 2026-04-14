# TODO Real20 Visual Hardening

Stand: 2026-04-14
Status: offen
Prioritaet: hoch

## Ziel

Einen stabilen, reproduzierbaren 20-Real-Part-Benchmark etablieren und jede
Iteration sichtbar beurteilen, bevor der Critic freigibt. Fokus: reale Teile,
keine synthetischen Samples.

## Aktueller Stand

Letzter 20er-Real-Part-Sweep: 15/20 passed.

Fehlfaelle:
- 202400491_05_Grundlpatte_V1.0 (FreeCAD failed)
- 202500145_09_trolleybase_bracket01_V1.0 (FreeCAD failed)
- 202500145_09_trolleybase_bracket02_V1.0 (FreeCAD failed)
- 202500145_28_productholderpin02_plate02_V1.0 (feature_dims_outside missing in Front)
- 202500220_03_Doppelbacke_V1.0 (feature_dims_outside missing in Front)

## P0 - Benchmark und Visual Gate fixieren

1. Real20-Manifest einfuehren
   - fixierte Liste der 20 Real Parts (keine Zufallsreihenfolge)
   - eigener Sample-Set-Name oder Manifest-Loader
   - nachvollziehbare, wiederholbare Laeufe

2. Visual Review Pflicht je Iteration erzwingen
   - pro Iteration: aktuelle Preview, Debug SVG, Report
   - klarer Vergleich zu Voriteration
   - Visual Verdict: PASS / WARN / FAIL_RECOMMENDED

3. Crash-Cluster analysieren
   - 3 FreeCAD-Fails einzeln reproduzieren
   - gemeinsame Root Cause identifizieren
   - harte Fehlerpfade in kontrollierte Failure Classes ueberfuehren

## P1 - Dimension Placement fuer Real Parts haerten

4. Outside-Placement bevorzugen
   - failure: feature_dims_outside missing in Front
   - Pruefen: DSE-Plan vs. Renderer-Placement
   - Ziel: stabile Aussenplatzierung fuer schmale Frontansichten

5. Visual Delta beweisen
   - Vorher/Nachher fuer die 2 Placement-Faelle sichern
   - keine Verschlechterung der restlichen 15 Teile

## P2 - Long-Run Absicherung

6. Real20 stabilisieren
   - 2 aufeinanderfolgende Long-Run-Pass-Zyklen
   - pro Fehlteil >= 5 Stability Runs
   - Regression auch gegen real_priority

## Akzeptanzkriterien

- Real20: 20/20 passed
- 0 Renderer-Abbrueche in Real20
- feature_dims_outside: keine offenen Verstosse
- jede Iteration hat Visual-Review-Evidenz
- keine Degradation im real_priority Set

## Betroffene Dateien

- server/test_views.py
- server/sample_catalog.py
- server/freecad/step_to_pdf.py
- server/rules/dimension_strategy.py
- server/_debug/*
- server/_debug/agent_runs/<run_id>/run_state.json

