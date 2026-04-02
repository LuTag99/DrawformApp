# Drawform Pipeline: Analyse auf Senior-Konstrukteur / CAM/CNC-Niveau

**Datum:** 2026-03-22
**Scope:** Vollstaendige Analyse der Test- und Verbesserungspipeline
**Basis:** 145 STEP-Dateien (48 katalogisiert, 97 nicht erfasst), step_to_pdf.py, test_views.py, DSE, Feature Probe

---

## 1. KRITISCHE FEHLER (Sofortmassnahmen noetig)

### 1.1 Tier-3 Klassifizierung: Dicke Fraesplatten werden als sheet_metal eingestuft

**Schweregrad: HOCH**
**Betroffene Datei:** `server/rules/dimension_strategy.py` Zeilen 371-379
**Normverstoss:** Fertigungsgerechte Zeichnungserstellung (DIN 6789)

**Problem:** Die Tier-3 Klassifizierung (`select_layout_profile_standalone()`) nutzt nur das BBox-Verhaeltnis `thickness / mid_dim < 0.15`, hat aber KEINEN absoluten Dickenguard. Ergebnis:

| Teil | BBox (mm) | Dicke | Ratio | Klassifiziert als | Korrekt |
|------|-----------|-------|-------|-------------------|---------|
| Miba Grundplatte Endeffektor | 365x160x17 | 17mm | 0.106 | sheet_metal | **milling** |
| Miba Motorflanschplatte | 160x180x12 | 12mm | 0.075 | sheet_metal | **milling** |
| Endeffektor 10102P01 | 381x160x15 | 15mm | 0.094 | sheet_metal | **milling** |
| Endeffektor 10201P01 | ~380x160x15 | ~15mm | ~0.094 | sheet_metal | **milling** |

**Konsequenz:** Falsche Zeichnungsart — keine Abwicklung moeglich, falsches Ansichtslayout (Iso-View fehlt bei sheet_metal), falsche Bemassungsstrategie, falsche Fertigungshinweise.

**Fix:** Absoluten Dickenguard in Tier 3 einfuegen:
```python
# Tier 3: BBox ratio fallback — but ONLY if thickness is plausible for sheet metal
bbox_min_dim = min(dim_x, dim_y, dim_z)
if bbox_min_dim > 8.0:  # Sheet metal max ~6-8mm; above this is always milling
    return "milling"
```

**Zusaetzlich:** `_looks_like_compact_flat_milling_part()` (Zeilen 291-311) fangt nur Teile mit `plan_aspect <= 1.35` ab. Langgestreckte Platten (Aspect > 2) fallen durch. Der Guard braucht eine Erweiterung:
```python
# Long thin plates with thickness > 8mm are always milling
if thickness > 8.0:
    return True
```

### 1.2 Detection-Block liefert `unknown` fuer reale Teile

**Schweregrad: HOCH**
**Betroffene Datei:** `server/freecad/step_to_pdf.py` (Detection-Block)

**Problem:** Bei mindestens 3 von 48 katalogisierten Teilen und 1 unkatalogierten Teil liefert der Detection-Block `longest_axis=unknown`, `flatness_ratio=0`, `confidence=0`, obwohl der Feature-Probe korrekte Werte hat.

Betroffene Teile:
- `SP-RHM-000` (43x22x8.5mm, 65 Bohrungen) — Features: axis=X, flat_ratio=0.386
- `logiBOT_02_Abdeckblech Hinten_Einpress` — axis=unknown
- `logiBOT_02_AbdeckblechSeitlichSpie_Schweiss` — axis=unknown

**Root Cause:** step_to_pdf.py hat einen eigenen Erkennungsalgorithmus, der die Feature-Probe-Daten NICHT als Fallback nutzt. Wenn der eigene Algorithmus versagt, wird `unknown` geschrieben, obwohl korrekte Daten vorliegen.

**Konsequenz:** Falsche Ansichtswahl, keine Achsenoptimierung, conf=0.00 signalisiert "Zufallsergebnis".

