# Quality Check Audit

Stand: 2026-03-13

Ziel:
- dokumentieren, welche Pruefpfade echte fachliche Tiefe haben
- markieren, welche Checks nur oberflaechlich oder rein strukturell pruefen
- die Blind Spots fuer Zeichnungsqualitaet klar benennen

## Einstufung

- `deep`: prueft fachliche oder geometrische Wahrheit mit belastbarer Regel
- `medium`: prueft einen sinnvollen Teilaspekt, aber nicht die volle Zeichnungsqualitaet
- `superficial`: prueft nur Presence, Counts, grobe Heuristik oder Orchestrierung

## Audit nach Pruefpfad

### `server/run_quality_gate.py`

- `run_step()` -> `superficial`
  Grund: reine Orchestrierung; keine fachliche Bewertung.
- Gesamtablauf -> `superficial`
  Grund: fuehrt Checks aus, bewertet aber nicht deren Tiefe oder Blind Spots.

### `server/test_views.py`

- `check_alignment()` -> `superficial`
  Grund: prueft nur linke/obere Kantenlage von Front/Top/Left.
  Blind Spot: keine semantische Ansichtsanordnung, keine Pruefung auf professionelle Komposition.

- `check_view_orientation()` -> `medium`
  Grund: prueft Achse, Flatness, Aspect Ratio, optionale Top-Rotation.
  Blind Spot: keine Funktionssicht, keine Merkmalprioritaet, keine Fertigungsplausibilitaet.

- `check_feature_expectations()` -> `superficial`
  Grund: Count- und Threshold-Pruefung fuer Loecher, Pitch, Radius.
  Blind Spot: keine Lochbildklarheit, keine Platzierungsqualitaet, keine Bezugskantenlogik.

- `check_layout_quality()` -> `superficial`
  Grund: prueft nur Overflow/Fit.
  Blind Spot: die View-BBox basiert auf Geometrie, nicht auf kompletter Mass- und Textausdehnung.

- `check_norm_conformity()` -> `medium`
  Grund: Marker, Einheitensuffixe und Mittellinien werden sinnvoll geprueft.
  Blind Spot: keine echte Normpruefung fuer Bemaessungsaufbau, keine Symbol-/Abstandslogik.

- `check_dim_quality()` -> `medium`
  Grund: prueft Mindestanzahl, Feature-Mass-Praesenz, fehlende Aussenplatzierung bei bevorzugten Feature-Views und harte Textkollisionen.
  Blind Spot: Geometrie-/Gesamtmass-Ueberlagerungen werden zwar als View-Metrik erfasst, aber standardmaessig noch nicht global hart gegatet; ausserdem keine vollstaendige Datum-/Baseline-/Chain-Bewertung und keine semantische Lesbarkeitsmetrik.

- `check_dimension_plan()` -> `superficial`
  Grund: prueft Struktur des DSE-Plans und offensichtliche Duplikate.
  Blind Spot: sagt fast nichts ueber gute Zeichnungswirkung oder richtige Platzierung aus.

- `check_geometry_accuracy()` -> `deep`
  Grund: vergleicht DSE-Werte gegen reale CAD-Geometrie.
  Blind Spot: keine Aussage ueber Lesbarkeit oder Platzierung.

- `check_abwicklung()` -> `medium`
  Grund: prueft Konturbezug, Endpunkte, Summen, Aussen-vs-Biegekanten-Hierarchie und verbotene Biegelegenden.
  Blind Spot: keine allgemeine visuelle Kollisionspruefung und keine Ruhe-/Ordnungsbewertung der Masskette.

- `check_title_block()` -> `medium`
  Grund: prueft Pflichtfelder und Skaleneintrag.
  Blind Spot: keine typografische oder layoutbezogene Qualitaetspruefung.

### `server/freecad/step_to_pdf.py`

- `evaluate_pre_export_quality()` -> `medium`
  Grund: generische Vorab-Heuristik fuer fehlende Aussenmasse, fehlende Durchmesser, Doppelteintraege, Blattgrenzen und jetzt auch View-bezogene Ueberlagerungsmetriken fuer Gesamt-, Feature- und Textboxen.
  Blind Spot: weiterhin kein vollstaendiger Collision Graph aller SVG-Elemente und keine fachliche Score-Logik fuer ruhige, normnahe Massanordnung.

## Aktuelle Haupt-Blind-Spots

- Kein Check bewertet systematisch, ob Massketten an fachlich sinnvollen Bezugskanten liegen.
- Kein Check bewertet generell, ob Feature-Masse ausserhalb der Geometrie auf einer ruhigen Seite gestapelt sind.
- Kein Check bewertet Slot-zu-Slot-, Text-zu-Text- und Text-zu-Geometrie-Kollisionen view-spezifisch.
- Layout-Fit basiert noch auf View-Geometrie, nicht auf kompletter Zeichnung inklusive Dimensionen.
- Doppelte Werte werden nur textuell und naeherungsweise erkannt; gleiche Werte in verschiedenen fachlichen Ketten koennen falsch beurteilt werden.

## Konsequenz

Die Qualitaetssicherung ist bei Zahlenwahrheit und Abwicklungsgrundregeln mittlerweile brauchbar, aber bei allgemeiner Zeichnungsordnung noch nicht tief genug. Weitere harte Checks sollten direkt auf View-Ebene mit echten Bounding Boxes fuer Geometrie, Masslinien und Texte arbeiten.
