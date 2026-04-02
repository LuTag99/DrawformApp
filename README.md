# Drawform AI Workspace (React)

Ein kompletter Rewrite der Drawform-App auf Basis von React, TypeScript und Vite.
Das neue Frontend setzt den iOS 26 Glass Look konsequent um, fühlt sich wie eine KI-Experience an und kann auf demselben Server wie [Drawform-Website](https://github.com/LuTag99/Drawform-Website) ausgeliefert werden.

## Features

- Glasiges, responsives UI mit Desktop-Sidebar & Mobile-Tab-Bar.
- Auth-Flow (Login, Registrierung, Passwort-Reset) ohne Backend – Status bleibt im LocalStorage.
- Dashboard mit AI-Insights (Backend-Proxy) und animiertem Canvas-Chart.
- Projektübersicht, Export-Center inkl. Server-Aufruf `/api/export`, Profilverwaltung mit Avatar + Passwortwechsel.
- Bemaessungslabor mit Backend-Jobflow ueber `/api/analyze` (Status: pending/processing/completed) inkl. CAD-Feature-Probe (Bounding-Box, Bohrung, Biegeradius, Fasen, Langlocher).
- Foto-zu-3D-Rekonstruktion ueber `/api/reconstruct` (5 Ansichtsfotos -> STL -> STEP).
- Komponentenbibliothek für Glass Cards, Gradient Buttons, Chips usw.

## Tech-Stack

- React 19, React Router 7, TypeScript.
- Vite 7 als Dev- und Build-Tool.
- Framer Motion für subtile Animationen.
- clsx + Custom CSS (glassmorphism + iOS Typographie).

## Schnellstart

## frontend:
```bash
npm install
npm run dev
```
## Backend
cd C:\Projects\DrawformApp\server
.venv\Scripts\Activate.ps1
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000


## Lokales Backend (STEP -> PDF)

Fuer den MVP-Export (STEP -> PDF mit ISO7200-Schriftkopf, `sheet=auto|A3|A2`) gibt es einen lokalen FastAPI-Service.
Details und Setup findest du unter `server/README.md`.

| Script           | Zweck                               |
| ---------------- | ----------------------------------- |
| `npm run dev`    | Vite-Dev-Server auf `5173`          |
| `npm run build`  | Type-Check + Production Build (`dist/`) |
| `npm run preview`| Vorschau des gebauten Bundles       |
| `npm run lint`   | ESLint über das Repo                |

## Backend-Capabilities

Der FastAPI-Service (`server/main.py`) bietet:

- **PDF-Export**: STEP -> Normkonforme 2D-Fertigungszeichnung (DIN EN ISO, First-Angle)
- **DXF-Export**: Blech-Abwicklung als DXF
- **Feature-Analyse**: Geometrie-Erkennung (Bohrungen, Gewinde, Biegeradien, Fasen, Langlocher)
- **Dimension Strategy Engine (DSE)**: Regelbasierte Bemaessungsplanung mit KB-gesteuertem Closed-Loop-Learning
- **Normkonforme Annotationen**: GD&T (ISO 1101), Schnittansichten (ISO 128-40), Oberflaechenangaben (ISO 1302), Schweisssymbole (ISO 2553), Diagonale Massfuehrung (ISO 129-1)
- **Foto-Rekonstruktion**: 5 Ansichtsfotos -> Voxel-Carving -> STL -> STEP
- **AI-Insights**: Backend-Proxy fuer AI-gestuetzte Analyse
- **Abwicklung-Toggle**: Checkbox im Export-Center steuert ob Flat-Pattern auf dem Blatt erscheint

### Zeichnungsqualitaet

- ISO 7200 Schriftfeld mit Masse, Material, Oberflaechenangabe, Skalenlabel (ISO 5455)
- DIN EN ISO First-Angle Projektion
- 20/20 Baseline-Regression (Golden Baseline 2026-03-31), **64/64 DSE Unit Tests**
- 111 Sample-Parts (20 Baseline, 91 Real)
- Wissensbasis v0.2.1: 21 ISO/DIN-Quellen, 50 Regeln (inkl. GD&T, K-Faktor, Werkstoff, Schweissnaht)
- Closed-Loop KB-Learning: Critic-Feedback wird automatisch als KB-Regelvorschlag strukturiert

## AI-Insights

- `src/services/aiService.ts` ruft den Backend-Proxy `POST /api/ai-insight` auf.
- API-Keys liegen ausschliesslich serverseitig — kein Key im Browser.
- Ist das Backend nicht erreichbar oder der Endpunkt nicht implementiert, faellt die App automatisch auf kuratierte Insights zurueck.

## Export-Service & gemeinsamer Server

- `src/services/exportService.ts` erwartet einen Endpoint `POST /api/export` auf **derselben Domain** wie die Website.
- Lokal ist ein laufendes Backend unter `/api/export` erforderlich; ohne Backend zeigt die Seite einen Fehlerstatus.
- Für eine gemeinsame Auslieferung mit [Drawform-Website](https://github.com/LuTag99/Drawform-Website):
  1. `npm run build`
  2. Den Inhalt aus `dist/` in das Webserver-Verzeichnis der bestehenden Seite kopieren (z. B. als Unterordner `/ai`).
  3. Reverse-Proxy/Rewrite so konfigurieren, dass `/api/export` an euren Python-Service weitergeleitet wird.

## Projektstruktur

```
src/
  components/        # Glas-UI Bausteine (Buttons, Header, Cards)
  layouts/           # Auth Layout + App Shell (Sidebar, Mobile Nav)
  pages/             # Auth, Dashboard, Projekte, Export, Profil, Reconstruct
  providers/         # AuthContext (LocalStorage)
  services/          # AI-Insight-Proxy + Export-API + Analyzer + Reconstruct
  styles/            # globals.css mit Glass Look Tokens

server/
  main.py            # FastAPI Endpunkte + DSE-Orchestrierung
  freecad/           # FreeCAD-Subprozesse (step_to_pdf, step_feature_probe, step_unfold)
  rules/             # Dimension Strategy Engine + Schema
  knowledge/         # Wissensbasis (knowledge_base.json)
  tests/             # DSE Unit Tests
  _debug/            # Debug-Artefakte (SVG, PNG, JSON, Agent-Runs)
  _golden/           # Golden Baseline fuer Regression
  sample_catalog.py  # Sample-Sets (baseline, real, all)
  test_views.py      # View-Regression + Quality Checks
```

## Deployment

```bash
npm run build
# dist/ nach Drawform-Website kopieren oder als eigenes Static Hosting ausliefern
```

Auf klassischen Hosts (Nginx/Apache) reicht es, das `dist/`-Verzeichnis neben die bestehende Website zu legen und via Rewrite auf `index.html` zu routen. Für moderne Deployments (Vercel, Netlify, Cloudflare Pages) einfach das Repo verbinden und `npm run build` als Build Command hinterlegen.

### Plesk/Ubuntu Server

Für klassische Plesk-Server (Apache/Nginx) findest du eine Schritt-für-Schritt-Anleitung unter `deploy/plesk/README.md`.

## Weiterentwicklung

- Die Authentifizierung ist absichtlich lokal gehalten. Hänge hier dein bestehendes Backend an (`AuthProvider` austauschen).
- Für AI-Features lassen sich weitere Panels (Co-Pilot, Generative Assist) leicht über `fetchAiInsight` erweitern.
- Die Export-Seite unterstützt bereits Drag & Drop – bei Bedarf Dateianalyse/Progress-Bar ergänzen.
- Fuer Entwickler-Dokumentation siehe `Developer.md` und `DEVELOPER_DOCS.md`.