### 1.3 97 von 145 STEP-Dateien werden nicht getestet

**Schweregrad: HOCH**
**Betroffene Datei:** `server/sample_catalog.py` Zeile 12

**Problem:** `REAL_SAMPLE_FOLDERS = {"milling parts", "sheetmetals"}` — nur 2 von 10 Ordnern sind registriert.

Nicht erfasste Ordner mit realen Industrieteilen:
- `02_MillingParts_Miba/` — 12 Frasteile (Grundplatten, Wellen, Greifer, Spannscheiben)
- `05_...Endeffektor/` — 52 Endeffektorteile (2 Revisionssaetze)
- `10-03-2026/` — 7 SP-RHM/RMH Teile
- `2025-04-24_Blechteile/` — 5 Kreisfoermige Deckel/Grundplatten
- `Adapterplatte UR10_UR20/` — 2 Roboter-Adapterplatten
- `Bleche Magazinwagen/` + `Bleche Magazinwagen 2/` — 11 Magazinwagen-Bleche

**Konsequenz:** Regressionstests decken nur 33% der verfuegbaren Daten ab. Neue Fehlerklassen (Tier-3-Fehlklassifizierung, unknown-axis) wurden erst durch manuelles Testen entdeckt.

---

## 2. STRUKTURELLE SCHWAECHEN IM TEST-FRAMEWORK

### 2.1 Overflow-Toleranz verdeckt echte Layout-Probleme

**Betroffene Datei:** `server/test_views.py` Zeilen 550-557

**Problem:** `QUALITY_OVERFLOW_TOL_MM = 1.5` — alle Overflow-abhaengigen Assertions sind hinter dieser Toleranz gated. Auf einem A3-Blatt (420x297mm) sind 1.5mm = 0.36% — fuer einen gedruckten Plan akzeptabel, aber fuer CNC-Fertigung NICHT.

**Konstrukteur-Perspektive:** Ein CNC-Programmierer, der Masse von der Zeichnung abnimmt, braucht 100% Sichtbarkeit aller Bemassungen. Wenn eine Masslinie 1.5mm ausserhalb des Zeichnungsbereichs liegt, wird sie ggf. beim Drucken/PDF-Export abgeschnitten.

**Empfehlung:** Zwei Toleranzstufen einfuehren:
- `QUALITY_OVERFLOW_SOFT_MM = 1.5` — Warning (wird gemeldet, kein Fail)
- `QUALITY_OVERFLOW_HARD_MM = 0.5` — Fail fuer Bemassungslinien und Masszahlen
- Geometrieumrisse duerfen um 1.5mm ueberragen (nicht fertigungsrelevant)

### 2.2 Alignment-Check nutzt BBox statt Umriss-Kanten

**Betroffene Datei:** `server/freecad/step_to_pdf.py` Zeilen 7093-7110

**Problem:** Die Fluchtlinienpruefung (Front/Top left-edge Match, Front/Left top-edge Match) vergleicht **BBox-Kanten** (`left_edge = round(min_x, 2)`), nicht die geometrische Umrisskante. Bei Kreisfoermigen Teilen (Flansch, Deckel) weicht die BBox-Kante deutlich vom wahren Umriss ab.

**DIN ISO 128-30:** Erste-Winkel-Projektion verlangt, dass sichtbare Umrisskanten der zugehoerigen Ansichten vertikal/horizontal fluchten. Die BBox ist keine Umrisskante.

**Aktuelle Toleranz:** 2.0mm — fuer die BBox-Methode noetig, aber fuer echte Umriss-Fluchtung viel zu locker. Ein Senior-Konstrukteur wuerde bei 1mm Fluchtungsabweichung die Zeichnung zurueckweisen.

### 2.3 Geometrie-Genauigkeitscheck greift zu kurz

**Betroffene Datei:** `server/test_views.py` Zeilen 765-898

