# Firestore Data Model

Stand: 2026-04-17
Status: aktiv

Dieses Dokument legt die Firestore-Collections, Feldvertraege und
Invarianten fuer Drawform fest. Aenderungen erfolgen nur ueber einen
neuen Stand + Versionsvermerk; es gibt keinen impliziten Feldvertrag.

## Uebersicht

```
users/{uid}
users/{uid}/exports/{exportId}

kb_documents/{docId}
kb_documents/{docId}/chunks/{chunkId}

kb_sync_runs/{runId}
```

- `users/**` ist nutzergebunden und strikt isoliert.
- `kb_documents/**` ist global lesbar fuer angemeldete Nutzer,
  clientseitig nicht schreibbar.
- `kb_sync_runs/**` ist ausschliesslich serverseitig sichtbar (Admin SDK).

## Collection: users/{uid}

Ein Dokument pro Firebase Auth User. Die Document ID ist identisch zur
Firebase-Auth-UID.

### Pflichtfelder

| Feld             | Typ                   | Beschreibung                                                        |
| ---------------- | --------------------- | ------------------------------------------------------------------- |
| `uid`            | string                | Auth-UID; muss mit Document ID identisch sein                       |
| `email`          | string                | Primaere E-Mail aus Firebase Auth                                   |
| `displayName`    | string                | Anzeigename; leerer String erlaubt, `null` nicht                    |
| `avatarUrl`      | string                | Storage-URL aus `users/{uid}/avatar/...`; leerer String erlaubt     |
| `providers`      | string[]              | z. B. `["password"]`, `["google.com"]`, Kombinationen erlaubt        |
| `highlights`     | string[]              | UI-Merker aus der Profilseite, z. B. Schnellzugriffe                |
| `createdAt`      | timestamp             | Erstellzeit des Profils                                             |
| `lastLoginAt`    | timestamp             | Letzte erfolgreiche Anmeldung                                       |
| `profileVersion` | number                | Integer, inkrementiert bei Vertragsaenderungen des Profildokuments  |
| `isActive`       | boolean               | `false` markiert deaktivierte Accounts ohne Hard-Delete             |

### Invarianten

- `uid` darf nach dem ersten Schreiben nie geaendert werden.
- `email` ist fuer Suche/Matching gedacht; die Source of Truth bleibt Firebase Auth.
- `providers` enthaelt nur bekannte Provider-IDs aus `src/providers/authTypes.ts`.
- `profileVersion` beginnt bei 1 und wird bei inkompatiblen Feldaenderungen
  zentral erhoeht; Clients unter der Version werden zu einem Refresh gezwungen.

## Collection: users/{uid}/exports/{exportId}

Ein Dokument pro Export-Auftrag des Nutzers. Die Document ID ist identisch
mit `exportId` und wird serverseitig als ULID/UUID vergeben.

### Pflichtfelder

| Feld                | Typ       | Beschreibung                                                           |
| ------------------- | --------- | ---------------------------------------------------------------------- |
| `exportId`          | string    | ULID/UUID; identisch zur Document ID                                   |
| `createdAt`         | timestamp | Zeit der Auftragserzeugung                                             |
| `sourceFileName`    | string    | Originaler Upload-Dateiname (z. B. `bauteil.step`)                     |
| `outputType`        | string    | `"pdf"` oder `"dxf"`; erweiterbar, aber pro Eintrag fix                |
| `status`            | string    | `"queued" \| "running" \| "succeeded" \| "failed"`                     |
| `storageInputPath`  | string    | `users/{uid}/exports/{exportId}/source/<name>` oder Ankerpfad          |
| `storageOutputPath` | string    | Pfad zum erzeugten Artefakt in Storage; leerer String bis Erfolg       |
| `drawingNo`         | string    | Zeichnungsnummer aus der UI-Eingabe                                    |
| `revision`          | string    | Revisionsstand                                                         |
| `sheet`             | string    | Blattangabe (z. B. `"1/1"`)                                            |
| `standard`          | string    | Zeichennorm (z. B. `"DIN EN ISO"`)                                     |
| `projection`        | string    | `"first-angle"` oder `"third-angle"`                                   |
| `detailLevel`       | number    | 1-3 gemaess DSE-Definition                                             |
| `error`             | string    | Leerer String bis Fehler; bei `status="failed"` menschlich lesbar      |

### Invarianten

- `exportId` stimmt mit Document ID und Storage-Pfad-Segment ueberein.
- `status` darf nicht von `"succeeded"` oder `"failed"` zurueckfallen.
- `storageOutputPath` ist bei `status="succeeded"` nicht leer.
- `error` ist bei `status="failed"` nicht leer.
- Analyzer- und Reconstruct-Jobs bekommen in dieser Stufe kein eigenes
  Subcollection-Schema; sie sind in [KB_SYNC_AGENT.md](KB_SYNC_AGENT.md)
  als spaeterer Ausbau markiert.

## Collection: kb_documents/{docId}

Ein Dokument pro KB-Quelle aus `server/knowledge/`. Die Document ID ist ein
deterministischer Hash ueber `relativePath` (z. B. erste 24 Zeichen des
SHA-256 von `relativePath`); dadurch bleibt die ID bei Umbenennungen stabil,
wenn der Pfad stabil bleibt.

