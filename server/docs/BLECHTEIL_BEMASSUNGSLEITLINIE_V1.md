# Blechteil-Bemassungsleitlinie v1

## Zweck

Dieses Dokument uebersetzt die fachliche Leitlinie fuer Blechteile in eine Drawform-taugliche Spezifikation.
Ziel ist keine maximal vollgestopfte Zeichnung, sondern eine fachlich saubere, fertigungsgerechte und gut lesbare Zeichnung.

Kernsatz:

`Nicht alles bemassen, aber alles eindeutig machen.`

Die Spezifikation ist fuer drei Schichten gedacht:

- `DSE`: entscheidet, welche Merkmale auf welcher Ansicht bemasst werden
- `Renderer`: platziert die vom DSE geplanten Masse lesbar und systematisch
- `Quality Checks`: pruefen Eindeutigkeit, Redundanz, Platzierung und Mindestangaben

## Geltungsbereich

Diese Leitlinie gilt nur fuer `part_type = sheet_metal`.

Innerhalb der Blechteile wird zwingend unterschieden:

- `subtype = biegeteil`
- `subtype = laserteil`

Begruendung:

- `biegeteil`: Fertigteilansicht und Abwicklung haben unterschiedliche Aufgaben
- `laserteil`: die flache Kontur ist bereits das Fertigteil; eine eigene Biegelogik entfaellt

## Subtypklassifikation

Die Subtypzuordnung ist fuer `sheet_metal` in `v1` formal festgelegt.

Primaarregel:

- `biegeteil` wenn `flat_pattern.bend_count >= 1`
- `laserteil` wenn `part_type = sheet_metal` und `flat_pattern.bend_count == 0`

Fallback-Regel:

- wenn das Unfold fehlschlaegt oder kein belastbares `bend_count` liefert, wird
  konservativ `biegeteil` gesetzt

Begruendung:

- der bestehende Renderer behandelt den fehlgeschlagenen Unfold bereits
  konservativ als `biegeteil`
- dadurch wird eher eine zu informative als eine zu duenne Zeichnung erzeugt

## Grundprinzipien

1. Funktion vor Massmenge.
2. Eindeutigkeit vor Vollstaendigkeitsoptik.
3. Bezugsbemassung vor Kettenbemassung.
4. Ein Mass nur einmal, ausser eine Wiederholung ist fachlich zwingend.
5. Hauptansicht und Abwicklung haben unterschiedliche Verantwortungen.
6. Biegungen, Gewinde, Passungen und pruefkritische Merkmale haben Vorrang.
7. Symmetrie, Wiederholung und Lochbilder duerfen genutzt werden, aber nie stillschweigend.

## Zeichnungsfamilien

### 1. Biegeteil

Pflichtansichten:

- Hauptansicht Fertigteil
- mindestens eine orthogonale Nebenansicht fuer Geometrie-/Biegeverstaendnis
- Isometrie nachrangig
- Abwicklung verpflichtend

Ziel:

- Hauptansicht beantwortet: `Wie muss das fertige Teil aussehen und funktionieren?`
- Abwicklung beantwortet: `Wie muss das flache Blech hergestellt und gebogen werden?`

### 2. Laserteil

Pflichtansichten:

- Hauptansicht der flachen Kontur
- Isometrie optional
- keine verpflichtende separate Abwicklung

Ziel:

- eine einzige flache Hauptansicht soll Zuschnitt und Funktion moeglichst vollstaendig beschreiben

## Prioritaetslogik

### Prioritaet A: immer eindeutig bemassen

- Biegelinien
- Biegewinkel
- Biegeradien
- Materialdicke
- Gewinde
- Passungen
- funktionskritische Masse
- montagekritische Masse
- pruefrelevante Masse
- kritische Ausschnitte
- Bezugskanten und Bezugsmasse

### Prioritaet B: bemassen, wenn nicht eindeutig ableitbar

- Bohrungen
- Schlitze
- Ausschnitte
- Lochbilder
- Innenkonturen
- Randabstaende
- Lochlagen

### Prioritaet C: vermeiden oder zusammenfassen

- identische Masse mehrfach
- identische Lochlagen einzeln wiederholen
- ueber Symmetrie bereits definierte Masse
- triviale Wiederholungen
- unnoetige Kettenbemassung
- reine Vollstaendigkeitsmasse ohne Mehrwert