**Problem:** `check_geometry_accuracy()` vergleicht nur:
- Overall-Masse gegen BBox (Toleranz 0.5mm)
- Lochdurchmesser gegen erkannte Durchmesser (Toleranz 0.2mm)
- Abwicklungsmasse gegen berechnete Werte (Toleranz 1.0mm)
- Dicke gegen Prozessnotiz (Toleranz 0.1mm)
- Completeness: Top-2 BBox-Masse muessen im Plan vorkommen

**Fehlend aus Konstrukteur-Sicht:**
- Lochabstaende (Pitch, X/Y-Positionen) werden NICHT gegen CAD-Geometrie geprueft
- Lochmuster-Symmetrie wird nicht validiert (ISO 1101 Positionstoleranz)
- Stufenmasse (stepped_shaft: Absaetze) werden nicht einzeln geprueft
- Fase/Radius-Masse fehlen komplett
- Gewindekernloch-Durchmesser vs. Gewindebezeichnung (ISO 261/965) nicht validiert
- Passungsmasse (H7, g6) nicht erkannt/bemasst

### 2.4 Centerline-Check: Nur Zaehlung, keine Positions-Validierung

**Betroffene Datei:** `server/test_views.py` Zeilen 598-627

**Problem:** Der Test prueft nur:
- Ob `stroke-dasharray` im SVG vorkommt (= irgendeine Strichlinie existiert)
- Ob `centerline_total > 0`
- Ob Views mit Kreisen auch Mittellinien haben

**Fehlend:**
- Mittellinien muessen durch den **Kreismittelpunkt** gehen (Positionscheck)
- Mittellinien muessen ueber den Kreis **hinausragen** (ISO 128-1: Ueberstand 2-3mm)
- Bei Lochmustern muessen Mittellinien **verbundene Lochkreise** darstellen (Lochkreis-Mittellinie)
- Symmetrielinien bei symmetrischen Teilen fehlen komplett

---

## 3. DIN/ISO NORMVERSTÖSSE

### 3.1 Masslinienstil (ISO 129-1)

**Betroffene Datei:** `server/freecad/step_to_pdf.py` Zeilen 1359-1519

| Aspekt | Soll (ISO 129-1) | Ist | Status |
|--------|-------------------|-----|--------|
| Masshilfslinienabstand vom Umriss | 0-0.5mm | `gap_mm = 0.0` | OK |
| Texthoehe | 3.5-7.0mm | 4.2-4.9mm | OK |
| Pfeillaenge | 2.5-3.0mm | skaliert | Teilweise OK |
| Masshilfslinien-Ueberstand | 1.0-2.0mm | 0.6-2.0mm | **0.6mm zu kurz** |
| Abstand Masslinien untereinander | min. 7mm | nicht gestaffelt | **FEHLT** |
| Abstand Masslinie zu Umriss | min. 10mm | `offset_mm = max(1.6, ...)` | **1.6mm zu nah** |
| Diagonale Massfuehrung | Parallel zur Kante | nur H/V | **FEHLT** |
| Vertikale Text-Leserichtung | Von unten nach oben | rotate(-90) | **Potenziell falsch** |

### 3.2 Mittellinienstil (ISO 128-1)

**Betroffene Datei:** `server/freecad/step_to_pdf.py` Zeilen 3852-3906

| Aspekt | Soll (ISO 128-1 §3.2.5) | Ist | Status |
|--------|--------------------------|-----|--------|
| Strichlaenge lang | 5-30mm auf Papier | 5mm/scale | **Skaliert falsch** |
| Strichlaenge kurz | 0.5-1.5mm | 1.2mm/scale | **Skaliert falsch** |
| Luecke | 1.5-3.0mm | 2mm/scale | **Skaliert falsch** |
| Linienstaerke | 0.18-0.25mm | `stroke_width * 0.46` | **Kann < 0.01mm sein** |
| Ueberstand ueber Kreis | 2-3mm | extension = f(radius) | Teilweise OK |
| Max Kreise | unbegrenzt | Hard-limit 12 | **Fehler bei 20+ Bohrungen** |

**Hauptproblem:** Die Strichlierung wird mit `1/scale` skaliert, was bei kleinen Masstaeben (0.1) zu 50mm Strichen fuehrt. ISO 128 fordert feste Strichlaengen auf dem Papier, unabhaengig vom Massstab.