### Pflichtfelder

| Feld                 | Typ       | Beschreibung                                                              |
| -------------------- | --------- | ------------------------------------------------------------------------- |
| `docId`              | string    | Document ID (s. o.)                                                       |
| `relativePath`       | string    | Pfad ab `server/knowledge/`, Unix-Style                                   |
| `fileName`           | string    | Dateiname ohne Pfad                                                       |
| `sourceType`         | string    | `"knowledge_base_json" \| "reference_learning_json" \| "reference_learning_md"` |
| `contentType`        | string    | MIME-Typ des Mirrors in Storage                                           |
| `title`              | string    | Menschlich lesbarer Titel (aus Frontmatter/Key, sonst Dateiname)          |
| `summary`            | string    | Kurzbeschreibung (<= 1000 Zeichen)                                        |
| `searchTextPreview`  | string    | Erste 500 Zeichen durchsuchbarer Text; Ranking-Hinweis, keine Suche       |
| `storagePath`        | string    | `knowledge-base/current/<relativePath>` (Mirror)                          |
| `sha256`             | string    | SHA-256 ueber den Dateiinhalt des Mirrors                                 |
| `sizeBytes`          | number    | Dateigroesse in Byte                                                      |
| `sourceOfTruth`      | string    | Konstant `"repo"` in V1                                                    |
| `syncReleaseId`      | string    | Verweist auf `kb_sync_runs/{runId}`, der diese Version ins Mirror schob   |
| `syncedAt`           | timestamp | Zeit des letzten erfolgreichen Sync                                       |
| `updatedAt`          | timestamp | Zeit der letzten inhaltlichen Aenderung an diesem Dokument                |
| `language`           | string    | ISO 639-1; `"de"` oder `"en"` bzw. `"und"` wenn unklar                    |
| `baseTags`           | string[]  | Deterministisch abgeleitet aus Pfad, Typ, Keys                            |
| `aiFlags`            | map       | Optional, s. Abschnitt "aiFlags"                                          |
| `reviewStatus`       | string    | `"unreviewed" \| "approved" \| "rejected" \| "needs_review"`             |
| `isStructured`       | boolean   | `true` fuer JSON/MD mit klaren Keys/Headings, sonst `false`               |
| `isActive`           | boolean   | `false` blendet das Dokument fuer Retrieval aus                           |
| `visibility`         | string    | `"internal" \| "authenticated"`                                           |

### aiFlags (optional)

Wenn kein AI-Signal vorliegt, bleibt `aiFlags` leer (`{}`). Nie `null`.

| Feld                 | Typ       | Beschreibung                                                        |
| -------------------- | --------- | ------------------------------------------------------------------- |
| `status`             | string    | `"ok" \| "skipped" \| "error"`                                      |
| `topics`             | string[]  | Themen (z. B. `"norm"`, `"tolerance"`, `"sheet-metal"`)             |
| `failureClasses`     | string[]  | Gemaess `server/rules/failure_classes.py`                           |
| `searchAliases`      | string[]  | Alternative Suchbegriffe                                            |
| `relevanceScore`     | number    | 0.0-1.0 als grobe Relevanzgewichtung                                |
| `modelId`            | string    | Nachvollziehbarkeit (z. B. `"claude-opus-4-7"`)                     |
| `generatedAt`        | timestamp | Zeit der Flag-Erzeugung                                             |

### Invarianten

- `sourceOfTruth` ist immer `"repo"`; kein clientseitiges Dokument darf das
  aendern.
- `storagePath` beginnt immer mit `knowledge-base/current/`.
- `visibility="authenticated"` ist die Default-Stufe fuer V1.

## Subcollection: kb_documents/{docId}/chunks/{chunkId}

Ein Chunk je strukturiertem Abschnitt. Die `chunkId` ist deterministisch
(`<docId>_<ordinal>`), damit Deltas stabil bleiben.

### Pflichtfelder

| Feld            | Typ       | Beschreibung                                                   |
| --------------- | --------- | -------------------------------------------------------------- |
| `chunkId`       | string    | s. o.                                                          |
| `ordinal`       | number    | 0-basierte Reihenfolge im Dokument                             |
| `heading`       | string    | Abschnittsueberschrift oder Key; leerer String erlaubt         |
| `text`          | string    | Fliesstext des Chunks; max. ~8 KB empfohlen                    |
| `charCount`     | number    | Zeichenzahl von `text`                                         |
| `sectionPath`   | string[]  | Pfad der Ueberschriften-/Key-Hierarchie                        |
| `keywords`      | string[]  | Deterministisch extrahierte Schluesselbegriffe                 |
| `baseTags`      | string[]  | Erbt ueblicherweise die `baseTags` des Eltern-Dokuments        |
| `aiFlags`       | map       | Optional, analog zum Dokument; leer statt `null`               |
| `reviewStatus`  | string    | `"unreviewed" \| "approved" \| "rejected" \| "needs_review"` |
| `sourceType`    | string    | Erbt aus dem Elterndokument, redundant fuer Abfragen           |
| `updatedAt`     | timestamp | Zeit der letzten Aenderung des Chunks                          |

