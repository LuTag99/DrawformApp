# Drehteil-Bemassungsleitlinie v1

## Zweck

Dieses Dokument uebersetzt die fachliche Leitlinie fuer Drehteile in eine Drawform-taugliche Spezifikation.
Ziel ist keine rein modellabgeleitete Zeichnung, sondern eine fachlich saubere, fertigungsgerechte und CNC-taugliche Drehzeichnung.

Kernsatz:

`Nicht das Modell abzeichnen, sondern das Einrichtblatt beschreiben.`

Die Spezifikation ist fuer drei Schichten gedacht:

- `Feature Probe`: erkennt rotationssymmetrische Merkmale, Stufengeometrie und Z-Informationen
- `DSE`: entscheidet, welche Merkmale auf welcher Ansicht bemasst werden
- `Renderer + Quality Checks`: platzieren und pruefen die geplanten Masse systematisch

## Geltungsbereich

Diese Leitlinie gilt nur fuer `part_type = turning`.

Innerhalb der Drehteile wird fuer `v1` pragmatisch unterschieden:

- `simple_rotational`: einfache Wellen, Bolzen, Buchsen ohne komplexe Features
- `stepped_shaft`: Absatzwellen mit mehreren Durchmesserstufen
- `complex_turning`: Drehteile mit Bohrungen, Gewinden, Nuten oder kombinierten Bearbeitungen

Begruendung:

- einfache Rotationskoerper brauchen weniger Ansichten und Masse
- Absatzwellen haben spezifische Anforderungen an Stufenbemassung
- komplexe Drehteile koennen Zusatzansichten oder Schnitte benoetigen

## Subtypklassifikation

Die Drehteil-Unterfamilie wird in `v1` aus bestehenden Probe-Feldern abgeleitet.

Reihenfolge:

1. `complex_turning`, wenn
   - `hole_count >= 1` und `thread_label is not None`
   - oder `slot_count >= 1`
   - oder `(hole_count + cylinder_face_count) >= 8`
2. `stepped_shaft`, wenn
   - `cylinder_face_count >= 4`
   - oder mindestens 2 unterschiedliche Durchmesser in `hole_groups`
3. `simple_rotational` fuer alle verbleibenden Faelle

## Grundprinzipien

1. Drehachse immer horizontal in der Hauptansicht.
2. Bemassung ueber der Drehachse (symmetrische Halbansicht bevorzugen, wenn sinnvoll).
3. Durchmesser als Ø-Mass, nie als Radius (ausser Rundungen und Hohlkehlen).
4. Laengenmasse parallel zur Drehachse von einem definierten Bezug.
5. Stufenbemassung bevorzugt kumulativ vom festen Bezug.
6. Ein Mass nur einmal, ausser die Wiederholung ist fachlich zwingend.
7. Isometrie ist nur Uebersicht, nie Haupttraeger fertigungskritischer Masse.
8. Freistiche, Einstiche und Gewindeauslaeufe muessen spezifiziert werden.

## Prioritaetslogik

### Prioritaet A: immer eindeutig bemassen

- Gesamtlaenge
- Gesamtdurchmesser (groesster Durchmesser)
- Alle Stufendurchmesser
- Stufenlaengen
- Gewinde (Nennmass, Art, Laenge)
- Passungen (Nennmass, Passungsangabe)
- Zentrierbohrungen
- Bohrungen (axial und radial)
- Funktionsflaechen
- montagekritische Masse
- pruefrelevante Masse

### Prioritaet B: bemassen, wenn nicht eindeutig ableitbar

- Fasen
- Hohlkehlen / Rundungen
- Freistiche (DIN 509 Angabe)
- Einstiche
- Gewindeauslaeufe
- Raendelungen (Angabe nach DIN 82)
- Konuswinkel
- nicht funktionskritische Uebergangsradien

### Prioritaet C: vermeiden oder zusammenfassen

- gleiche Masse mehrfach
- triviale Wiederholungen
- Zwischenmasse ohne Funktions- oder Pruefbezug
- Masse, die sich ueber Symmetrie definieren lassen
- reine Vollstaendigkeitsmasse

## Bezugssystem

Drehteile werden immer mit einem klaren axialen Bezugssystem beschrieben.

Standardlogik:

- Primaerbezug = Planflaeche (Stirnseite) des Spannbackenfutters
- Sekundaerbezug = Drehachse (Mittellinie)

Default-Beispiel:

- `Z-Achse` = Drehachse (horizontal in der Zeichnung)
- `Bezugsstirnflaeche` = linke oder rechte Planflaeche

Auswahlregeln:

1. Bevorzuge die Stirnflaeche, die in der Fertigung als Spannbezug dient.
2. Alle Laengenmasse vom selben axialen Bezug fuehren.
3. Radiale Masse immer als Durchmesser (nicht Radius) angeben.
4. Bei mehrseitiger Bearbeitung: Bezugswechsel klar kennzeichnen.

Folgeregeln:

