# Firebase Rules

Stand: 2026-04-17
Status: aktiv

Dieses Dokument beschreibt die verbindliche Zugriffslogik fuer Firestore und
Storage. Die ausfuehrbaren Dateien sind:

- `firebase.json` - Projektkonfiguration (Rules, Emulatoren, Indexes)
- `firestore.rules` - Firestore Security Rules
- `storage.rules` - Storage Security Rules
- `firestore.indexes.json` - Firestore-Indexe

## Grundprinzipien

1. Keine anonymen Zugriffe auf Firestore oder Storage.
2. Nutzer darf ausschliesslich seinen eigenen Namensraum lesen und schreiben.
3. KB-Daten sind fuer Clients lesbar (Authenticated), aber niemals
   schreibbar; jeder Schreibzugriff laeuft serverseitig ueber das Admin SDK.
4. Technische Metadaten (`kb_sync_runs`) sind fuer Clients unsichtbar.

## Firestore-Regeln je Pfad

### `users/{uid}`

- Read/Create/Update: nur wenn `request.auth.uid == uid` UND
  `request.resource.data.uid == uid` (verhindert Spoofing der eigenen UID).
- Delete: verboten. Deaktivierung laeuft ueber das Feld `isActive = false`.

### `users/{uid}/exports/{exportId}`

- Read: nur fuer den Besitzer.
- Write: clientseitig verboten. Schreiben passiert serverseitig:
  - beim Auftragseingang (`status="queued"`),
  - bei Zustandsuebergaengen (`"running" -> "succeeded"`/`"failed"`),
  - beim Setzen von `storageOutputPath` / `error`.

### `users/{uid}/analyzer/{jobId}` und `users/{uid}/reconstruct/{jobId}`

- Read: nur fuer den Besitzer.
- Write: verboten. Diese Pfade sind reserviert, aber nicht aktiv genutzt.
- Ein produktiver Vertrag folgt in einer eigenen TODO, sobald Analyzer und
  Reconstruct stabil genug sind.

### Gemeinsame Helper-Funktion `kbDocReadable(docId)`

Die KB-Sichtbarkeit lebt in genau einer Rule-Funktion und wird vom
Dokument *und* den Chunks benutzt. Die Funktion liest das Eltern-Dokument
via `get(...)` und gibt `true` zurueck, wenn alle Bedingungen gelten:

- `isActive == true`
- `visibility == 'authenticated'`
- `reviewStatus != 'rejected'`

Damit koennen Chunk-Reads nicht mehr weiter reichen als Dokument-Reads.

### `kb_documents/{docId}`

- Read: nur fuer angemeldete Nutzer UND `kbDocReadable(docId)`.
- Write: clientseitig verboten. Schreiben nur serverseitig ueber den
  KB-Sync-Agenten (siehe [KB_SYNC_AGENT.md](KB_SYNC_AGENT.md)).

### `kb_documents/{docId}/chunks/{chunkId}`

- Read: nur fuer angemeldete Nutzer UND `kbDocReadable(docId)`, d. h.
  technisch an das Eltern-Dokument gebunden. Chunks sind niemals
  eigenstaendig lesbar, auch nicht per direkter Document-ID.
- Write: clientseitig verboten.

### Kosten-/Read-Hinweis

Jeder Chunk-Read fuehrt zu einem zusaetzlichen Firestore-Read auf das
Eltern-Dokument (via `get(...)`). Das ist der akzeptierte Preis fuer eine
konsistente Sichtbarkeit. Fuer haeufige Retrieval-Szenarien wird ein
serverseitiger Query empfohlen, der den Parent-Check nur einmal pro
Dokument durchfuehrt.

### `kb_sync_runs/{runId}`

- Read: clientseitig verboten.
- Write: clientseitig verboten.
- Zugriff erfolgt ausschliesslich ueber das Admin SDK.

### Catch-All

Alles andere ist implizit verboten (`allow read, write: if false`).

## Storage-Regeln je Pfad

### `users/{uid}/**`

- Read/Write: nur wenn `request.auth.uid == uid`.
- Enthaelt `avatar/`, `exports/`, `reconstruct/` im selben Namensraum.

### `knowledge-base/**`

- Read: nur fuer angemeldete Nutzer.
- Write: clientseitig verboten (Admin SDK only).
- Authoritativer Pfad ist `knowledge-base/current/...`; optionale
  Release-Historie unter `knowledge-base/releases/<releaseId>/...`.

### Catch-All

`match /{allPaths=**}` erlaubt standardmaessig keinen Zugriff.

## Emulator und lokale Validierung

`firebase.json` aktiviert die Emulatoren fuer Auth, Firestore und Storage
sowie die Emulator UI auf Port 4000. Eine vollstaendige lokale Validierung
laeuft sinngemaess so ab:

```powershell
firebase emulators:start --only firestore,storage,auth
```

Oder gekoppelt an den Frontend-Build als Smoke-Test:

```powershell
firebase emulators:exec --only firestore,storage "npm run build"
```

Regeltests gegen die Emulatoren werden in einer eigenen Testdatei gefuehrt,
siehe [KB_SYNC_AGENT.md](KB_SYNC_AGENT.md) und [OPERATIONS.md](OPERATIONS.md).

## Bekannte Nicht-Ziele

- Keine Admin-Oberflaeche fuer KB-Review in V1.
- Keine Kollaboration mehrerer Nutzer an einem Export (kein Sharing).
- Keine Public-Links fuer Export-Outputs ueber Firestore-Rules; falls noetig,
  laeuft das ueber signierte URLs aus dem Backend.
