# Musterzeichnungen als Lerninhalt

Diese Datei wird aus den realen STEP/PDF-Paaren in `server/_samples` erzeugt.
Sie dient als wiederverwendbarer Referenzbestand fuer Layout-, Bemaessungs- und Norm-Reviews.

## Datensatz
- Teile gesamt: 28
- Blattformat-Mismatches: 2
- Abwicklungs-Mismatches: 3
- SPIE-/Logo-Platzhalterfunde im Output: 2
- Durchschnitt Font-Ratio: 0.5935
- Durchschnitt Dimensions-Ratio: 0.8129
- Durchschnitt Layout-Divergenz (occupancy L1): 0.0447

## Hauefigste Abweichungsflags
- `font_too_small`: 26
- `layout_diverges`: 23
- `abwicklung_mismatch`: 3
- `sheet_mismatch`: 2

## Teile mit der groessten Layout-Divergenz
| Teil | Flat | Lochzahl | Dicke mm | Font-Ratio | Dim-Ratio | Layout-L1 | Flags |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| logiBOT_02_AbdeckblechSeitlichSpie_V1.1 | True | 0 | 2.0 | 0.642 | 0.857 | 0.0649 | font_too_small, layout_diverges |
| 202500521_EOAT verlängerung_V1.0 | True | 18 | 0.3 | 0.642 | 0.783 | 0.0578 | font_too_small, layout_diverges |
| logiBOT_02_AbdeckblechOben_V1.0 | True | 5 | None | 0.578 | 0.667 | 0.0554 | font_too_small, layout_diverges |
| 202500521_Z-Verlängerung EOAT 1_V1.0 | True | 17 | 0.15 | 0.578 | 0.56 | 0.0531 | font_too_small, layout_diverges |
| logiBOT_02_Abdeckblech Tasche_V1.0 | True | 15 | 0.25 | 0.578 | 1.043 | 0.0506 | font_too_small, layout_diverges |
| logiBOT_02_Dämpfhalter_V1.0 | False | 6 | 3.0 | 0.642 | 1.0 | 0.0492 | font_too_small, layout_diverges |
| 202500260_02_EoAT_Formhand Zwischenstück_V1.0 | True | 16 | 3.0 | 0.578 | 0.905 | 0.0472 | font_too_small, layout_diverges |
| logiBOT_02_AbdeckblechVorne_V1.0 | False | 8 | 2.0 | 0.578 | 0.647 | 0.0471 | abwicklung_mismatch, font_too_small, layout_diverges |
| 202500521_Halteblech Lackierpistole_V1.0 | False | 14 | 0.25 | 0.578 | 0.75 | 0.0453 | font_too_small, layout_diverges |
| 202500521_Laufblech Energiekette | False | 62 | 3.0 | 0.578 | 1.091 | 0.0452 | sheet_mismatch, font_too_small, layout_diverges |
| 202500260_02_EoAT_UR Adapter_V1.0 | True | 16 | 0.5 | 0.578 | 0.95 | 0.0446 | font_too_small, layout_diverges |
| logiBOT_02_Abdeckblech Hinten_Einpress_V1.0 | False | 10 | 0.31 | 0.578 | 0.95 | 0.0446 | abwicklung_mismatch, font_too_small, layout_diverges |

## Nutzung
1. `python server/build_reference_learning.py --refresh-exports`
2. Ergebnisse in `server/knowledge/reference_learning/reference_drawings_index.json` pruefen.
3. Visuelle Gegenpruefung optional mit `--render-contact-sheets` in `server/_debug/reference_learning`.
4. Auffaellige Teile gezielt fuer Planner/Builder/Critic-Iterationen priorisieren.

## Grenzen
- Die PDF-Metriken messen Layout, Textdichte, Blattnutzung und grobe Struktur.
- Sie ersetzen keine echte Konstrukteursbewertung von Bezugslogik, falschen Massen oder Normdetails.
- Die Musterzeichnungen sind deshalb Lerninhalt und Referenzbasis, aber kein alleiniger Freigabeautomatismus.
