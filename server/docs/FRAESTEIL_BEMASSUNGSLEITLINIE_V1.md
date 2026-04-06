# Fraesteil-Bemassungsleitlinie v1

## Zweck

Dieses Dokument uebersetzt die fachliche Leitlinie fuer Fraesteile in eine Drawform-taugliche Spezifikation.
Ziel ist keine rein modellabgeleitete Zeichnung, sondern eine fachlich saubere, fertigungsgerechte und CAM-taugliche Fraeszeichnung.

Kernsatz:

`Nicht das Modell abzeichnen, sondern die Fertigung beschreiben.`

Die Spezifikation ist fuer drei Schichten gedacht:

- `Feature Probe`: erkennt bearbeitungsrelevante Merkmale, Typen und Z-Informationen
- `DSE`: entscheidet, welche Merkmale auf welcher Ansicht bemasst werden
- `Renderer + Quality Checks`: platzieren und pruefen die geplanten Masse systematisch

## Geltungsbereich

Diese Leitlinie gilt nur fuer `part_type = milling`.

Innerhalb der Fraesteile wird fuer `v1` mindestens pragmatisch unterschieden:

- `plate_2p5d`: flaches 2,5D-Teil mit Taschen, Bohrungen, Schlitzen oder Konturmerkmalen
- `block_prismatic`: prismatischer Koerper mit Bearbeitungen auf mehreren Flaechen
- `feature_dense`: taschen-, nuten- oder bohrungsdominantes Teil mit hoher Merkmalsdichte

Begruendung:

- nicht jedes Fraesteil braucht dieselbe Ansichtslogik
- flache Platten, prismatische Bloecke und feature-dichte Teile haben unterschiedliche Anforderungen an Hauptansicht, Z-Darstellung und Schnittbedarf

## Subtypklassifikation

Die Fraesteil-Unterfamilie wird in `v1` explizit aus bestehenden Probe-Feldern
abgeleitet.

Reihenfolge:

1. `feature_dense`, wenn
   - `hole_count >= 8`
   - oder `slot_count >= 4`
   - oder `(hole_count + slot_count) >= 6`
2. `plate_2p5d`, wenn
   - `flat_ratio < 0.25`
   - und kein `feature_dense`-Trigger aktiv ist
3. `block_prismatic` fuer alle verbleibenden Faelle

Begruendung:

- die Regeln nutzen nur bereits vorhandene Probe-Felder
- die Klassifikation ist damit in `v1` robust genug fuer DSE-Metadaten und
  spaetere Layout-Entscheidungen

## Grundprinzipien

1. Fertigung vor Geometrieoptik.
2. Eindeutigkeit vor Vollstaendigkeitsoptik.
3. Bezugsbemassung vor Kettenbemassung.
4. Ein Mass nur einmal, ausser die Wiederholung ist fachlich zwingend.
5. Fraesteile werden feature-basiert bemasst, nicht nur ueber Silhouetten.
6. Jede Bearbeitung muss Typ, Lage, Groesse und falls noetig Tiefe klar beschreiben.
7. Isometrie ist nur Uebersicht, nie Haupttraeger fertigungskritischer Masse.
8. Verdeckte Kanten duerfen das Verstaendnis unterstuetzen, ersetzen aber keine eindeutige Beschreibung.

## Prioritaetslogik

### Prioritaet A: immer eindeutig bemassen

- Aussenmasse des Bauteils
- Bezugskanten und Bezugsflaechen
- Funktionsflaechen
- Bohrungen
- Gewinde
- Passungen
- Taschen
- Nuten
- Stufen und Absaetze
- Bearbeitungstiefen
- montagekritische Masse
- pruefrelevante Masse
- Lochbilder
- Sitzmasse
- Mittenabstaende funktionsrelevanter Features

### Prioritaet B: bemassen, wenn nicht eindeutig ableitbar

- Radien
- Fasen
- Freistiche
- symmetrische Lochlagen
- wiederholte identische Features
- Innenkonturen
- nicht funktionskritische Randabstaende

### Prioritaet C: vermeiden oder zusammenfassen

- gleiche Masse mehrfach
- triviale Wiederholungen
- optisch ableitbare Masse ohne Fertigungsmehrwert
- unnoetige Kettenbemassung
- Zwischenmasse ohne Funktions- oder Pruefbezug
- Masse, die sich sauber ueber Symmetrie oder Lochbild definieren lassen