### 3.3 Schriftfeld (ISO 7200)

**Betroffene Datei:** `server/freecad/step_to_pdf.py` Zeilen 5240-5330

**Fehlende Pflichtfelder:**
- AUSGABE (Issue/Release)
- ZEICHNUNGSART (Einzelteil, Zusammenbau, Fertigungszeichnung)
- FREIGABE (Genehmigung + Unterschrift)
- GEPRUEFT (Pruefer + Datum)
- OBERFLAECHENGUETE (ISO 1302 — zumindest Platzhalter)

**Falsch:**
- Projektionssymbol zu klein (~8x8px, soll >= 20x20mm)
- Material-Feld default="-" statt leer (ISO 7200)
- Datumsformat nicht validiert (muss DD.MM.YYYY sein, DIN 7701)
- Massstab kann Nicht-Standardwerte haben (z.B. 1:2.347 statt 1:2 oder 1:2.5 gem. ISO 5455)

### 3.4 Toleranzrahmen / GD&T (ISO 1101) nicht implementiert

Keine Formtoleranzen, keine Lagetoleranzen, keine Lauftoleranzen, keine Bezugsangaben am Schriftfeld. Ein Senior-Konstrukteur wuerde eine Zeichnung ohne Formtoleranzen bei Passungen NICHT freigeben.

---

## 4. FEATURE-PROBE SCHWAECHEN (step_feature_probe.py)

### 4.1 Biegeradius-Falscherkennung

**Zeilen 557-562:** `bend_radius_mm` wird aus ALLEN Zylinderflaechen berechnet, die groesser als `thickness * 0.5` sind. Bei Fraes- und Drehteilen werden Bohrungswaende und Absatzradien faelschlicherweise als Biegeradien gemeldet.

**Beispiel:** SP-RHM-000 (43x22x8.5mm Fraesteil, 65 Bohrungen) meldet `bend_radius_mm=12.86mm` — das ist ein Bohrungsradius, kein Biegeradius.

**Fix:** Biegeradius nur melden, wenn:
- Flatpattern >= 1 Bend ODER
- `is_sheet_metal_by_faces` == True ODER
- `measured_thickness_mm` <= 5mm

### 4.2 Hole-Pitch ist SPAN, nicht PITCH

**Zeilen 550-555:**
```python
hole_pitch_mm = float(span)  # span = max(positions) - min(positions)
```

Das ist der **Gesamtabstand** (Span), nicht der **Lochabstand** (Pitch). Bei 4 Bohrungen im Raster [0, 30, 60, 90] wuerde `pitch=90mm` gemeldet, korrekt waere `pitch=30mm`.

**Konsequenz fuer CNC:** Ein CNC-Programmierer, der den Pitch zum Programmieren nutzt, bekommt die Gesamtspanne statt des Teilungsabstands.

**Fix:**
```python
positions_sorted = sorted(positions)
spacings = [positions_sorted[i+1] - positions_sorted[i] for i in range(len(positions_sorted)-1)]
hole_pitch_mm = statistics.median(spacings) if spacings else None
```

### 4.3 Gewinde-Erkennung: Zu wenige Kandidaten

**Zeilen 453-468:** Nur 7 Gewindegrundbohrungen (M5-M20) werden erkannt. Feingewinde (M8x1, M10x1.25), Whitworth (G1/4), UNC/UNF fehlen komplett. Fuer internationalen Einsatz unzureichend.

### 4.4 Flachmuster-Berechnung: K-Faktor nur 2-stufig

**Zeilen 396-401:**
```python
k = 0.33 if r_over_t < 2.0 else 0.50
```

Zwei K-Faktor-Werte fuer alle Materialien/Dicken. DIN 6935 gibt materialabhaengige Werte:
- Stahl S235: K=0.33 (r/t < 1), K=0.38 (1 < r/t < 3), K=0.44 (r/t > 3)
- Aluminium: K=0.28 (weich), K=0.35 (hart)
- Edelstahl: K=0.37-0.45

