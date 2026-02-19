# Developer.md

Hauptdokument fuer den aktuellen Entwicklungsstand:
- `DEVELOPER_DOCS.md`

Hinweis:
`DEVELOPER_DOCS.md` ist die gepflegte Uebergabedokumentation (Architektur, aktueller Stand, Tests, Qualitaetsgate, naechste Schritte).

Stand der letzten Uebergabe:
- Sample-Sets `baseline|real|all` inkl. Deduplizierung (`server/sample_catalog.py`)
- Auto-Sheet `auto|A3|A2` in Export-Metadaten und Renderer
- Neutralisierte Templates ohne SPIE-Branding (`server/templates/iso7200_a3_landscape.svg`, `server/templates/iso7200_a2_landscape.svg`)
- Lokaler Real-Part-Benchmark (`server/benchmark_real_parts.py`)