## Bezugssystem

Fraesteile werden immer mit einem klaren 3D-Bezugssystem beschrieben.

Standardlogik:

- Primaerbezug = Hauptauflageflaeche
- Sekundaerbezug = Laengskante
- Tertiaerbezug = orthogonale Querkante

Default-Beispiel:

- `Z` = Unterseite oder Hauptauflageflaeche
- `X` = linke Bezugskante
- `Y` = untere Bezugskante

Auswahlregeln:

1. Bevorzuge stabile Auflageflaechen als Primaerbezug.
2. Bevorzuge lange, gerade Aussenkanten als Sekundaer-/Tertiaerbezug.
3. Bevorzuge Kanten, die in Fertigung und Pruefung als natuerlicher Nullpunkt taugen.
4. Vermeide Bezug auf Hilfsgeometrie, wenn feste Aussenbezuege verfuegbar sind.

Folgeregeln:

- Positionsmasse bevorzugt von festen Bezuegen
- Kettenbemassung nur bei echter fachlicher Notwendigkeit
- gleiche Featuregruppen auf gemeinsame Bezuege legen
- Mittellinien nur nutzen, wenn Symmetrie konstruktiv wirklich gewollt ist

## Feature-Klassifikation

Jedes erkannte Bearbeitungsmerkmal wird typisiert.
Ein Merkmal darf nicht nur auf seine sichtbare 2D-Kontur reduziert werden.

### Mindestklassen fuer v1

- Durchgangsbohrung
- Sackloch
- Gewindebohrung
- Senkbohrung
- Zylindersenkung
- Passbohrung
- Reibbohrung
- Tasche
- Nut
- Stufe / Absatz
- Aussenkonturmerkmal

Wenn die Probe den Typ nicht sicher erkennt:

- das Merkmal darf nicht stillschweigend als triviale Kreis- oder Schlitzkontur behandelt werden
- der Quality Check muss mindestens `WARNUNG` erzeugen
- bei bearbeitungskritischen Merkmalen ist `MAJOR` angemessen

## Merkmalsregeln

### 1. Aussenmasse

Pflicht:

- mindestens zwei eindeutige Gesamtmasse in der primaeren Funktionsansicht
- bei prismatischen Teilen zusaetzlich eine eindeutige Hoehen- oder Dickeninformation

Regeln:

- Gesamtmasse nur einmal fuehren
- Gesamtmasse nicht redundant auf mehrere Ansichten verteilen
- Zwischenmasse nur dann zeigen, wenn sie funktional oder prueftechnisch relevant sind

### 2. Bohrungen

Eine Bohrung darf nie nur als Kreis behandelt werden.
Sie muss typisiert und entsprechend beschrieben werden.

#### Durchgangsbohrung

Pflicht:

- Durchmesser
- Lage `X/Y`
- Anzahl
- Toleranz falls relevant

#### Sackloch

Pflicht:

- Durchmesser
- Lage `X/Y`
- Tiefe

#### Gewindebohrung

Pflicht:

- Gewindeart
- Nenngroesse
- Lage
- Anzahl
- Gewindetiefe, wenn nicht durchgehend
- durchgehend oder blind

#### Senkbohrung / Zylindersenkung

Pflicht:

- Kerndurchmesser bzw. Bohrungsdurchmesser
- Senkdurchmesser
- Senkwinkel oder Senktiefe
- Lage `X/Y`

#### Passbohrung / Reibbohrung

Pflicht:

- Nennmass
- Passungsangabe oder Toleranz
- Lage `X/Y`

Nicht zulaessig:

- Gewinde nur als isolierter Text ohne Lagebezug
- Sackloch ohne Tiefe
- Passbohrung ohne Passung
- unklar, ob durchgehend oder blind

### 3. Gewinde

Gewinde sind immer explizit zu beschreiben.

Pflicht:

- Gewindeart
- Nenngroesse
- Anzahl
- Lage
- Gewindetiefe, wenn nicht durchgehend
- durchgehend oder blind

Kompakte Formen sind zulaessig, wenn gleiche Gewinde mehrfach vorkommen:

- `2x M6 durch`
- `4x M5`
- `M8 x 12 tief`

Nicht zulaessig:

- Gewinde nur graphisch angedeutet
- Gewinde ohne Lagebezug
- mehrere unterschiedliche Gewinde in einer Sammelangabe

### 4. Passungen

Passungen haben hohe Prioritaet und muessen immer explizit bemasst werden.

Pflicht:

- Nennmass
- Passungsangabe
- Lage
- Bezug zur Gegenfunktion, wenn bekannt

Regel:

- Passmasse duerfen nie als normales Durchmessermass ohne Passungsinformation behandelt werden

### 5. Taschen

Jede Tasche ist eine 3D- oder 2,5D-Bearbeitung und braucht zwingend eine Z-Information.

Probe-Voraussetzung:

- Taschenerkennung ist in `v1` noch nicht robust implementiert
- die Regel ist fachlich verpflichtend, aber aktuell nur dann voll umsetzbar,
  wenn der Probe die Tasche explizit liefert

Pflicht:

- Lage `X/Y`
- Laenge
- Breite
- Tiefe
- Eckradius oder Werkzeugradius, wenn relevant

Nicht zulaessig:

- Tasche nur in Draufsicht sichtbar
- Tiefe fehlt

### 6. Nuten

Probe-Voraussetzung:

- `slot_groups[].depth_mm` ist als Datenpfad fuer `v1` vorgesehen bzw.
  verfuegbar
- die Nutenregel ist deshalb teilweise umsetzbar, solange `depth_mm`
  konsistent geliefert wird

Pflicht:

- Lage
- Laenge
- Breite
- Tiefe
- Orientierung

Nicht zulaessig:

- Nut nur als Schlitz in Draufsicht
- keine Z-Information

### 7. Stufen / Absaetze

Probe-Voraussetzung:

- Stufenerkennung erfordert in `v1` eine Probe-Erweiterung
- ohne diese Probe-Erweiterung bleibt die Regel fachlich richtig, aber nur
  ueber Silhouetten- oder View-Fallbacks approximierbar

Pflicht:

- Lage
- Hoehe oder Tiefe
- Bezug
- Ausdehnung

Nicht zulaessig:

- sichtbare Stufe ohne Hoehenmass
- mehrere Ebenen ohne klare Z-Zuordnung

## Probe-Voraussetzungen in v1

| Regelbereich | In v1 direkt umsetzbar | Braucht Probe-Erweiterung |
| --- | --- | --- |
| Bohrungen | ja | nur fuer `durch/blind` und Tiefen-Details |
| Nuten / Schlitze | ja, wenn `slot_groups` inkl. Tiefe vorliegen | bei fehlender `depth_mm` |
| Taschen | teilweise | ja |
| Stufen / Absaetze | teilweise | ja |
| Gewinde / Passungen | teilweise | ja, wenn Text-/Toleranzinfos fehlen |

## Lochbilder und Wiederholungen

Kompakte Bemassung ist zulaessig, wenn folgende Punkte gleichzeitig erfuellt sind:

- Anzahl klar
- Typ klar
- Lage klar
- Bezug klar

Zulaessige Muster:

- symmetrisch zur Mittellinie
- auf Rechteckbild
- gleichmaessig verteilt
- gemeinsame Bezugsangabe
- identische Randabstaende

Nicht zulaessig:

- Symmetrie nur optisch vermutet
- Lochanzahl nicht textlich abgesichert
- Lage nur ungefaehr ableitbar
- mehrere identische Features ohne Wiederholangabe

## Ansichtslogik

Ansichten werden nach Fertigungsnutzen gewaehlt, nicht nach Menge.

### Hauptansicht

Soll zeigen:

- funktional wichtigste Seite
- Aussenkontur
- Hauptlochbild
- Hauptfeatures
- sichtbares Bezugssystem

### Zusatzansicht / Seitenansicht

Soll zeigen:

- Stufen
- Bearbeitungstiefen
- Sackloecher
- Taschen
- Nuttiefe
- Hoehenbezuege

### Schnittansicht

Ist Pflicht, wenn mindestens einer dieser Trigger zutrifft:

- verdeckte bearbeitungskritische Geometrie ist sonst nicht eindeutig
- mehrere Bearbeitungsebenen sind vorhanden
- Sackloecher oder Taschen sind sonst nicht sicher beschreibbar
- Innenkonturen waeren sonst nur ueber verdeckte Kanten erkennbar