---

## 5. SCALE-REDUCTION-LOOP (step_to_pdf.py)

### 5.1 Padding-Skalierungsfehler

**Zeilen 6880-6930:** `fit_w * scale` skaliert Bemassungs-Padding (Texte, Pfeile, Hilfslinien) linear mit dem Massstab. Aber Texthoehe, Pfeillaenge und Hilfslinienabstand sind FESTE Groessen (mm auf Papier). Bei scale=0.3 sind die Padding-Reservierungen 70% zu klein, bei scale=2.0 doppelt so gross wie noetig.

### 5.2 Kein ISO-5455-konformer Massstab

Nach der Scale-Reduction ergibt sich ein beliebiger Massstab (z.B. 1:2.347). ISO 5455 erlaubt nur Vorzugsmassstabe: 1:1, 1:2, 1:2.5, 1:5, 1:10, etc. Der Massstab im Schriftfeld zeigt den beliebigen Wert.

**Fix-Vorschlag:** Nach Berechnung zum naechst-kleineren ISO-Massstab runden:
```python
ISO_SCALES = [10, 5, 2.5, 2, 1, 0.5, 0.2, 0.1, 0.05]
preferred = max(s for s in ISO_SCALES if s <= computed_scale)
```

---

## 6. PRIORISIERTE VERBESSERUNGSEMPFEHLUNGEN

### Prioritaet 1 — Sofort (Fehlerkorrektur)

| # | Massnahme | Aufwand | Impact |
|---|-----------|---------|--------|
| P1.1 | Tier-3 Dickenguard: `bbox_min_dim > 8mm → milling` | 5 Zeilen | 4 Teile korrekt |
| P1.2 | `_looks_like_compact_flat_milling_part()` erweitern fuer Dicke > 8mm | 3 Zeilen | Robusterer Guard |
| P1.3 | hole_pitch als Median(Abstande) statt Span berechnen | 10 Zeilen | Korrekte Teilung |
| P1.4 | bend_radius nur bei echtem Blech melden | 5 Zeilen | Keine Falsch-Radien |
| P1.5 | `REAL_SAMPLE_FOLDERS` um alle Ordner erweitern | 1 Zeile | 97 neue Teile im Test |

### Prioritaet 2 — Kurzfristig (Normkonformitaet)

| # | Massnahme | Aufwand | Impact |
|---|-----------|---------|--------|
| P2.1 | Centerline-Strichlierung ISO-konform (feste Papierlaengen) | 20 Zeilen | ISO 128-1 |
| P2.2 | Masslinienstaffelung (7mm Mindestabstand) | 30 Zeilen | ISO 129-1 |
| P2.3 | Massstab auf ISO 5455 Vorzugswerte runden | 15 Zeilen | ISO 5455 |
| P2.4 | Centerline-Limit von 12 auf 30+ erhoehen | 2 Zeilen | Volle Abdeckung |
| P2.5 | Schriftfeld: fehlende Felder + Symbolgroesse | 40 Zeilen | ISO 7200 |

### Prioritaet 3 — Mittelfristig (Fertigungsqualitaet)

| # | Massnahme | Aufwand | Impact |
|---|-----------|---------|--------|
| P3.1 | Detection-Fallback auf Feature-Probe Daten | 20 Zeilen | `unknown` eliminieren |
| P3.2 | K-Faktor-Tabelle materialabhaengig (DIN 6935) | 30 Zeilen | Korrekte Abwicklung |
| P3.3 | Geometrie-Genauigkeitscheck: Lochabstaende, Stufenmasse | 80 Zeilen | Fertigungssicherheit |
| P3.4 | Gewinde-Erkennung erweitern (Feingewinde, Whitworth) | 30 Zeilen | Internationale Teile |
| P3.5 | Overflow-Toleranz 2-stufig (Soft/Hard) | 15 Zeilen | Bessere QA |
| P3.6 | Alignment-Check auf Umrisskanten statt BBox | 60 Zeilen | DIN 6784 |

