# Literatur-Review Fertigungszeichnungen fuer Drawform

Stand: 2026-03-18

Ziel dieser Auswertung ist, die neu abgelegte Literatur in `server/knowledge/Literatur`
auf konkrete, fuer Drawform nutzbare Regeln fuer Fertigungszeichnungen zu verdichten.
Die Inhalte hier sind absichtlich nicht normvollstaendig. Sie uebersetzen die
Literatur in KB-taugliche Folgerungen fuer Ansichtslogik, Bemaessung, Tolerierung,
Oberflaechen, Gewinde und Schweissangaben.

## 1. Relevanzbewertung der gesichteten Dateien

### Primaer nutzbar

- `Tabellenbuch Metall.pdf`
  - Relevante Seiten: 64-97.
  - Nutztbare Themen: Zeichenblaetter, Linienarten und Linienbreiten, Vorderansicht,
    Projektionsmethode, Schnittregeln, Bemaessung, Toleranzangaben, Werkstueckkanten,
    Gewinde-, Loch-, Schweiss- und Oberflaechenangaben.
  - Nutzen fuer Drawform: beste Quelle fuer konkrete Darstellungs- und
    Zeichnungsheuristiken auf Blatt- und View-Ebene.

- `RoloffMatek_21.Auflage.pdf`
  - Relevante Seiten: 48-60.
  - Nutzbare Themen: Toleranzphilosophie, Maß-/Form-/Lagetoleranzen,
    Toleranzangaben in Zeichnungen, ISO-Passsysteme, Unabhaengigkeitsprinzip,
    Oberflaechenkenngroessen und Oberflaechenangaben.
  - Nutzen fuer Drawform: starke Quelle fuer die Frage, welche Toleranz-,
    Passungs- und Oberflaecheninformationen eine technisch brauchbare
    Fertigungszeichnung tragen muss.

- `Roloff Matek Maschinenelemente Normung Berechnung Gestaltung 2009.pdf`
  - Relevante Seiten: 39-54.
  - Nutzbare Themen: inhaltliche Bestaetigung der Regeln aus der neueren
    Roloff/Matek-Auflage zu Toleranzen, Passungen und Oberflaechen.
  - Nutzen fuer Drawform: zweite, unabhaengige Bestaetigung derselben
    Zeichen- und Toleranzlogik.

- `Toleranzen und Passungen.pdf`
  - Relevante Seiten: 1-11.
  - Nutzbare Themen: System Einheitsbohrung vs. Einheitswelle, Prioritaetspassungen,
    Passungsarten, Passungsauswahl nach Funktion, ISO-2768-Hinweise.
  - Nutzen fuer Drawform: pragmatische Bruecke zwischen Normsystem und
    werkstattnaher Passungsauswahl.

### Sekundaer / niedrige Relevanz

- `Roloff-Matek_-_Tabellenbuch.pdf`
  - Die Datei war in der vorliegenden Form textlich schlecht erschliessbar.
  - Vermutlich inhaltlich ueberlappend mit `Tabellenbuch Metall.pdf`.
  - Fuer diese Iteration nicht als Primaerquelle verwendet.

- `Formeln-und-Tabellen-Technische-Mechanik_Boege.pdf`
  - Kaum direkte Relevanz fuer Fertigungszeichnungen.
  - Inhaltlich ueberwiegend Rechenhilfen zur Mechanik, nicht zur Zeichnungsnormik
    oder Zeichnungsqualitaet.

## 2. Was fuer Fertigungszeichnungen wirklich relevant ist

### 2.1 Ansichtslogik und Projektion

- Die Vorderansicht soll die Ansicht sein, die Form und Abmessungen am besten
  erklaert.
- Weitere Ansichten sind auf das notwendige Minimum zu beschraenken.
- Zusatzausichten sollen moeglichst wenig verdeckte Kanten enthalten.
- Projektion muss eindeutig ueber das Projektionssymbol kenntlich sein.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 68-71

Drawform-Folge:
- Die View-Auswahl sollte nicht nur nach Bounding-Box laufen, sondern nach
  Informationsdichte, Lesbarkeit und Hidden-Edge-Last.

### 2.2 Schnittregeln

- In Schnitten sollen verdeckte Kanten im Regelfall nicht dargestellt werden.
- Schrauben, Stifte, Wellen sowie Rippen und Stege werden in Laengsrichtung
  nicht geschnitten.
- Halbschnitte sind fuer symmetrische Werkstuecke sinnvoll, wenn die Mittellogik
  klar bleibt.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 72-74