#### Fallback bei nicht verfuegbarer Schnittansicht

Wenn keine automatische Schnittansicht erzeugt werden kann, gilt in `v1`
folgende Fallback-Reihenfolge:

1. verdeckte Kanten anzeigen
2. explizite Tiefen-Annotation ergaenzen, z. B. `Tasche t = 5,0`
3. Quality Check erzeugt `VIEW_SELECTION_ERROR`

Klarstellung:

- automatische Schnitterzeugung ist in `v1` optional
- die Infrastruktur fuer Section Views ist vorhanden, aber noch nicht fuer alle
  Milling-Faelle automatisch getriggert

### Isometrie

- nur Uebersicht
- keine Hauptmassrolle
- keine ueberladenen Fertigungsmasse

## View Ownership

Jedes Merkmal hat genau eine primaere Bemassungsansicht.
Eine zweite Ansicht darf dasselbe Merkmal nur dann wiederholen, wenn das Fertigungsverstaendnis sonst nicht eindeutig ist.

Default-Regeln:

- `Hauptansicht`: Lage, Funktion, Aussenkontur, Lochbilder, Hauptfeatures
- `Zusatzansicht`: Z-Masse, Stufen, Tiefen, Hoehenbeziehungen
- `Schnittansicht`: interne oder verdeckte Bearbeitungslogik

## Placement-Regeln

### Hauptansicht

- Aussenmasse ausserhalb der Kontur
- Positionsmasse systematisch von Primaer-/Sekundaerbezug
- Bohrungsgruppen zusammenhaengend und nicht verstreut
- keine zufaellige Mischbemassung ohne Bezugssystem

### Zusatzansicht

- Z-Informationen gruppiert
- Tiefenmasse nah an den betroffenen Features
- Stufen und Hoehen klar voneinander getrennt

### Schnittansicht

- nur die Schnitte zeigen, die echte Informationsluecken schliessen
- keine reine Dekoration
- Schnitt muss bearbeitungskritische Tiefe oder Innengeometrie erklaeren

### Abstandswerte

Die exakten Abstaende sind Renderer-Parameter und keine DSE-Entscheidung.

Normnahe Zielwerte fuer `v1`:

- Konturabstand erste Masslinie: `>= 6,0 mm`
- Staffelung weiterer Masslinien: `>= 6,0 mm`
- Ueberstand der Extensionslinien ueber die Masslinie: `1,5 mm`

Interpretation:

- die Leitlinie definiert die Ordnungsgrenzen
- der Renderer verantwortet die konkrete Parametrisierung und Kollisionen

## Verdeckte Kanten

Verdeckte Kanten duerfen nie die einzige Informationsquelle fuer fertigungskritische Geometrie sein.

Wenn ein Merkmal verdeckt und relevant ist:

- Schnittansicht bevorzugen
- Detailansicht bevorzugen
- oder explizite Tiefen-/Featureangabe ergaenzen

### Interimsstrategie (v1)

Bis zur feineren Feature-Erkennung fuer verdeckte Geometrie gilt:

1. verdeckte Kanten werden standardmaessig gerendert
2. `hidden_edge_load` und `hidden_ratio` werden pro Ansicht bewertet
3. bei `hidden_ratio >= 0.14` entsteht mindestens eine Schnittempfehlung und
   ein `VIEW_SELECTION_ERROR`
4. Feature-Level-Erkennung, welches konkrete Merkmal nur verdeckt sichtbar ist,
   bleibt `v2`

## Funktionsmasse vor Schoenheitsmassen

Hohe Prioritaet:

- Achsabstaende
- Sitzmasse
- Mittenabstaende
- Einbaumasse
- Referenzflaechen
- Lagebeziehungen von Bohrungen, Taschen und Nuten
- pruefentscheidende Masse

Niedrige Prioritaet:

- triviale Zwischenmasse
- dekorative Vollstaendigkeit
- doppelte Aussenmasse
- Masse ohne Montage-, Pruef- oder Fertigungsbezug

## Titelblock und Hinweisfeld

Pflicht fuer Fraesteile:

- Werkstoff
- Masseinheit
- Allgemeintoleranz
- Entgrathinweis

Optional je nach Teil:

- Oberflaechenangabe
- Kantenbruch
- Waermebehandlung
- Beschichtung

