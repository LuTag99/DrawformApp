# Drawform AI Workspace (React)

Ein kompletter Rewrite der Drawform-App auf Basis von React, TypeScript und Vite.  
Das neue Frontend setzt den iOS 26 Glass Look konsequent um, fühlt sich wie eine KI‑Experience an und kann auf demselben Server wie [Drawform-Website](https://github.com/LuTag99/Drawform-Website) ausgeliefert werden.

## Features

- Glasiges, responsives UI mit Desktop-Sidebar & Mobile-Tab-Bar.
- Auth-Flow (Login, Registrierung, Passwort-Reset) ohne Backend – Status bleibt im LocalStorage.
- Dashboard mit AI‑Insights (OpenAI) und animiertem Canvas-Chart.
- Projektübersicht, Export-Center inkl. Server-Aufruf `/api/export`, Profilverwaltung mit Avatar + Passwortwechsel.
- Bemaessungslabor mit Backend-Jobflow ueber `/api/analyze` (Status: pending/processing/completed) inkl. CAD-Feature-Probe (Bounding-Box, Bohrung, Biegeradius).
- Komponentenbibliothek für Glass Cards, Gradient Buttons, Chips usw.

## Tech-Stack

- React 19, React Router 7, TypeScript.
- Vite 7 als Dev- und Build-Tool.
- Framer Motion für subtile Animationen.
- clsx + Custom CSS (glassmorphism + iOS Typographie).

## Schnellstart

```bash
npm install
cp .env.example .env.local   # OpenAI Key eintragen
npm run dev
```

## Lokales Backend (STEP -> PDF)

Fuer den MVP-Export (STEP -> PDF mit ISO7200-Schriftkopf, `sheet=auto|A3|A2`) gibt es einen lokalen FastAPI-Service.
Details und Setup findest du unter `server/README.md`.

Optional kannst du das Backend auch per Docker starten (siehe `server/README.md`).

| Script           | Zweck                               |
| ---------------- | ----------------------------------- |
| `npm run dev`    | Vite-Dev-Server auf `5173`          |
| `npm run build`  | Type-Check + Production Build (`dist/`) |
| `npm run preview`| Vorschau des gebauten Bundles       |
| `npm run lint`   | ESLint über das Repo                |

## OpenAI-Anbindung

- Leg deinen Key in `.env.local` als `VITE_OPENAI_API_KEY=sk-...` ab.  
- Der Key wird **nie** ins Repo eingecheckt (`.env` ist ignoriert).  
- `src/services/aiService.ts` ruft `https://api.openai.com/v1/chat/completions` (Modell `gpt-4.1-mini`).  
- Fehlt der Key oder schlägt der Call fehl, fällt die App auf kuratierte Insights zurück.

> **Sicherheitstipp:** Hinterlege den Key vorzugsweise serverseitig (Proxy oder Edge Function), damit er beim Deployment nicht im Browser landet.

## Export-Service & gemeinsamer Server

- `src/services/exportService.ts` erwartet einen Endpoint `POST /api/export` auf **derselben Domain** wie die Website.  
- Lokal ist ein laufendes Backend unter `/api/export` erforderlich; ohne Backend zeigt die Seite einen Fehlerstatus.  
- Für eine gemeinsame Auslieferung mit [Drawform-Website](https://github.com/LuTag99/Drawform-Website):
  1. `npm run build`
  2. Den Inhalt aus `dist/` in das Webserver-Verzeichnis der bestehenden Seite kopieren (z. B. als Unterordner `/ai`).
  3. Reverse-Proxy/Rewrite so konfigurieren, dass `/api/export` an euren Python‑/Node‑Service weitergeleitet wird.

## Projektstruktur

```
src/
  components/        # Glas-UI Bausteine (Buttons, Header, Cards)
  layouts/           # Auth Layout + App Shell (Sidebar, Mobile Nav)
  pages/             # Auth, Dashboard, Projekte, Export, Profil
  providers/         # AuthContext (LocalStorage)
  services/          # OpenAI-Client + Export-API Stub
  styles/            # globals.css mit Glass Look Tokens
```

## Deployment

```bash
npm run build
# dist/ nach Drawform-Website kopieren oder als eigenes Static Hosting ausliefern
```

Auf klassischen Hosts (Nginx/Apache) reicht es, das `dist/`-Verzeichnis neben die bestehende Website zu legen und via Rewrite auf `index.html` zu routen. Für moderne Deployments (Vercel, Netlify, Cloudflare Pages) einfach das Repo verbinden und `npm run build` als Build Command hinterlegen.

### Plesk/Ubuntu Server

Für klassische Plesk-Server (Apache/Nginx) findest du eine Schritt-für-Schritt-Anleitung unter `deploy/plesk/README.md`. Darin: Build erstellen, ZIP hochladen, `.htaccess` für SPA-Routing und Proxy-Hinweise für `/api/export`.

## Weiterentwicklung

- Die Authentifizierung ist absichtlich lokal gehalten. Hänge hier dein bestehendes Backend an (`AuthProvider` austauschen).  
- Für AI-Features lassen sich weitere Panels (Co-Pilot, Generative Assist) leicht über `fetchAiInsight` erweitern.  
- Die Export-Seite unterstützt bereits Drag & Drop – bei Bedarf Dateianalyse/Progress-Bar ergänzen.

Viel Spaß mit dem neuen Glass Look! ✨