Drawform-Folge:
- Section- oder Hidden-Line-Logik darf innere Klarheit nicht durch doppelte
  Information verschlechtern.

### 2.3 Bemaessungslogik

- Jedes Maß soll nur einmal eingetragen werden.
- Bemaessung gehoert in die Ansicht, in der die Form am besten erkennbar ist.
- Geschlossene Maßketten sind zu vermeiden.
- Wiederkehrende Geometrieelemente sollen ueber Anzahl, Teilung und
  Gesamtlaenge oder Gesamtwinkel definiert werden.
- Koordinatenbemaessung ist fuer Lochbilder und wiederholte Features sinnvoll.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 75-82
- `RoloffMatek_21.Auflage.pdf`, S. 52-53

Drawform-Folge:
- Die DSE braucht spaeter explizite Guards gegen geschlossene Ketten und
  sollte Lochbilder bevorzugt ueber Referenzkanten/Datums statt chaotischer
  Kettenmasse definieren.

### 2.4 Toleranzphilosophie und Allgemeintoleranzen

- Nicht jede Abmessung muss einzeln toleriert werden.
- Allgemeintoleranzen sind fuer nicht funktionskritische Masse sinnvoll und
  sollen klar auf der Zeichnung angegeben werden.
- Toleranzen sind nach dem Grundsatz "so grob wie moeglich, so fein wie noetig"
  zu waehlen.
- Form- und Lagetoleranzen sind dann noetig, wenn Fertigungsprozess und
  Funktionsbezug sonst nicht sicher genug beschrieben sind.

Evidenz:
- `RoloffMatek_21.Auflage.pdf`, S. 48-53
- `Roloff Matek Maschinenelemente Normung Berechnung Gestaltung 2009.pdf`, S. 39-44
- `Toleranzen und Passungen.pdf`, S. 1-2, 11

Drawform-Folge:
- Drawform sollte nicht versuchen, jedes Maß einzeln zu verfeinern, sondern
  zwischen Allgemeintoleranz, Funktionsmaß und expliziter Form-/Lagetoleranz
  unterscheiden.

### 2.5 Passungen und Bevorzugung des Einheitsbohrungssystems

- In der Praxis wird das System Einheitsbohrung haeufig bevorzugt.
- Passungsauswahl ist funktional zu treffen: Spiel-, Uebergangs- oder
  Uebermaßpassung je nach Montierbarkeit, Fuehrung und Kraftuebertragung.
- Prioritaetspassungen sind wirtschaftlich sinnvoll, wenn nichts dagegen spricht.

Evidenz:
- `RoloffMatek_21.Auflage.pdf`, S. 53-57
- `Roloff Matek Maschinenelemente Normung Berechnung Gestaltung 2009.pdf`, S. 44-47
- `Toleranzen und Passungen.pdf`, S. 5-8

Drawform-Folge:
- Wenn Drawform spaeter Passungen oder Fertigungshinweise ausgibt, sollte das
  System Einheitsbohrung Default sein, solange kein guter Grund fuer
  Einheitswelle vorliegt.

### 2.6 Unabhaengigkeitsprinzip, GD&T und Datums

- Maß-, Form- und Lagetoleranzen sind grundsaetzlich unabhaengig voneinander,
  sofern auf der Zeichnung nichts anderes verlangt wird.
- GD&T ist vor allem fuer funktionskritische Flaechen sinnvoll.
- Der Toleranzrahmen folgt einer klaren Reihenfolge:
  Toleranzsymbol, Toleranzwert, danach bei Bedarf die Bezuege.

Evidenz:
- `RoloffMatek_21.Auflage.pdf`, S. 52-57
- `Roloff Matek Maschinenelemente Normung Berechnung Gestaltung 2009.pdf`, S. 43-47

Drawform-Folge:
- GD&T sollte nur dort erzwungen werden, wo Funktion, Montage oder Pruefbarkeit
  das wirklich verlangen.

### 2.7 Oberflaechenangaben

- Oberflaechen sind nicht pauschal ueberall zu spezifizieren, sondern dort, wo
  Funktion oder Fertigungsverfahren sie relevant macht.
- Wichtige Stellen sind Dicht-, Lager-, Gleit- und Passflaechen.
- Die Zeichnungssymbolik muss Fertigungsverfahren, Kennwert und bei Bedarf
  Richtungsangabe tragen koennen.
- Rauheit und Maßtoleranz stehen praktisch in Beziehung und sollten nicht
  widerspruechlich gewaehlt werden.