- Stufenmasse bevorzugt als kumulative Masse vom axialen Bezug
- Kettenbemassung nur bei echter fachlicher Notwendigkeit
- Tolerierte Masse einzeln fuehren, nicht in Ketten einbinden

## Feature-Klassifikation

### Mindestklassen fuer v1

- Zylindrische Stufe
- Planflaeche
- Fase (Innen-/Aussenfase)
- Hohlkehle / Rundung
- Freistich (DIN 509)
- Einstich (Innen-/Ausseneinstich)
- Gewinde (Aussen-/Innengewinde)
- Zentrierbohrung
- Axialbohrung
- Radialbohrung
- Konus / Kegel
- Raendelung

Wenn die Probe den Typ nicht sicher erkennt:

- das Merkmal darf nicht stillschweigend ignoriert werden
- der Quality Check muss mindestens `WARNUNG` erzeugen
- bei fertigungskritischen Merkmalen ist `MAJOR` angemessen

## Merkmalsregeln

### 1. Gesamtmasse

Pflicht:

- Gesamtlaenge
- Groesster Aussendurchmesser (als Ø-Mass)

Regeln:

- Gesamtlaenge nur einmal fuehren
- Gesamtdurchmesser nur einmal fuehren
- nicht redundant auf mehrere Ansichten verteilen

### 2. Stufenbemassung

Pflicht fuer jede Durchmesserstufe:

- Durchmesser (Ø)
- Laenge (Stufen- oder kumulative Laenge)

Regeln:

- kumulative Bemassung vom Stirnflaechenbezug bevorzugen
- bei kurzen Stufen darf Stufenlaenge direkt bemasst werden
- Uebergaenge (Fase, Radius) an jeder Stufe angeben

### 3. Gewinde

Pflicht:

- Gewindeart und Nennmass (z. B. `M12`, `M10x1`)
- Gewindelaenge
- durchgehend oder blind
- Gewindeauslauf, wenn relevant

Kompakte Formen zulaessig:

- `M12 x 25 lang`
- `M8 Feingewinde P1,0`

Nicht zulaessig:

- Gewinde nur graphisch angedeutet
- Gewinde ohne Laengenangabe
- unklar ob Aussen- oder Innengewinde

### 4. Passungen

Pflicht:

- Nennmass
- Passungsangabe (z. B. `Ø25 h7`, `Ø30 H7`)
- Laenge der Passstelle

Regel:

- Passmasse duerfen nie als normales Durchmessermass ohne Passungsinformation behandelt werden

### 5. Freistiche und Einstiche

Pflicht:

- Form (nach DIN 509 fuer Freistiche, z. B. `DIN 509 E 0,6x0,3`)
- Lage (welche Stufe)

Regel:

- jeder Gewindeanfang benoetigt einen Freistich oder Gewindeauslauf
- Einstiche fuer Sicherungsringe muessen Breite und Tiefe zeigen

### 6. Fasen und Hohlkehlen

Pflicht:

- Mass und Winkel bei Fasen (z. B. `1x45°`, `2x30°`)
- Radius bei Hohlkehlen (z. B. `R0,5`)

Regel:

- identische Fasen duerfen zusammengefasst werden (`alle Kanten 0,5x45°`)
- nicht-triviale Radien muessen einzeln bemasst werden

### 7. Bohrungen

#### Axialbohrung (Zentrierbohrung, Durchgangsbohrung)

Pflicht:

- Durchmesser
- Tiefe (wenn nicht durchgehend)
- Zentrierbohrung nach DIN 332 angeben

#### Radialbohrung

Pflicht:

- Durchmesser
- Lage (axialer Abstand vom Bezug)
- Winkelposition (wenn nicht auf Hauptachse)
- Tiefe (wenn nicht durchgehend)

## Ansichtslogik

### Hauptansicht (Front)

Die Hauptansicht zeigt:

- Drehachse horizontal
- vollstaendige Aussenkontur
- Mittellinie (Drehachse)
- alle Durchmessermasse
- alle Laengenmasse

Regel:

- die Hauptansicht ist fuer Drehteile fast immer ausreichend
- eine einzelne Seitenansicht genuegt, wenn Querloecher, Abflachungen oder
  Schluesselflaechen vorhanden sind

### Seitenansicht (Links/Rechts)

Nur erforderlich, wenn:

- Radialbohrungen oder Abflachungen sichtbar gemacht werden muessen
- Schluesselflaechen (Sechskant, Vierkant) vorhanden sind
- die Stirnseite funktionskritische Merkmale traegt

### Schnittansicht

Ist Pflicht, wenn:

- Innenbearbeitungen (Innendurchmesser, Innengewinde) nicht aus der Hauptansicht eindeutig sind
- Axialbohrungen mit Stufen vorhanden sind
- Wandstaerken kontrolliert werden muessen

### Isometrie

- nur Uebersicht
- keine Massrolle

## View Ownership

