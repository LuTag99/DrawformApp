# Deployment auf Ubuntu Server mit Plesk

Diese Anleitung beschreibt, wie du den neuen Drawform-AI-Frontend-Build auf einem Ubuntu-Server mit Plesk (Apache/Nginx) veröffentlichst.

## 1. Voraussetzungen

- Ubuntu-Server mit Plesk WebPro/WebHost Edition (Apache + optional Nginx Reverse Proxy aktiv).
- Node.js 18+ oder 20+ (nur für den Build-Prozess benötigt, nicht zwingend auf dem Server, wenn du lokal baust).
- SSH- oder SFTP-Zugang bzw. Plesk-Dateimanager.
- Optional: Shell-Zugriff auf dem Server, falls du direkt dort bauen möchtest.

## 2. Build lokal erstellen

```bash
# Im Projektverzeichnis (lokal)
npm ci
npm run build
# Ergebnis liegt unter dist/
```

- Die SPA-Route-Weiterleitung wird über `public/.htaccess` automatisch nach `dist/` kopiert – so funktionieren Deep Links unter Apache.
- Stelle sicher, dass `VITE_OPENAI_API_KEY` vor dem Build gesetzt ist, falls du den Key clientseitig einbetten möchtest (`.env.production` oder direkte Shell-Variable). Ohne Key nutzt die App den Fallback-Text.

## 3. Build paketieren

```bash
zip -r drawform-ai-dist.zip dist
```

Alternativ kannst du den gesamten `dist/`-Ordner via SFTP oder den Plesk-Dateimanager hochladen.

## 4. Deployment in Plesk

1. Melde dich in Plesk an und wähle die gewünschte Domain/Subdomain.
2. Unter **Hosting-Einstellungen** sicherstellen, dass „Hosting-Typ: Website-Hosting“ aktiv ist und der Dokumentenstamm (Document Root) z. B. `httpdocs` lautet.
3. Lade die Inhalte von `dist/` (nicht den Ordner selbst) in diesen Document Root:
   - Variante A: **Dateimanager → Upload** und ZIP-Datei hochladen, anschließend im Zielverzeichnis entpacken.
   - Variante B: Per SFTP/SSH Dateien nach `/var/www/vhosts/<domain>/httpdocs` kopieren.
4. Prüfe, ob die Datei `.htaccess` im Document Root liegt (sie sorgt dafür, dass alle Routen an `index.html` gehen).
5. Optional: Wenn du einen separaten Backend-Endpunkt (`/api/export`) auf demselben Server anbietest, konfiguriere unter **Apache & nginx-Einstellungen** die passenden Proxy-Pfade (z. B. Location `/api` → Node/Python-Service).

## 5. OpenAI-Key & Backend

- Für den produktiven Einsatz solltest du den OpenAI-Schlüssel **nicht** clientseitig ausliefern. Empfohlen: Einen serverseitigen Proxy/Edge Function einrichten, die den Key schützt. Passe anschließend `fetchAiInsight` an, damit die App deinen Proxy anspricht.
- Falls du den Key vorerst clientseitig einbetten musst, setze ihn vor dem Build, z. B.:

  ```bash
  # lokale Shell
  setx VITE_OPENAI_API_KEY "sk-..."
  npm run build
  ```

  Danach die entstandene `dist/`-Version deployen.

## 6. Tests nach dem Upload

- Öffne die Domain im Browser → du solltest die Glas-Oberfläche sehen.
- Navigiere durch `/projects`, `/export`, `/profile`, um zu bestätigen, dass die `.htaccess`-Weiterleitung greift.
- Wenn du `/api/export` auf denselben Server legst, teste einen Export-Request (z. B. mit `sheet=auto`, `sheet=A3` oder `sheet=A2`).
- Ohne Backend zeigt die Export-Seite einen echten Fehlerstatus.

## 7. Updates

1. Lokale Änderungen committen (falls Git).
2. `npm run build`.
3. Dist-Inhalt erneut hochladen (alte Dateien überschreiben).
4. Optional: Mit dem Plesk-Dateimanager überflüssige Dateien löschen, um den Document Root sauber zu halten.

Damit ist die SPA für Plesk/Ubuntu vorbereitet. Die Anleitung kannst du projektspezifisch anpassen (z. B. eigener Deploy-User, automatisiertes FTP-Script).