Evidenz:
- `RoloffMatek_21.Auflage.pdf`, S. 57-60
- `Roloff Matek Maschinenelemente Normung Berechnung Gestaltung 2009.pdf`, S. 47-50
- `Tabellenbuch Metall.pdf`, S. 96-97

Drawform-Folge:
- Oberflaechenregeln sollten funktionale Flaechen bevorzugen statt eine
  flaechige Default-Ueberannotation zu erzeugen.

### 2.8 Kantenzustand und Entgraten

- Werkstueckkanten muessen entweder explizit oder ueber Sammelangabe
  beschrieben werden.
- Eine allgemeine Entgratungsnotiz ist der minimale sichere Standard, wenn keine
  kritischen Einzelkanten hervorgehoben werden.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 87

Drawform-Folge:
- Die aktuelle allgemeine Kanten-Notiz ist fachlich sinnvoll; spaeter sollten
  kritische Kanten explizit ausgezeichnet werden koennen.

### 2.9 Loch- und Gewindedarstellung

- Wiederholte Lochbilder brauchen Anzahl, Teilung und Referenz.
- Gestufte Bohrungen, Senkungen und Gewinde sollen ueber vereinfachte, aber
  vollstaendige Callouts beschrieben werden.
- Bei Gewinden sind Richtung (LH/RH), gegebenenfalls Steigung und nutzbare
  Gewindelaenge relevante Zeichnungsinformationen.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 78, 82, 88-89
- `RoloffMatek_21.Auflage.pdf`, S. 52-56

Drawform-Folge:
- Die Feature-Erkennung sollte spaeter zwischen Durchgangsloch, Gewindeloch,
  Senkung und Stufenbohrung unterscheiden.

### 2.10 Schweissangaben

- Schweissnähte muessen mit standardisierter Symbolik, Bezugs- und Pfeillinie
  beschrieben werden.
- Pfeilseite/Gegenseite, Nahtart sowie a- oder z-Maße sind zentral.
- Unterbrochene und versetzte Nähte brauchen Laenge, Abstand und gegebenenfalls
  Vormass.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 92-95

Drawform-Folge:
- Die bestehende KB-Regel fuer Schweisssymbole ist fachlich richtig und kann
  als approved behandelt werden.

### 2.11 Frontansicht bei Gleichstand

- Wenn mehrere moegliche Vorderansichten aehnlich viel Geometrie erklaeren,
  soll die Ansicht bevorzugt werden, die funktionale, bearbeitete oder
  montagekritische Flaechen direkt zeigt.
- Eine reine Achs- oder Bounding-Box-Logik reicht fuer diese Entscheidung
  nicht aus.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 68-71
- `RoloffMatek_21.Auflage.pdf`, S. 52-53

Drawform-Folge:
- Die KB braucht eine explizite Tie-Break-Regel fuer Frontansichten, damit
  spaetere View-Scorer nicht nur auf Geometriegleichstand oder feste
  Achs-Prioritaeten zurueckfallen.

### 2.12 Schnitt vor Hidden-Line-Clutter

- Wenn eine Zusatzansicht hauptsaechlich aus verdeckten Kanten bestehen
  wuerde, ist ein Voll-, Halb- oder Teilschnitt oft die klarere Darstellung.
- Ein Schnitt ist dabei kein Zusatzballast, sondern ein Mittel zur
  Informationsreduktion.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 72-74

Drawform-Folge:
- Die KB sollte nicht nur Hidden Lines im Schnitt regeln, sondern auch die
  Entscheidung unterstuetzen, wann ein Schnitt einer weiteren verdeckten
  Ansicht vorzuziehen ist.

### 2.13 Bemaessungsdichte und Layout-Eskalation

- Eine Zeichnung wird unbrauchbar, wenn Masse, Masslinien oder Texte trotz
  formaler Vollstaendigkeit zu dicht werden.
- In solchen Faellen ist die richtige Reaktion nicht weitere Verdichtung,
  sondern Verteilung auf andere Ansichten, Detailansichten, Massstabsanpassung
  oder Blatteskalation.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 64-82
- `DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`

Drawform-Folge:
- Die KB braucht operative Regeln fuer die Eskalation bei
  Bemaessungsueberfrachtung, damit Layoutfehler nicht erst spaet im
  Pre-Export-Check auffallen.

### 2.14 Detailansichten fuer kleine oder dichte Funktionsmerkmale

- Kleine, eng gruppierte oder callout-intensive Features sollen bei Bedarf in
  vergroesserten Detailansichten statt in der Hauptansicht spezifiziert werden.
