# DIN/ISO Baseline fuer technische Fertigungszeichnungen

Stand: 2026-02-15
Quelle: offizielle Metadaten von ISO, DIN Media und Austrian Standards.
Hinweis: Normtexte sind urheberrechtlich geschuetzt und teils kostenpflichtig. Dieses Dokument enthaelt nur oeffentlich zugaengliche Status- und Strukturinfos.

## Ziel

Diese Baseline definiert, welche Normen in Drawform als Standard fuer technische Zeichnungen (Deutschland/Oesterreich) gelten sollen. Sie dient als feste Grundlage fuer spaetere Code-Implementierung.

## 1) Normenkern (international)

| Bereich | Primarnorm | Aktueller Stand (oeffentliche Quelle) | Relevanz fuer Code |
| --- | --- | --- | --- |
| Allgemeine Darstellungsregeln | ISO 128-1 | 2020 | Grundregeln fuer Ansichtsdarstellung |
| Linienarten und Linienstaerken | ISO 128-2 | 2022 | Sichtbar/verdeckt/Mittellinie/Schraffur |
| Bemaszung (allgemein) | ISO 129-1 | 2018 + Amd.1:2020 | Pfeile, Hilfslinien, Bemaszungslogik |
| Projektion (Orthogonal) | ISO 5456-2 | 1996 (confirmed 2025) | 1. Winkel fuer DACH als Default |
| Massstaebe | ISO 5455 | 1979 (confirmed 2020) | 1:1, 1:2, 2:1 usw. |
| Zeichenblatt/Layout | ISO 5457 | 1999 + Amd.1:2010 | Blattformat A3/A4, Zeichnungsfeld |
| Schriftfeld/Metadaten | ISO 7200 | 2004 (confirmed 2025) | Titelblock-Felder im SVG/PDF |
| Schrift | ISO 3098-2 | 2000 | Zeichnungsschrift fuer Lesbarkeit |

## 2) GPS und Toleranzen

| Bereich | Norm | Aktueller Stand | Relevanz fuer Code |
| --- | --- | --- | --- |
| GPS Grundprinzip | ISO 8015 | 2011 | Unabhaengigkeitsprinzip als Basiskonzept |
| Geometrische Toleranzen | ISO 1101 | 2017 | Form-/Lage-/Richtungstoleranzen |
| Bezuge/Datums | ISO 5459 | 2024 | Bezugssysteme fuer GD&T |
| Maximum-/Minimum-Material | ISO 2692 | 2021 | Konditionsmodifikatoren |
| Profilangaben | ISO 1660 | 2017 | Profiltoleranzen |
| Groessenmasz (lineare Groesse) | ISO 14405-1 | 2025 | Eindeutige Groessenangaben |
| Kantenangaben | ISO 13715 | 2017 | Kanten undef./def. |
| Oberflaechenangaben | ISO 21920-1 | 2021 | ersetzt ISO 1302 fuer moderne Spezifikation |

## 3) Passungen, Gewinde, Allgemeintoleranzen

| Bereich | Norm | Aktueller Stand | Relevanz fuer Code |
| --- | --- | --- | --- |
| ISO-Passungen (System) | ISO 286-1 | 2010 | Basis fuer H7/g6 etc. |
| ISO-Passungen (Tabellen) | ISO 286-2 | 2010 | Numerische Grenzmasse |
| Gewindeprofil M | ISO 68-1 | 2023 | Profilgrundlage metrisches Gewinde |
| Gewindereihen M | ISO 261 | 1998 (confirmed 2024) | M-Nenngewinde-Reihen |
| Gewindetoleranzen | ISO 965-1 | 2013 (replacement under publication) | Kennzeichnung z.B. 6H/6g |
| Gewindedarstellung Zeichnung | ISO 6410-1 | 1993 | Symbolische Gewindedarstellung |
| Allgemeintoleranzen linear/winklig | ISO 2768-1 | 1989 (active, replacement in Arbeit) | m/f/c/v Klassen |
| Allgemeintoleranzen geometrisch | ISO 22081 | 2021 | Nachfolger fuer den 2768-2 Bereich |

## 4) Nationale Uebernahme (DE/AT)

In Deutschland und Oesterreich werden ISO-Normen ueblicherweise als nationale Uebernahmen gefuehrt:

- Deutschland: `DIN EN ISO ...` oder `DIN ISO ...`
- Oesterreich: `OENORM EN ISO ...` oder `OENORM ISO ...`

Verifizierte Beispiele (Stand 2026-02-15):

- DIN EN ISO 129-1:2022-02
- DIN EN ISO 128-2:2023-06
- DIN EN ISO 5457:2017-10
- DIN EN ISO 7200:2004-05
- DIN ISO 5456-2:1998-04
- OENORM EN ISO 129-1:2022-02-15
- OENORM EN ISO 128-2:2023-05-15
- OENORM EN ISO 5457:2011-03-01
- OENORM EN ISO 7200:2004-05-01
- OENORM EN ISO 1101:2017-08-01