- `Hauptansicht`: alle Durchmesser, alle Laengen, Fasen, Hohlkehlen, Freistiche, Gewinde, Passungen, Gesamtmasse
- `Seitenansicht`: Radialbohrungen, Schluesselflaechen, Stirnseiten-Features
- `Schnittansicht`: Innenbearbeitungen, Wandstaerken, Axialbohrung-Details

## Placement-Regeln

### Hauptansicht

- Durchmessermasse oberhalb der Mittellinie (ISO 129-1 Konvention)
- Laengenmasse unterhalb der Kontur oder systematisch gestaffelt
- Stufenmasse in Leserichtung von links nach rechts
- keine kreuzenden Masslinien, wenn vermeidbar

### Abstandswerte

Normnahe Zielwerte fuer `v1`:

- Konturabstand erste Masslinie: `>= 8,0 mm`
- Staffelung weiterer Masslinien: `>= 6,0 mm`
- Ueberstand der Extensionslinien ueber die Masslinie: `1,5 mm`

## Titelblock und Hinweisfeld

Pflicht fuer Drehteile:

- Werkstoff
- Masseinheit
- Allgemeintoleranz
- Entgrathinweis
- Oberflaechenangabe (falls funktionskritisch)

Optional je nach Teil:

- Waermebehandlung
- Beschichtung
- Haerteangabe

Qualitaetsregel:

- fehlender Werkstoff = mindestens `TITLEBLOCK_INCOMPLETE`
- fehlende Masseinheit = `TITLEBLOCK_INCOMPLETE`

## Fehlerabbildung auf Drawform-Fehlerklassen

- fehlende Stufenlaenge oder Stufendurchmesser -> `DIMENSION_MISSING`
- fehlende Gewindeangabe -> `DIMENSION_MISSING`
- unklar ob Gewinde Aussen- oder Innengewinde -> `HOLE_PATTERN_UNCLEAR`
- doppeltes Durchmessermass -> `DIMENSION_REDUNDANT`
- Mass nicht auf Drehachse bezogen -> `DIMENSION_POOR_PLACEMENT`
- Schnittansicht fehlt bei Innenbearbeitung -> `VIEW_SELECTION_ERROR`
- Pflichtangaben im Titelblock fehlen -> `TITLEBLOCK_INCOMPLETE`

## Mindestregeln fuer v1-Implementierung

Diese Regeln muessen in `v1` hart umgesetzt werden:

1. `turning` wird mindestens in `simple_rotational`, `stepped_shaft` und `complex_turning` unterteilt.
2. Drehachse ist immer horizontal in der Hauptansicht.
3. Durchmesser werden als Ø bemasst, nie als Radius.
4. Gesamtlaenge und groesster Durchmesser sind Pflicht.
5. Stufenbemassung bevorzugt kumulativ vom Stirnflaechenbezug.
6. Gewinde und Passungen muessen textlich vollstaendig beschrieben werden.
7. Freistiche an Gewindeanfaengen sind Pflicht.
8. Mittellinie (Drehachse) ist in der Hauptansicht verpflichtend.

## Ableitung fuer den Code

### `server/freecad/step_feature_probe.py`

Soll liefern:

- `rotational_profile: True/False`
- Stufengeometrie (Durchmesser, Laengen)
- Gewinde-Erkennung (Art, Nennmass)
- Zentrierbohrung-Erkennung
- Radialbohrung-Erkennung

### `server/rules/dimension_strategy.py`

Soll entscheiden:

- turning-Unterfamilie
- kumulative vs. Stufen-Einzelbemassung
- Freistich-Angaben
- Gewinde-Darstellung

### `server/freecad/step_to_pdf.py`

Soll umsetzen:

- horizontale Drehachse
- Durchmessermasse mit Ø
- systematische Stufenbemassung
- Mittellinie als Pflicht-Element

### `server/test_views.py`

Soll pruefen:

- Gesamtlaenge und Gesamtdurchmesser vorhanden
- alle Stufen bemasst
- Gewinde und Passungen textlich spezifiziert
- Mittellinie vorhanden
- keine Radius-statt-Durchmesser-Fehler

## Nichtziel fuer v1

Diese Spezifikation verlangt noch nicht:

- vollstaendige GD&T-Abdeckung
- automatische Spannsimulation
- formale Oberflaechenzeichen nach ISO 1302
- Bearbeitungsfolgeplanung
- Einzeltoleranzen
- formale GD&T-Rahmen nach ISO 1101

Klarstellung:

- `v1` erwartet eine Allgemeintoleranz `DIN ISO 2768-mK` im Titelblock
- individuelle Toleranzen sind `v2`-Scope

## Kurzform

- Drehachse horizontal
- Durchmesser als Ø, nie als Radius
- Bezug von der Stirnflaeche
- Stufenbemassung kumulativ
- Gesamtlaenge und Gesamtdurchmesser Pflicht
- Gewinde und Passungen explizit angeben
- Freistiche an Gewindeanfaengen
- Mittellinie verpflichtend
- keine unnoetige Massdopplung
- der Dreher muss die Zeichnung ohne Raten verstehen