## View Ownership

Jedes Merkmal hat genau eine primaere Bemassungsansicht.
Eine zweite Ansicht darf dasselbe Merkmal nur dann erneut zeigen, wenn ohne diese Wiederholung Fertigung oder Pruefung nicht eindeutig waere.

### Biegeteil

- `Fertigteilansicht`: Aussenmasse des fertigen Teils, funktionskritische Abstaende, Loch-/Schlitzlagen, Gewinde, Passungen
- `Abwicklung`: flache Aussenmasse, Biegelinien, Biegewinkel, Biegeradien, Biegerichtung falls noetig, biegerelevante Schenkellaengen

### Laserteil

- `Hauptansicht`: Aussenkontur, Ausschnitte, Bohrungen, Schlitze, Lochbilder, Bezugskanten

## Merkmalsregeln

### 1. Aussenmasse

Pflicht:

- mindestens zwei eindeutige Gesamtmasse in der primaeren Fertigungsansicht

Regeln:

- bei `biegeteil` gehoeren Gesamtmasse des Fertigteils in die Fertigteilansicht
- Gesamtmasse der flachen Kontur gehoeren in die Abwicklung
- dasselbe Gesamtmass nicht in beiden Ansichten wiederholen, wenn die Ansicht es nicht primaer besitzt

### 2. Bohrungen

Ein Rundloch ist eindeutig beschrieben durch:

- Anzahl
- Groesse
- Lagebezug

Erlaubte kompakte Formen:

- `4x D6,6 gleichmaessig verteilt`
- `2x D8 symmetrisch zur Mittellinie`
- `1x D19,0 von linker und unterer Bezugskante`

Nicht ausreichend:

- nur graphisch sichtbar
- Symmetrie nur optisch vermutbar
- Lochanzahl nur gezeichnet, nicht textlich abgesichert

### 3. Schlitze

Ein Schlitz ist eindeutig beschrieben durch:

- Anzahl
- Laenge x Breite
- Orientierung
- Lagebezug

Erlaubte kompakte Formen:

- `2x Schlitz 18 x 5, gleicher Randabstand`
- `Langloch 20 x 6, mittig, laengs orientiert`

Wichtige Zusatzregel:

- `mittig` ist nur zulaessig, wenn auch die Mittellinie oder Symmetrieachse explizit vorhanden ist
- `Laenge x Breite` ohne Orientierungsinformation ist unzureichend, wenn mehrere Achsen plausibel sind

### 4. Lochbilder und Wiederholungen

Kompakte Bemassung ist zulaessig, wenn folgende drei Punkte gleichzeitig erfuellt sind:

- Anzahl ist textlich genannt
- Muster ist textlich genannt
- Bezug ist textlich genannt

Beispiele fuer zulassige Muster:

- symmetrisch zur Mittellinie
- gleichmaessig verteilt
- auf Raster
- auf Teilkreis
- gleicher Randabstand

Wenn eines davon fehlt, muss zusaetzlich bemasst werden.

### 5. Ausschnitte und Innenkonturen

Bemassung ist Pflicht, wenn:

- der Ausschnitt funktionskritisch ist
- die Kontur fuer Fertigung nicht sicher aus Symmetrie/Wiederholung ableitbar ist
- der CAM-Programmierer sonst raten muesste

Zusammenfassen ist zulaessig, wenn:

- gleiche Konturen mehrfach mit identischem Bezug vorkommen

### 6. Biegungen

Jede Biegung muss eindeutig definiert sein.

Pflichtinformationen je Biegung oder eindeutiger Biegegruppe:

- Lage der Biegelinie
- Biegewinkel
- Biegeradius

Teilbezogene Pflichtinformationen:

- Materialdicke
- Werkstoff

Optional:

- Biegerichtung
- Biegefolge
- Innen- oder Aussenmasssystem

Zusammenfassung ist nur zulaessig, wenn:

- Winkel identisch sind
- Radius identisch ist
- die Zuordnung zur Biegelinie eindeutig bleibt

### 7. Gewinde und Passungen

Immer vollstaendig und textlich angeben.

Gewinde mindestens:

- Nennmass
- Gewindeart
- Tiefe falls relevant
- Durchgang oder blind

