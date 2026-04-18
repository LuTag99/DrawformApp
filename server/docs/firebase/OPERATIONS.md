# Firebase Operations, Tests & Costs

Stand: 2026-04-17
Status: aktiv

Dieses Dokument buendelt die Integrations-, Test- und Betriebsgrenzen fuer
die Firebase-Anbindung (P5 aus `server/docs/todos/TODO.md`).

## Integration Frontend / Backend

### Firestore-Zugriff Frontend

- Nutzerprofil (`users/{uid}`): Lese-/Schreibzugriff ueber einen
  dedizierten `userProfileService` (noch anzulegen unter
  `src/services/userProfileService.ts`). Der Service kapselt
  `getFirestore` plus `doc(...).get/set/update` und ist die einzige
  clientseitige Quelle fuer Profil-Mutationen.
- Export-Metadaten (`users/{uid}/exports/{exportId}`): nur lesender
  Zugriff, Listenansicht im Profil- oder Export-Verlauf. Kein Client
  darf exports schreiben (Rules verbieten es).

### Firestore-Zugriff Backend

- Alle KB-Schreiboperationen und alle Export-Statusupdates laufen
  ueber das Firebase Admin SDK in `server/` mit einem Service Account.
- `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_PATH` oder
  `DRAWFORM_FIREBASE_SERVICE_ACCOUNT_JSON` aus `.env.example` sind die
  zwei unterstuetzten Quellen; Prioritaet liegt beim direkten JSON,
  weil es Docker-freundlich ist.
- Der Admin SDK Client wird als Modul-Singleton in einem neuen Modul
  `server/firebase_admin.py` initialisiert; die KB-Sync-Pipeline aus
  [KB_SYNC_AGENT.md](KB_SYNC_AGENT.md) und die Export-Statuslogik
  benutzen denselben Client.

### Storage-Zugriff

- Frontend schreibt nur unter `users/{uid}/...`.
- KB-Uploads unter `knowledge-base/**` laufen ausschliesslich ueber
  das Admin SDK.

## Testabdeckung

Die Pruefkommandos aus `server/docs/todos/TODO.md` werden auf
bestehende bzw. neu anzulegende Testmodule gemappt:

| Kommando                                                                            | Zielmodul                                 | Zweck                                         |
| ----------------------------------------------------------------------------------- | ----------------------------------------- | --------------------------------------------- |
| `npm run lint`                                                                      | Frontend                                  | Codequalitaet, Auth/Services                  |
| `npm run build`                                                                     | Frontend                                  | Typ- und Build-Integritaet                    |
| `python -m pytest server/test_api_endpoints.py -q`                                  | bestehend                                 | API-Glue inkl. Auth-Shim                      |
| `python -m pytest server/tests/test_kb_sync.py -q`                                  | `server/tests/test_kb_sync.py` (neu)      | Delta-/Hash-/Scope-Logik gegen Fake-Firestore |
| `python -m pytest server/tests/test_kb_flagging_agent.py -q`                        | `server/tests/test_kb_flagging_agent.py`  | Hybrid-Tagging inkl. AI-Fallback              |
| `firebase emulators:exec --only firestore,storage "npm run build"`                  | lokal                                     | Smoke-Test gegen Emulator-Rules               |

### Firestore-Regeltests

- Werkzeug: `@firebase/rules-unit-testing` gegen die Emulatoren.
- Zielgruppen:
  - Nutzer liest nur eigenes Profil (pass)
  - Nutzer liest fremdes Profil (fail)
  - Nutzer schreibt eigenes Profil mit passender `uid` (pass)
  - Nutzer schreibt eigenes Profil mit manipulierter `uid` (fail)
  - Nutzer liest eigene Exporte (pass)
  - Nutzer schreibt eigene Exporte clientseitig (fail)
  - Nicht-eingeloggt liest `kb_documents` (fail)
  - Eingeloggt liest aktives, `authenticated`-sichtbares
    `kb_documents`-Dokument (pass)
  - Eingeloggt liest inaktives oder `internal`-sichtbares Dokument (fail)
  - Jeder Client schreibt `kb_sync_runs` (fail)

### Storage-Regeltests