## 5) Verbindliche Drawform-Defaults (ab sofort)

1. Projektion: 1. Winkel (First Angle) als Default fuer DE/AT.
2. Einheit: `mm` im Schriftfeld/Metadaten; Masszahl in Bemaszung ohne Einheiten-Suffix.
3. Massstab: nur aus ISO-5455-Werten.
4. Schriftfeld: ISO-7200 Felder (Benennung, Zeichnungsnr., Revision, Datum, Massstab, Blatt).
5. Linienlogik: sichtbare Kanten/verdeckte Kanten/Mittellinien nach ISO-128-2 differenzieren.
6. Toleranzblock: allgemeine Toleranzklasse explizit im Zeichnungskopf (z.B. DIN ISO 2768-mK oder ISO 22081-basiert).
7. Gewinde: Darstellung und Beschriftung nach ISO 6410-1 + ISO 965-1 (z.B. `M12-6H`).
8. Oberflaechenangaben: perspektivisch auf ISO 21920-1 ausrichten (anstatt alter ISO-1302-Only-Logik).

## 6) Umsetzungsplan fuer Code

Phase A (schnell, stabil):
- Normen-Metadaten zentralisieren (`standard`, `projection`, `general_tolerance`, `surface_standard`, `thread_standard`).
- Validierungsregeln fuer erlaubte Massstaebe, Projektion und Toleranz-Strings einfuehren.
- Ausgabeformat fuer Zahlen lokalisierbar halten (DE/AT standardmaessig Dezimalkomma).

Phase B (Zeichnungsqualitaet):
- Linienstile pro Semantik im SVG/PDF trennen.
- Mittellinien fuer Bohrungen und Symmetrieachsen automatisieren.
- Gewinde-Callout aus Feature-Erkennung in Hauptansichten platzieren.

Phase C (GPS-Faehigkeit):
- Datenmodell fuer GD&T und Bezuege erweitern.
- Toleranzrahmen (Feature Control Frame) rendern.
- Regelwerk fuer 22081/2768 migrationsfaehig machen.

## 7) Quellen (offiziell)

ISO:
- https://www.iso.org/standard/64741.html (ISO 129-1)
- https://www.iso.org/standard/81804.html (ISO 128-2)
- https://www.iso.org/standard/82785.html (ISO 128-1)
- https://www.iso.org/standard/11714.html (ISO 5456-2)
- https://www.iso.org/standard/11321.html (ISO 5455)
- https://www.iso.org/standard/79848.html (ISO 7200)
- https://www.iso.org/standard/79849.html (ISO 5457)
- https://www.iso.org/standard/28674.html (ISO 3098-2)
- https://www.iso.org/standard/61707.html (ISO 1101)
- https://www.iso.org/standard/45419.html (ISO 8015)
- https://www.iso.org/standard/80910.html (ISO 5459)
- https://www.iso.org/standard/75848.html (ISO 2692)
- https://www.iso.org/standard/60789.html (ISO 1660)
- https://www.iso.org/standard/86018.html (ISO 14405-1)
- https://www.iso.org/standard/72302.html (ISO 13715)
- https://www.iso.org/standard/75967.html (ISO 21920-1)
- https://www.iso.org/standard/72801.html (ISO 286-1)
- https://www.iso.org/standard/72802.html (ISO 286-2)
- https://www.iso.org/standard/83638.html (ISO 68-1)
- https://www.iso.org/standard/41456.html (ISO 965-1)
- https://www.iso.org/standard/43298.html (ISO 261)
- https://www.iso.org/standard/19290.html (ISO 6410-1)
- https://www.iso.org/standard/67583.html (ISO 2768-1)
- https://www.iso.org/standard/67093.html (ISO 2768-2, withdrawn)
- https://www.iso.org/standard/75139.html (ISO 22081)

Deutschland (DIN Media):
- https://www.dinmedia.de/de/norm/din-en-iso-129-1/337383224
- https://www.dinmedia.de/de/norm/din-en-iso-128-2/363562904
- https://www.dinmedia.de/de/norm/din-en-iso-5457/274056833
- https://www.dinmedia.de/de/norm/din-en-iso-7200/74388562
- https://www.dinmedia.de/de/norm/din-iso-5456-2/6033147

Oesterreich (Austrian Standards):
- https://shop.austrian-standards.at/action/de/public/details/668492/OENORM_EN_ISO_129-1_2022_02_15
- https://shop.austrian-standards.at/action/de/public/details/788157/OENORM_EN_ISO_128-2_2023_05_15
- https://shop.austrian-standards.at/action/de/public/details/393195/OENORM_EN_ISO_5457_2011_03_01
- https://shop.austrian-standards.at/action/de/public/details/119503/OENORM_EN_ISO_7200_2004_05_01
- https://shop.austrian-standards.at/action/de/public/details/580147/OENORM_EN_ISO_1101_2017_08_01
