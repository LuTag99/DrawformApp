# Developer.md

Hauptdokument fuer den aktuellen Entwicklungsstand:
- `DEVELOPER_DOCS.md`

Hinweis:
`DEVELOPER_DOCS.md` ist die gepflegte Uebergabedokumentation (Architektur, aktueller Stand, Tests, Qualitaetsgate, naechste Schritte).

Stand der letzten Uebergabe (Feb 2026):
- FreeCAD SheetMetal Addon (V2 Unfolder) integriert — echte Abwicklung fuer Blechteile
- `step_unfold.py` Headless-Skript fuer Subprocess-Unfold
- Feature-Probe: Wanddicken-Messung via antiparallele Flaechenpaare (`measured_thickness_mm`)
- Layoutprofil-Klassifizierung: 3-stufig (Dateiname / Flaechentypen+Dicke-Guard / BBox-Ratio)
- Bauteilname-Extraktion aus Dateinamen (beliebige Ziffernpraefixe, Versionssuffix)
- Normkonform: Toleranz `DIN ISO 2768-mK`, Durchmesser U+00D8, kein „LOCHABSTAND"
- K-Faktor-Duplikat beseitigt, Abwicklung mit `complex_geometry`-Guard
- Baseline: 20/20 Tests bestehen