- Das gilt besonders fuer Gewinde, Senkungen, kleine Radien, Taschen und enge
  Lochgruppen.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 75-82, 88-89
- `RoloffMatek_21.Auflage.pdf`, S. 52-56

Drawform-Folge:
- Die KB sollte Trigger fuer Detailansichten definieren, damit spaetere
  Renderer und Planner zwischen normaler Zusatzansicht und vergroessertem
  Detail unterscheiden koennen.

### 2.15 Symmetrie, Mittellinien und funktionale Bezuege

- Symmetrische und rotationsbezogene Geometrien sollen ueber Mittellinien,
  Achsen oder Bezugsmerkmale bemaesst werden, nicht ueber improvisierte
  Kettenmasse.
- Mittellinien sind nicht nur grafische Dekoration, sondern tragende
  Referenzen fuer professionelle Bemaessung.

Evidenz:
- `Tabellenbuch Metall.pdf`, S. 66-67, 75-82
- `RoloffMatek_21.Auflage.pdf`, S. 52-57

Drawform-Folge:
- Die KB braucht eine explizite Regel, symmetrische oder runde Features
  bevorzugt an Achsen und Mittellinien zu referenzieren.

## 3. Konkrete KB-Folgerungen

### Sofort in die KB aufnehmen

- View-Auswahl nach Informationswert und minimaler Hidden-Edge-Last.
- Tie-Break-Regel fuer Frontansichten nach Funktions-, Bearbeitungs- und
  Montagebezug.
- Verbot geschlossener Maßketten.
- Dimensionierung wiederholter Features ueber Anzahl, Teilung und Referenz.
- Bevorzugung koordinatenartiger Lochbildbemaessung gegenueber chaotischer
  Muster-Kettenbemaessung.
- Schnittregeln: keine versteckten Kanten im Schnitt, keine Laengsschnitte
  durch Wellen/Schrauben/Stifte/Rippen.
- Regel: Schnitt oder Teilschnitt vor weiterer hidden-line-lastiger Zusatzansicht.
- Detailansichten fuer kleine oder callout-dichte Funktionsmerkmale.
- Layout-Eskalation bei Bemaessungsdichte: Verteilung, Massstab oder Blattgroesse
  statt weiterer Verdichtung.
- Symmetrie- und Mittellinienregeln als bevorzugte Bemaessungsreferenz.
- Vollstaendigere Regeln fuer Gewinde-/Sonderloch-Callouts.
- Bevorzugung des Einheitsbohrungssystems fuer spaetere Passungslogik.

### Bestehende KB-Regeln, die die Literatur klar stuetzt

- `surface_roughness_indication`
- `welding_symbol_iso_2553`
- `gdt_feature_control_frame`

## 4. Wichtigste technische Konsequenzen fuer Drawform

1. Die groesste Luecke liegt nicht bei einzelnen Maßzahlen, sondern bei
   Ansichtslogik, Schnittregeln und strukturierter Lochbildbemaessung.
2. Die Literatur bestaetigt klar, dass professionelle Zeichnungen nicht nur
   Maße brauchen, sondern auch eine disziplinierte Informationsselektion.
3. Hidden edges, geschlossene Maßketten und unnoetige Zusatzansichten sind
   typische Ursachen fuer unprofessionell wirkende Zeichnungen.
4. Passungen, Oberflaechen und GD&T sollten funktional und selektiv eingesetzt
   werden, nicht flaechendeckend.
5. Fuer reale Fertigungszeichnungen ist das Zusammenspiel von
   Allgemeintoleranz, Funktionsmassen, Lochbilddefinition und Kanten-/Oberflaechenangaben
   entscheidender als ein formal erfolgreicher PDF-Export.

## 5. Priorisierte naechste Code-Schritte

1. Front-/Top-/Left-Auswahl mit Score fuer Informationsdichte und Hidden-Edge-Penalty.
2. DSE-Guard gegen geschlossene Maßketten und Dimensionsplatzierung nur in
   der geometrisch sinnvollsten Ansicht.
3. Feature-Probe-Erweiterung fuer Senkungen, Stufenbohrungen, Gewindelaenge,
   Linksgewinde und wiederholte Lochmuster.
4. Schnittlogik in Renderer und Critic explizit aufnehmen.
5. Titelblock-/Notizlogik fuer Oberflaechen, Kanten und Schweisshinweise
   modularisieren, damit sie nur bei Bedarf erscheinen.