Qualitaetsregel:

- fehlender Werkstoff = mindestens `TITLEBLOCK_INCOMPLETE`
- fehlende Masseinheit = `TITLEBLOCK_INCOMPLETE`

## Entscheidungsalgorithmus pro Feature

Fuer jedes erkannte Feature wird diese Reihenfolge angewendet:

### Frage 1

Ist das Feature:

- funktional
- montagekritisch
- pruefrelevant
- bearbeitungskritisch

Wenn `ja`:

- eindeutig bemassen

### Frage 2

Ist das Feature eine Bohrung?

Wenn `ja`:

- Typ klassifizieren
- bohrungsspezifische Pflichtangaben setzen

### Frage 3

Ist das Feature ein Gewinde?

Wenn `ja`:

- Gewindedaten explizit angeben

### Frage 4

Ist das Feature eine Passung?

Wenn `ja`:

- Passungsangabe explizit angeben

### Frage 5

Ist das Feature eine Tasche, Nut, Stufe oder ein Absatz?

Wenn `ja`:

- Z-Information zwingend ergaenzen

### Frage 6

Ist das Feature ohne Einzelbemassung vollstaendig ableitbar ueber:

- Symmetrie
- Wiederholung
- Lochbild
- gemeinsames Raster
- gleiche Randabstaende

Wenn `ja`:

- kompakte Bemassung zulaessig

### Frage 7

Entsteht durch zusaetzliche Bemassung nur Wiederholung oder Ueberladung?

Wenn `ja`:

- Mass unterdruecken

### Frage 8

Wuerde ein CAM-Programmierer ohne Rueckfrage wissen:

- was das Feature ist
- wo es liegt
- wie tief es ist
- ob es durchgehend oder blind ist
- wie es hergestellt werden soll

Wenn `nein`:

- zusaetzliche Bemassung oder Schnittansicht ergaenzen

## Fehlerabbildung auf Drawform-Fehlerklassen

- fehlende Tiefe bei Tasche/Nut/Stufe -> `DIMENSION_MISSING`
- unklare Bohrungs- oder Gewindedefinition -> `HOLE_PATTERN_UNCLEAR`
- doppelte oder wiederholte Featuremasse -> `DIMENSION_REDUNDANT`
- verstreute featurefremde Platzierung -> `DIMENSION_POOR_PLACEMENT`
- verdeckte Geometrie ohne klaerenden Schnitt -> `VIEW_SELECTION_ERROR`
- Pflichtangaben im Titelblock fehlen -> `TITLEBLOCK_INCOMPLETE`

## Mindestregeln fuer v1-Implementierung

Diese Regeln muessen in `v1` hart umgesetzt werden:

1. `milling` wird mindestens in `plate_2p5d`, `block_prismatic` und `feature_dense` unterteilt.
2. Fraesteile werden feature-basiert statt silhouettenbasiert bemasst.
3. Bohrungen werden typisiert und nicht nur als Kreis behandelt.
4. Gewinde und Passungen muessen textlich vollstaendig beschrieben werden.
5. Taschen, Nuten und Stufen brauchen zwingend eine Z-Information.
6. Hauptansicht traegt Funktion und Lage; Zusatzansicht oder Schnitt traegt Z-Information.
7. Bezugssystem ist verpflichtend.
8. Verdeckte Kanten duerfen nie allein die Fertigungslogik tragen.

## Ableitung fuer den Code

### `server/freecad/step_feature_probe.py`

Soll liefern:

- Feature-Typen statt nur Konturhinweisen
- Tiefe, Blind/Durchgang, Senkung, Passungs- oder Gewindehinweise soweit erkennbar
- Trigger fuer Schnittpflicht und Mehr-Ebenen-Geometrie

### `server/rules/dimension_strategy.py`

Soll entscheiden:

- milling-Unterfamilie
- primaere Bemassungsansicht je Feature
- kompakte vs. volle Bemassung
- Bezugssystem fuer Positionsmasse

### `server/freecad/step_to_pdf.py`

Soll umsetzen:

- View Ownership
- Gruppierung nach Bezuegen und Featurearten
- systematische Trennung von Lage- und Z-Massen
- Vermeidung redundanter Featurebemassung

### `server/test_views.py`

Soll pruefen:

