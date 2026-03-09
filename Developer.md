# Developer.md

Hauptdokument fuer den aktuellen Entwicklungsstand:
- `DEVELOPER_DOCS.md`

Hinweis:
`DEVELOPER_DOCS.md` ist die gepflegte Uebergabedokumentation (Architektur, aktueller Stand, Tests, Qualitaetsgate, naechste Schritte).

Stand der letzten Uebergabe (Maerz 2026):

**Backend (server/):**
- FreeCAD SheetMetal Addon (V2 Unfolder) integriert — echte Abwicklung fuer Blechteile
- `step_unfold.py` Headless-Skript fuer Subprocess-Unfold
- Feature-Probe: Wanddicken-Messung via antiparallele Flaechenpaare (`measured_thickness_mm`)
- Layoutprofil-Klassifizierung: 4-stufig (Dateiname / Flaechentypen+Dicke-Guard / bend_count / BBox-Ratio)
- Bauteilname-Extraktion aus Dateinamen (beliebige Ziffernpraefixe, Versionssuffix)
- Normkonform: Toleranz `DIN ISO 2768-mK`, Durchmesser U+00D8, kein „LOCHABSTAND"
- K-Faktor-Duplikat beseitigt, Abwicklung mit `complex_geometry`-Guard
- Baseline: 20/20 Tests bestehen, Real: 41/48
- Foto-zu-3D Pipeline: `/api/reconstruct` (Voxel-Carving, STL, STEP)
- DXF-Export: `/api/export-dxf` (Abwicklung als Flachmuster)

**Frontend (src/):**
- Vollstaendiger Rewrite auf React 19 + TypeScript + Vite 7
- Glassmorphism-UI (iOS 26 Glass Look), Desktop-Sidebar + Mobile-Nav
- Auth-Flow (Login, Register, Passwort-Reset) via LocalStorage — Stub fuer echtes Backend
- Dashboard mit AI-Insights (OpenAI `gpt-4.1-mini`) und SVG-Chart
- Bemaessungslabor (`/analyzer`): Upload, Job-Polling via `/api/analyze`, Ergebnisanzeige
- Rekonstruktion (`/reconstruct`): 5-Foto-Upload, Job-Status via `/api/reconstruct`
- Export-Center (`/export`): PDF und DXF via Backend, Preview und Log-Anzeige
- Projektseite (`/projects`): Demo-Daten (Stub)
- Profil (`/profile`): Avatar-URL, Passwortaenderung