Passungen mindestens:

- Nennmass
- Passungsangabe

Regel:

- Gewinde und Passungen duerfen nie nur graphisch dargestellt sein

## Bezugssystem

Es wird immer ein klares 2D-Bezugssystem verwendet.

Default-Regel:

- Primaerbezug = bevorzugte Fertigungskante
- Sekundaerbezug = orthogonale Fertigungskante

Auswahlalgorithmus:

1. Bevorzuge lange, gerade Aussenkanten.
2. Bevorzuge Kanten, die in der Fertigung natuerliche Anschlagskanten sind.
3. Bevorzuge ein orthogonales Paar.
4. Vermeide Bezuege auf Bohrungszentren oder Biegelinien, wenn feste Aussenkanten verfuegbar sind.

Folgeregeln:

- Positionsmasse immer bevorzugt von Primaer-/Sekundaerbezug
- Kettenbemassung nur, wenn der Fertigungsprozess dies direkt erfordert
- gleichartige Features auf gemeinsame Bezuege legen

## Entscheidungsalgorithmus pro Merkmal

Fuer jedes Merkmal wird diese Reihenfolge angewendet:

### Frage 1

Ist das Merkmal:

- biegerelevant
- funktionskritisch
- montagekritisch
- pruefrelevant
- gewinderelevant
- passungsrelevant

Wenn `ja`:

- eindeutig bemassen
- primaere Bemassungsansicht festlegen

### Frage 2

Ist das Merkmal ohne Einzelmass vollstaendig und sicher ableitbar durch:

- Symmetrie
- Mittellinie
- Wiederholung
- Raster
- Lochbild
- gleichen Randabstand

Wenn `ja`:

- kompakte oder zusammengefasste Bemassung zulaessig

### Frage 3

Entsteht durch zusaetzliche Bemassung nur:

- Wiederholung
- Unordnung
- Kettenmass ohne Mehrwert

Wenn `ja`:

- Mass unterdruecken

### Frage 4

Wuerde ein Fertiger oder CAM-Programmierer ohne Rueckfrage wissen:

- wo das Merkmal liegt
- wie gross es ist
- wie oft es vorkommt
- zu welchem Bezug es gehoert

Wenn `nein`:

- zusaetzliche Bemassung ergaenzen

## Placement-Regeln

Dieses Dokument entscheidet nicht nur `was`, sondern auch grob `wo`.

### Fertigteilansicht

- Aussenmasse bevorzugt ausserhalb der Kontur
- Loch- und Schlitzlagen systematisch von Bezugskanten
- zusammengehoerige Merkmale gruppieren
- keine verteilten Einzelmasse ohne gemeinsames Bezugssystem

### Abwicklung

- Gesamtmasse der flachen Kontur an die Aussenseiten
- Biegelinien und Biegeangaben als eigene Gruppe
- Loch- und Schlitzmasse nur zusaetzlich, wenn in der Fertigteilansicht nicht eindeutig
- keine freischwebenden Merkmalsmasse ohne erkennbare Konturbindung

### Abstandswerte

Die exakten Abstaende sind Renderer-Parameter und keine DSE-Entscheidung.

Normnahe Zielwerte fuer `v1`:

- Konturabstand erste Masslinie: `>= 6,0 mm`
- Staffelung weiterer Masslinien: `>= 6,0 mm`
- Ueberstand der Extensionslinien ueber die Masslinie: `1,5 mm`

Interpretation:

- die Leitlinie legt die Mindestordnung fest
- die konkrete Feinanordnung bleibt im Renderer und orientiert sich an ISO
  129-1-nahen Parametern

## Titelblock und Hinweisfeld

Pflicht fuer Blechteile:

- Werkstoff
- Materialdicke
- Allgemeintoleranz
- Entgrathinweis

Optional je nach Teil:

- Oberflaechenangabe
- Kantenangaben

Qualitaetsregel:

- fehlender Werkstoff = mindestens `TITLEBLOCK_INCOMPLETE`
- fehlende Materialdicke bei Blechteil = `SHOWSTOPPER`

## Fehlerabbildung auf Drawform-Fehlerklassen