- keine bearbeitungskritischen Features ohne Typ- oder Tiefeninformation
- keine unzulaessige Massdopplung
- keine rein silhouettenbasierte Fraeslogik
- Pflichtangaben im Titelblock

## Nichtziel fuer v1

Diese Spezifikation verlangt noch nicht:

- vollstaendige GD&T-Abdeckung
- automatische Werkzeugwahl
- vollautomatische CAM-Strategie
- komplexe 5-Achs-Bearbeitungsplanung
- vollstaendige Freiform-/Surfacing-Logik
- Einzeltoleranzen
- formale GD&T-Rahmen nach ISO 1101
- Passungstoleranzbereiche ueber die textliche Angabe hinaus

Klarstellung:

- `v1` erwartet eine Allgemeintoleranz `DIN ISO 2768-mK` im Titelblock
- individuelle Toleranzen sind `v2`-Scope

## Kurzform

- Fertigung vor Geometrieoptik
- Bezugssystem ist Pflicht
- Features statt Silhouetten bemassen
- Bohrungen typisieren
- Gewinde und Passungen explizit angeben
- Taschen, Nuten und Stufen brauchen Tiefe
- Hauptansicht fuer Funktion
- Zusatzansicht oder Schnitt fuer Z-Information
- Lochbilder kompakt, aber eindeutig
- keine unnoetige Massdopplung
- CAM muss die Zeichnung ohne Raten verstehen

## Umsetzungsstand 2026-04-04

Diese Leitlinie ist in Drawform fuer `v1` nur teilweise umgesetzt.
Der aktuelle Stand ist fuer die zuletzt bearbeitete Fraesteil-Iteration mit
`21631_03_141_gripper finger_486.STEP` nachgezogen.

### Bereits umgesetzt

- projizierte Lochzentren duerfen fuer `milling` aus dem Feature-Probe in die
  orthografische Frontalansicht uebernommen werden
- daraus werden Centerlines sowie Lochlage- und Pitch-Masse auch dann erzeugt,
  wenn im SVG selbst keine sichtbaren Kreise extrahiert werden koennen
- der 2-Loch-Fall wird nicht mehr nur deshalb unterdrueckt, weil der Probe
  `axis_median` statt `linear_pattern` meldet
- fuer Fraesteile wird eine dritte Gesamtabmessung auf der linken Ansicht
  mitgefuehrt
- die Aussenplatzierung fuer gedrehte Fraes-Frontansichten ist fuer Milling
  konservativer als fuer Blechteile

### Am Referenzfall verifiziert

Referenzteil:

- `21631_03_141_gripper finger_486.STEP`

Verbesserungen im aktuellen Lauf:

- Frontansicht zeigt jetzt `hole_diameter`, `hole_location_x`,
  `hole_location_y` und `hole_pitch`
- `centerline_total = 2`
- `Front.feature_dim_text_count = 4`
- die Bohrungen sind damit nicht mehr nur als isoliertes `D2,5` sichtbar,
  sondern als Featuregruppe beschrieben

Mitgepruefte Kontrollfaelle:

- `complex_bracket` -> `pre_export_check = OK`
- `feature_test_part` -> `pre_export_check = OK`
- `housing` -> `pre_export_check = OK`

### Noch nicht erreicht

- Bohrungstyp bleibt offen, solange der Probe nicht sicher `durch` oder
  `blind/tief` erkennt
- Z-Logik fuer Taschen, Nuten, Stufen und Absaetze ist weiterhin nur
  unvollstaendig vorhanden
- Fasen-/Chamfer-Logik ist im Renderer vorbereitet, aber noch nicht robust in
  die Milling-DSE eingebunden
- der Referenzfall meldet weiter
  `Ansichten ueberlagern sich: Front vs Top`
- die Zeichnung ist damit fachlich verbessert, aber noch nicht voll
  fertigungstauglich

### Konsequenz fuer die weitere Umsetzung

Die naechsten verbindlichen Schritte fuer `milling` sind:

1. `step_feature_probe.py`: Bohrungstyp, Tiefe und `durch/blind` robuster
   ableiten
2. `dimension_strategy.py`: Taschen, Nuten, Stufen und Chamfer-Masse
   feature-basiert planen
3. `step_to_pdf.py`: verbleibenden Rotations-/Bounds-Konflikt bei gedrehten
   Fraes-Frontansichten aufloesen
