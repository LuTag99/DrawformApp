# Priorisierter Referenz-Backlog

Dieser Backlog leitet aus dem Referenzkorpus in
`reference_drawings_index.json` die naechsten Pflichtfaelle fuer
`Planner -> Builder -> Critic` ab.

## Auswahlbasis

Sortierung nach:

1. `comparison.occupancy_l1` als grobe Layout-Abweichung zur Musterzeichnung
2. zusaetzlichen Flags wie `font_too_small`, `sheet_mismatch`, `abwicklung_mismatch`
3. STEP-Kontext, damit flache Teile, Lochbilder und gebogene Blechteile gemeinsam abgedeckt sind

## Top-5 Pflichtfaelle

| Prioritaet | Teil | Typ | Kritische Metriken | Hauptfehlerklassen |
| --- | --- | --- | --- | --- |
| 1 | `logiBOT_02_AbdeckblechSeitlichSpie_V1.1` | flaches Blechteil | `occupancy_l1=0.0657`, `font_ratio=0.578`, sehr geringe Zeichnungsdichte | `SCALE_LAYOUT_ERROR`, `SHEET_SPACE_WASTE`, `DIMENSION_POOR_PLACEMENT` |
| 2 | `202500521_EOAT verlängerung_V1.0` | flaches Teil mit 18 Bohrungen | `occupancy_l1=0.0564`, `font_ratio=0.578`, `dim_ratio=0.783` | `SCALE_LAYOUT_ERROR`, `HOLE_PATTERN_UNCLEAR`, `DIMENSION_POOR_PLACEMENT` |
| 3 | `logiBOT_02_AbdeckblechOben_V1.0` | flaches Blechteil mit 5 Bohrungen | `occupancy_l1=0.0554`, `font_ratio=0.578`, `dim_ratio=0.667` | `VIEW_SELECTION_ERROR`, `SCALE_LAYOUT_ERROR`, `DIMENSION_MISSING` |
| 4 | `202500521_Z-Verlängerung EOAT 1_V1.0` | flaches Teil mit 17 Bohrungen | `occupancy_l1=0.0531`, `font_ratio=0.578`, `dim_ratio=0.560` | `HOLE_PATTERN_UNCLEAR`, `DIMENSION_MISSING`, `DIMENSION_POOR_PLACEMENT` |
| 5 | `logiBOT_02_Dämpfhalter_V1.0` | gebogenes/aufgestelltes Blechteil | `occupancy_l1=0.0518`, `font_ratio=0.578` | `VIEW_SELECTION_ERROR`, `VIEW_ALIGNMENT_ERROR`, `SCALE_LAYOUT_ERROR` |

## Gemeinsame Root Causes

### 1. Schrift und Masszahlen sind systematisch zu klein

Fast der gesamte reale Referenzsatz liegt bei `font_ratio ~= 0.578`.
Das ist kein Einzelfall, sondern ein globaler Render- und Layoutfehler.

Betroffene Module:

- `server/freecad/step_to_pdf.py`
- Titelblock-/Textstil-Logik im Exportpfad

Technische Folgerung:

- Textgroessen muessen aus Blattformat, View-Skalierung und Massart abgeleitet werden.
- Das aktuelle feste Niveau ist gegen die Musterzeichnungen klar zu klein.

### 2. Die Zeichnungen nutzen zu wenig Blattflaeche

Die groessten Problemfaelle haben durchgehend negatives
`raster_bbox_ratio_delta`. Die generierten Inhalte belegen also weniger
nutzbare Flaeche als die Musterzeichnungen.

Betroffene Module:

- `server/freecad/step_to_pdf.py`
- View-Frame- und Fit-Logik

Technische Folgerung:

- Hauptansicht, Nebenansichten und Isometrie muessen aggressiver nach
  Informationsgehalt statt nach starrem Raster platziert werden.

### 3. Flache Teile mit Lochmustern sind weiterhin die groesste Schwachstelle

Drei der Top-5-Faelle sind flache Teile mit 5 bis 18 Bohrungen.
Gerade dort sind die Musterzeichnungen deutlich dichter, klarer und
funktionsorientierter als unsere Outputs.

Betroffene Module:

- `server/freecad/step_feature_probe.py`
- `server/rules/dimension_strategy.py`
- `server/freecad/step_to_pdf.py`

Technische Folgerung:

- Lochbilder muessen als Featuregruppen und nicht als lose Kreisfunde behandelt werden.
- Der `dimension_plan` muss Positions- und Musterlogik tragen.

### 4. Titelblock und Zusatzinformationen muessen neutral bewertet werden

`SPIE` wird im Referenzbestand als Logo-Platzhalter interpretiert und nicht als
qualitativer Fehlfund gewertet. Relevant bleibt nur, ob der Titelblock lesbar,
vollstaendig und professionell wirkt.

Betroffene Module:

- `server/freecad/step_to_pdf.py`
- Titleblock- und Annotation-Assemblierung

Technische Folgerung:

- Der Export muss Titelblock und Zusatzinformationen professionell und neutral
  platzieren, ohne Platzhaltertexte ueberzubewerten.

## Naechster Builder/Critic-Arbeitsstapel

### Welle 1: globale Lesbarkeit und Blattnutzung

Ziel:

- Textgroesse hochziehen
- Hauptansicht vergroessern
- Isometrie weiter nachrangig machen
- redundante Leerrasterwirkung reduzieren

Pflicht-Regression:

- `logiBOT_02_AbdeckblechSeitlichSpie_V1.1`
- `202500521_EOAT verlängerung_V1.0`
- `logiBOT_02_Dämpfhalter_V1.0`

### Welle 2: Lochbild- und Flachteil-Bemaessung

Ziel:

- echte Lochmuster erkennen
- planbasierte Lochbild-Callouts rendern
- chaotische Einzelmasse vermeiden

Pflicht-Regression:

- `202500521_EOAT verlängerung_V1.0`
- `202500521_Z-Verlängerung EOAT 1_V1.0`
- `logiBOT_02_AbdeckblechOben_V1.0`

### Welle 3: Blechteil-spezifische Ansichten und Neutralisierung

Ziel:

- bessere Hauptansicht fuer gebogene Blechteile
- Abwicklung korrekt nur dann zeigen, wenn fachlich passend
- Branding sicher entfernen

Pflicht-Regression:

- `logiBOT_02_AbdeckblechSeitlichSpie_V1.1`
- `logiBOT_02_Dämpfhalter_V1.0`
- `logiBOT_02_AbdeckblechVorne_V1.0`

## Critic-Grenzen fuer die naechste Runde

Ein Fall gilt erst dann als bestandene Referenzverbesserung, wenn:

- kein `font_too_small` mehr gesetzt ist
- `occupancy_l1 <= 0.0400`
- kein offensichtlicher Blattformat- oder Abwicklungsfehler vorliegt
- die Zeichnung visuell nicht mehr wie ein leerer Raster-Export wirkt

## Nutzung im Alltag

1. `python server/build_reference_learning.py --refresh-exports --render-contact-sheets`
2. `priority_backlog.md` lesen
3. naechste Builder-Iteration nur gegen die Pflichtfaelle fahren
4. danach den Korpus erneut bauen und die Flag-Entwicklung pruefen