- Werkzeug: ebenso `@firebase/rules-unit-testing` oder
  `gcloud storage`-basiertes Emulator-Setup.
- Zielgruppen:
  - Nutzer laedt Avatar unter eigenem `uid`-Pfad (pass)
  - Nutzer laedt Avatar unter fremdem `uid`-Pfad (fail)
  - Eingeloggt liest `knowledge-base/current/...` (pass)
  - Eingeloggt schreibt `knowledge-base/current/...` (fail)

### KB-Sync-Tests (`test_kb_sync.py`)

- Szenario NEUE Datei: Upload + Firestore-Dokument + Chunks werden
  angelegt; `kb_sync_runs` erhaelt `status="succeeded"`.
- Szenario UNVERAENDERT: nichts wird neu geschrieben, `documentsUpserted=0`.
- Szenario GEAENDERT (gleicher Pfad, neuer Inhalt): Upload + Upsert;
  alte Chunks ueber dem neuen `ordinal`-Maximum werden verworfen.
- Szenario OBSOLETE: Datei nicht mehr in Scope -> `isActive=false`, kein
  Hard-Delete.

### Flagging-Agent-Tests (`test_kb_flagging_agent.py`)

- `baseTags` sind stabil ueber mehrere Laeufe auf gleichem Input.
- Ohne AI-Konfiguration endet der Agent mit `aiFlags.status="skipped"`
  und der Lauf bleibt erfolgreich.
- Mit AI-Konfiguration erzeugt der Agent erwartete Feldstrukturen,
  ohne die `baseTags` zu ueberschreiben.

## Secret- und Betriebsdisziplin

- Service-Account-Dateien gehoeren niemals ins Repo. `.gitignore`
  schliesst bereits `service-account*.json` und
  `firebase-service-account*.json` aus.
- Produktionssecrets bleiben ausserhalb des Projektordners und werden
  nur ueber sichere Umgebungsvariablen oder Secret Manager injiziert.
- Service Accounts erhalten nur die noetigen IAM-Rollen:
  - Cloud Firestore User
  - Storage Object Admin (nur auf den konkreten Bucket)
  - keine `roles/owner`-Zuweisungen

## Kosten-Hauptlinien

### Kostenbewusste Entscheidungen

- V1-KB-Scope bleibt bei strukturierten JSON/MD-Dateien -> geringe
  Storage- und Downloadkosten.
- Repo als Source of Truth -> keine unnoetigen Firestore-Writes.
- Delta-Sync ueber SHA-256 -> keine teure Vollreindizierung.
- Hybrid-Tagging -> AI-Calls nur auf NEU/GEAENDERT; deterministische
  `baseTags` tragen die Last.
- Retrieval laeuft ueber Chunks + `baseTags`; teure Freitextsuche wird
  bewusst verschoben.

### Hauptkostentreiber

- Viele Firestore-Reads bei spaeterer Suche.
- Grosse KB-Dateien oder PDF-Mirror im Storage.
- AI-Flagging pro Datei ohne Delta-Pruefung.

### Verbindliche Kostenhygiene

- Kein Vollsync beim Backend-Start.
- Keine clientseitigen KB-Writes.
- Budget Alerts in Firebase/Google Cloud aktivieren:
  - monatliches Hard-Budget fuer das Drawform-Projekt (z. B. 25 EUR
    fuer V1) mit 50/90/100-Prozent-Trigger.
  - Alerts gehen an die technische Projekt-E-Mail.
- KB-Scope fuer V1 klein halten; jede Erweiterung braucht einen
  expliziten Scope-Change in `server/docs/firebase/KB_SYNC_AGENT.md`.

## Nicht akzeptabel

- Firestore-Collections ohne klaren Feldvertrag.
- KB-Schreibzugriffe direkt aus dem Client.
- Vollreindex bei jedem Backend-Start ohne Hash-/Delta-Pruefung.
- Service-Account-Dateien im Repo.
- Neue Firebase-Logik ohne Emulator- oder Regelteststrategie.
- Vermischung instabiler Analyzer-/Reconstruct-Migrationen mit dem
  KB-/Rules-Grundaufbau.