- nicht eindeutige Loch-/Schlitzlage -> `HOLE_PATTERN_UNCLEAR`
- gleiche Masse mehrfach -> `DIMENSION_REDUNDANT`
- freischwebende, ungebundene Merkmalsmasse -> `DIMENSION_POOR_PLACEMENT`
- Fertigteil- und Abwicklungslogik vermischt -> `PROJECTION_INCONSISTENT`
- Pflichtangaben im Hinweisfeld fehlen -> `TITLEBLOCK_INCOMPLETE`

## Mindestregeln fuer v1-Implementierung

Diese Regeln muessen in `v1` hart implementiert werden:

1. `sheet_metal` immer in `biegeteil` oder `laserteil` aufspalten.
2. `biegeteil` bekommt verpflichtend eine Abwicklung.
3. Abwicklung besitzt die Verantwortung fuer Biegelinien, Biegewinkel und Biegeradien.
4. Loch-/Schlitzbemassung wird nur dann in die Abwicklung dupliziert, wenn die Fertigteilansicht das Merkmal nicht eindeutig beschreibt.
5. Lagebemassung erfolgt standardmaessig von zwei festen Bezugskanten.
6. Symmetrie und Wiederholung duerfen nur verwendet werden, wenn sie textlich oder ueber Mittellinien explizit abgesichert sind.
7. Gewinde und Passungen muessen immer textlich spezifiziert sein.
8. Materialdicke und Werkstoff muessen im Titelblock/Hinweisfeld auftauchen.

## Ableitung fuer den Code

### `server/rules/dimension_strategy.py`

Soll entscheiden:

- `sheet_metal_subtype`
- primaere Bemassungsansicht je Merkmal
- ob ein Merkmal kompakt, voll oder gar nicht bemasst wird
- welches Bezugsachsenpaar verwendet wird

### `server/freecad/step_to_pdf.py`

Soll umsetzen:

- View Ownership
- Gruppierung und Platzierung
- Unterdrueckung redundanter Masse
- systematische Platzierung von Bezugsmassen

### `server/test_views.py`

Soll pruefen:

- keine Pflichtmerkmale ohne eindeutige Bemassung
- keine unzulaessige Massdopplung
- keine freischwebenden Merkmalsmasse
- Titelblockpflichten fuer Blechteile

## Nichtziel fuer v1

Diese Spezifikation verlangt noch nicht:

- vollstaendige GD&T-Logik
- formale ISO-Komplettabdeckung
- automatische Biegefolgeoptimierung
- NC-spezifische Werkzeugstrategien
- Einzeltoleranzen
- formale GD&T-Rahmen nach ISO 1101
- Passungstoleranzbereiche ueber die textliche Angabe hinaus

Klarstellung:

- `v1` erwartet eine Allgemeintoleranz `DIN ISO 2768-mK` im Titelblock
- individuelle Toleranzen sind `v2`-Scope

## Umsetzungsstand 2026-04-04

Diese Leitlinie ist in Drawform fuer `v1` teilweise umgesetzt.

### Bereits umgesetzt

- Split `biegeteil` vs. `laserteil`
- Abwicklung mit Biegelinien fuer echte Biegeteile
- Trennung von Fertigteil- und Abwicklungs-Gesamtmassen
- Flat-Pattern-Bemaessung fuer Loch-/Lageangaben ist grundsaetzlich an den
  DSE-Plan angebunden

### Noch offen

- durchgaengige View Ownership fuer Loch- und Schlitzfeatures
- robuste Wahl der Bezugskanten fuer alle Blechteilfamilien
- gemeinsame Fehlerklassen-Taxonomie als importierbarer Python-Baustein
- vollstaendige DSE-/Renderer-Abstimmung fuer kompakte Lochbild- und
  Schlitzregeln

## Kurzform

- Funktion vor Massmenge
- Eindeutigkeit vor Vollstaendigkeitsoptik
- Biegeteil und Laserteil strikt trennen
- Fertigteilansicht fuer Funktion
- Abwicklung fuer Zuschnitt und Biegung
- Bezugsbemassung vor Kettenbemassung
- Bohrungen und Schlitze nur so weit bemassen, wie fuer Eindeutigkeit noetig
- Symmetrie und Wiederholung nur explizit, nie stillschweigend
- keine unnoetige Massdopplung
- keine freischwebenden Masse