### Invarianten

- `ordinal` ist innerhalb eines Dokuments eindeutig.
- Ein Chunk darf nie ohne zugehoeriges Eltern-Dokument existieren.
- `charCount === text.length`.

## Collection: kb_sync_runs/{runId}

Ein Dokument pro Sync-Lauf. Die `runId` ist serverseitig vergeben (ULID).

### Pflichtfelder

| Feld                 | Typ       | Beschreibung                                                     |
| -------------------- | --------- | ---------------------------------------------------------------- |
| `runId`              | string    | s. o.                                                            |
| `startedAt`          | timestamp | Startzeit des Laufs                                              |
| `completedAt`        | timestamp | Endzeit; leerer Default wenn `status="running"`                 |
| `status`             | string    | `"running" \| "succeeded" \| "failed" \| "partial"`             |
| `releaseId`          | string    | Menschlich lesbar (z. B. Git-SHA oder Timestamp)                 |
| `filesScanned`       | number    | Anzahl der erkannten Dateien                                     |
| `filesUploaded`      | number    | Anzahl neuer/geaenderter Uploads ins Storage                     |
| `documentsUpserted`  | number    | Anzahl Firestore-Dokumente neu/aktualisiert                      |
| `chunksUpserted`     | number    | Anzahl Chunk-Schreiboperationen                                  |
| `aiFlaggedDocuments` | number    | Anzahl Dokumente mit erfolgreichem AI-Flagging                   |
| `skippedDocuments`   | number    | Anzahl Dokumente ohne AI-Flagging (Fallback-Pfad)                |
| `errors`             | string[]  | Kurzfassungen der aufgetretenen Fehler (<= 40 Eintraege)         |

### Invarianten

- `status="succeeded"` verlangt `errors.length === 0`.
- `status="partial"` ist der einzige Erfolgszustand mit `errors.length > 0`.
- `kb_documents` werden nie aktualisiert, ohne dass ein zugehoeriger Lauf
  mit `status="succeeded"` oder `"partial"` existiert.

## Storage-Pfadkonventionen

Diese Pfade sind kanonisch und werden vom Frontend ueber semantische
Helper in `src/services/firebaseStorageService.ts` (`uploadAvatar`,
`uploadExportSource`, `uploadExportOutput`, `uploadReconstructInput`,
`uploadAnalyzerInput`) erzeugt. Zufallsordner sind nicht erlaubt; jede
fachliche Einheit (Export, Reconstruct, Analyzer) bekommt eine stabile
ID.

| Pfad                                                    | Zugriff                                          |
| ------------------------------------------------------- | ------------------------------------------------ |
| `users/{uid}/avatar/<name>`                             | nur der jeweilige Nutzer, RW                     |
| `users/{uid}/exports/{exportId}/source/<name>`          | nur der jeweilige Nutzer, RW                     |
| `users/{uid}/exports/{exportId}/output/<name>`          | nur der jeweilige Nutzer, RW                     |
| `users/{uid}/reconstruct/{jobId}/input/<role>-<name>`   | nur der jeweilige Nutzer, RW                     |
| `users/{uid}/analyzer/{jobId}/input/<name>`             | nur der jeweilige Nutzer, RW                     |
| `knowledge-base/current/<relativePath>`                 | angemeldete Nutzer lesbar, Admin-only Schreiben  |
| `knowledge-base/releases/<releaseId>/...`               | nur Admin; optional fuer Release-Historie        |

ID-Vergabe:

- `exportId` wird clientseitig vor dem Backend-Call vergeben
  (`newClientExportId()`) und als `export_id` im Export-Request mitgesendet,
  damit Source- und Output-Upload denselben Pfad teilen. Sobald exports
  serverseitig persistiert werden, kann das Backend diese ID uebernehmen
  oder eine eigene vergeben; in beiden Faellen ist sie stabil und nicht
  zufaellig.
- `jobId` fuer Reconstruct kommt vom Backend; Storage-Mirror laeuft
  bewusst erst nach der Job-Vergabe, damit Pfad und Job-ID
  uebereinstimmen.
- `jobId` fuer Analyzer wird clientseitig erzeugt
  (`crypto.randomUUID()`) und als `job_id` an das Backend uebergeben; der
  Server uebernimmt diese ID bewusst und randomisiert sie nicht erneut.
- Avatar-Dateinamen erhalten ein Kurz-Suffix, um Kollisionen mit
  identischem Dateinamen zu vermeiden; der Pfadtyp (`avatar/`) bleibt
  fix.

## Analyzer- und Reconstruct-Anschluss

- Keine P1-Migration nach Firestore.
- Platzhaltende Subcollections (`users/{uid}/reconstruct/{jobId}`,
  `users/{uid}/analyzer/{jobId}`) sind im Schema bewusst offen gelassen.
- Wenn diese Jobs spaeter persistiert werden sollen, wird eine eigene TODO
  mit dem dann geltenden Feldvertrag erstellt; heutige Jobs laufen weiterhin
  ueber lokale Persistenz in `server/job_persistence.py`.
