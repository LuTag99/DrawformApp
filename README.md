# Drawform AI Workspace (React)

Ein kompletter Rewrite der Drawform-App auf Basis von React, TypeScript und Vite.
Das neue Frontend setzt den iOS 26 Glass Look konsequent um, fühlt sich wie eine KI-Experience an und kann auf demselben Server wie [Drawform-Website](https://github.com/LuTag99/Drawform-Website) ausgeliefert werden.

## Features

- Glasiges, responsives UI mit Desktop-Sidebar & Mobile-Tab-Bar.
- Firebase Auth mit E-Mail/Passwort, Google Login und Passwort-Reset.
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

## Firebase Setup

1. In Firebase eine Web-App registrieren und die `VITE_FIREBASE_*` Werte in `.env.local` eintragen.
2. In `Authentication -> Sign-in method` `Email/Password` und `Google` aktivieren.
3. In `Storage` einen Bucket anlegen.
4. Fuer das Backend einen Service Account erzeugen und `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_PATH`
   (oder `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_JSON`) setzen.
5. Falls noetig `DRAWFORM_FIREBASE_PROJECT_ID` setzen und den Backend-Server neu starten.

### Auth-Modi des Backends

Die geschuetzten Endpunkte (`/api/export`, `/api/analyze`, `/api/reconstruct`,
`/api/ai-insight`) kennen genau zwei Modi:

- **Produktion / Standardentwicklung**: `DRAWFORM_REQUIRE_FIREBASE_AUTH=1`
  (Default). Jeder Aufruf braucht einen `Authorization: Bearer <Firebase ID Token>`-Header;
  das Backend verifiziert den Token via Firebase Admin SDK. Beispiel:

  ```bash
  TOKEN="<Firebase ID Token aus einer angemeldeten Drawform-Session>"
  curl -X POST http://localhost:8000/api/export \
       -H "Authorization: Bearer $TOKEN" \
       -F "file=@bauteil.step" \
       -F "format=pdf"
  ```

- **Lokaler Dev/Test ohne Firebase Auth**: `DRAWFORM_REQUIRE_FIREBASE_AUTH=0`.
  In diesem Modus wird ein fixer Stub-User (`uid=local-dev`,
  `email=dev@drawform.local`, ueber `DRAWFORM_LOCAL_DEV_UID` /
  `DRAWFORM_LOCAL_DEV_EMAIL` ueberschreibbar) angenommen. Es gibt **keinen**
  503-Fehler, sondern alle Endpunkte sind ohne Token aufrufbar:

  ```bash
  DRAWFORM_REQUIRE_FIREBASE_AUTH=0 uvicorn main:app --reload --port 8000
  curl -X POST http://localhost:8000/api/ai-insight \
       -H "Content-Type: application/json" \
       -d '{"statusSummary":"Fast gate ok"}'
  ```

  Dieser Modus ist ausschliesslich fuer lokale Entwicklung und Tests gedacht
  und darf in Produktion **nicht** gesetzt sein.


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
- Aktuelle Test- und Regressionsergebnisse werden nicht fest in dieses README geschrieben
- Die kanonischen Regeln dafuer stehen in `AGENTS.md` und `REPO_SYNC_POLICY.md`
- Live-Status immer ueber `server/README.md`, CI und aktuelle Run-Artefakte pruefen
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
  providers/         # AuthContext auf Firebase Auth
  services/          # AI-Insight-Proxy + Export-API + Analyzer + Reconstruct + Storage Helper
  styles/            # globals.css mit Glass Look Tokens

server/
  main.py            # FastAPI Endpunkte + DSE-Orchestrierung
  freecad/           # FreeCAD-Subprozesse (step_to_pdf, step_feature_probe, step_unfold)
  rules/             # Dimension Strategy Engine + Schema
  knowledge/         # Wissensbasis (knowledge_base.json) + Reference Learning
  tests/             # DSE Unit Tests
  _debug/            # Debug-Artefakte (SVG, PNG, JSON, Agent-Runs)
  _golden/           # Golden Baselines fuer Regression (baseline + real_priority)
  _samples/          # STEP-Samples in Kategorie-Ordnern (Fraesteile, Drehteile, Blechteile, Baugruppen)
  sample_catalog.py  # Sample-Sets (baseline, real, real_priority, all)
  test_views.py      # View-Regression + Quality Checks
  reference_learning_gate.py  # Real-Part Reference Learning Gate
```

### Regressionsmodi

| Sample-Set       | Golden-Quelle                          | Modus    | Fehlende Golden-Eintraege |
|------------------|----------------------------------------|----------|---------------------------|
| `baseline`       | `_golden/views_baseline.json`          | **strict** | FAIL                    |
| `real_priority`  | `_golden/views_real_priority.json`     | **strict** | FAIL                    |
| `real20`         | `_golden/views_real20.json`            | **strict** | FAIL                    |
| `real`           | real_priority-Subset                   | subset   | nur Live-Quality-Checks   |
| `all`            | baseline + real_priority vereint       | subset   | nur Live-Quality-Checks   |

- `strict`: Jedes Sample muss einen Golden-Eintrag haben. Fehlende Eintraege fuehren zu einem Testfehler.
- `subset`: Nur verwaltete Golden-Eintraege werden geprueft. Samples ohne Golden-Eintrag werden durch Live-Quality-Checks validiert — kein Snapshot-Vergleich.
- Mit `--strict` wird strict-Modus fuer jedes Sample-Set erzwungen (fehlende Goldens = FAIL).
- Mit `--golden <path>` wird strict-Modus mit einer expliziten Golden-Datei erzwungen.

## Deployment

```bash
npm run build
# dist/ nach Drawform-Website kopieren oder als eigenes Static Hosting ausliefern
```

Auf klassischen Hosts (Nginx/Apache) reicht es, das `dist/`-Verzeichnis neben die bestehende Website zu legen und via Rewrite auf `index.html` zu routen. Für moderne Deployments (Vercel, Netlify, Cloudflare Pages) einfach das Repo verbinden und `npm run build` als Build Command hinterlegen.

### Plesk/Ubuntu Server

Für klassische Plesk-Server (Apache/Nginx) findest du eine Schritt-für-Schritt-Anleitung unter `deploy/plesk/README.md`.

## Weiterentwicklung

- Auth und Storage laufen über Firebase. Trage dafür die `VITE_FIREBASE_*` Werte im Frontend und den Firebase Service Account im Backend ein.
- Backend-Endpunkte prüfen Firebase ID Tokens und filtern Analyse-/Reconstruct-Jobs auf den angemeldeten Benutzer.
- Export-, Analyzer- und Reconstruct-Uploads werden zusätzlich benutzergebunden in Firebase Storage gespiegelt.
- Für AI-Features lassen sich weitere Panels (Co-Pilot, Generative Assist) leicht über `fetchAiInsight` erweitern.
- Die Export-Seite unterstützt bereits Drag & Drop – bei Bedarf Dateianalyse/Progress-Bar ergänzen.
- Fuer Entwickler-Dokumentation siehe `Developer.md`, `DEVELOPER_DOCS.md` und `REPO_SYNC_POLICY.md`.