### Prioritaet 4 — Langfristig (Senior-Level-Zeichnungen)

| # | Massnahme | Aufwand | Impact |
|---|-----------|---------|--------|
| P4.1 | GD&T / Formtoleranzen (ISO 1101) | 200+ Zeilen | Passungsteile |
| P4.2 | Schnittansichten (ISO 128-40) | 300+ Zeilen | Innenkonturen |
| P4.3 | Oberflaechenangaben (ISO 1302) | 100 Zeilen | Fertigungsvorschrift |
| P4.4 | Detailansichten fuer dichte Features | 150 Zeilen | Lesbarkeit |
| P4.5 | Diagonale Massfuehrung | 80 Zeilen | Winkelmasse |
| P4.6 | Schweisssymbole (ISO 2553) | 100 Zeilen | Schweissteile |

---

## 7. TESTABDECKUNG — AKTUELLE LUECKEN

### Was getestet wird (gut):
- Achsenerkennung, Flachheit, Rotation (check_view_orientation)
- Feature-Erwartungen: Lochzahl, Durchmesser, Pitch, Biegeradius (check_feature_expectations)
- Layout-Qualitaet: Overflow, Fits, Scale-Reduction (check_layout_quality)
- Norm-Marker: Titel, Toleranz, Projektionssymbol (check_norm_conformity)
- Bemassungsqualitaet: Textanzahl, Feature-Dims, Bounds, Overlap (check_dim_quality)
- DSE-Plan: Strukturvalidierung, Duplikat-Check (check_dimension_plan)
- Geometrie-Genauigkeit: BBox vs. Plan, Loecher, Dicke, Abwicklung (check_geometry_accuracy)
- Abwicklung: 8-Punkt-Check inkl. Biegekanten (check_abwicklung)
- Schriftfeld: 7 Pflichtfelder + Massstab-Konsistenz (check_title_block)

### Was NICHT getestet wird (Luecken):
1. **Keine visuelle Regression** — nur numerische Metriken, kein Pixel-Vergleich der PDFs
2. **Keine Lochmuster-Validierung** — Pitch-Positionen, Lochkreise, Symmetrie
3. **Keine Bemassungs-Lesbarkeit** — Textgroesse nach Scale-Reduction, Ueberlappung mit Geometrie
4. **Keine Schnitt-/Detailansicht-Tests** — weil sie nicht implementiert sind
5. **Keine DXF-Export-Validierung** — Abwicklung als DXF fuer Laser/CNC
6. **Keine Masskettencheck** — geschlossene Massketten (ISO 129-1 §6.1)
7. **Keine Strichstaerken-Validierung** — ISO 128 schreibt 0.5mm/0.25mm/0.18mm vor
8. **97 Industrieteile nicht im Testset**

---

## 8. ZUSAMMENFASSUNG

**Aktueller Status:** Solide Basis mit 47/48 katalogisierten Teilen bestanden. Die Pipeline erzeugt druckbare technische Zeichnungen, die auf den ersten Blick professionell wirken.

**Konstrukteur-Bewertung:** Bei genauer Pruefung fallen einem erfahrenen Konstrukteur sofort auf:
- Fehlklassifizierungen bei Industrieteilen (>12mm Dicke als Blech)
- Fehlende Bemassungsstaffelung und diagonale Masse
- Nicht ISO-konforme Mittellinien bei extremen Masstaeben
- Fehlende GD&T-Symbole und Formtoleranzen
- Kein Massstab-Normwert im Schriftfeld

**CNC-Programmierer-Bewertung:**
- hole_pitch als Span statt Teilung — direkt fehlerrelevant
- Fehlende Lochabstandsbemassungen (nur Gesamtspan)
- K-Faktor-Vereinfachung fuehrt zu Abwicklungsfehlern
- Material-Feld leer — keine Werkstoff-Info fuer Maschinenparameter

**Empfehlung:** P1.1-P1.5 sofort umsetzen (1-2h Aufwand, grosser Impact), dann P2.1-P2.5 fuer ISO-Konformitaet.
