# Knowledge Base Sync & Flagging Agent

Stand: 2026-04-17
Status: aktiv

Dieses Dokument beschreibt, wie strukturierte KB-Inhalte aus
`server/knowledge/` in Firebase Storage und Firestore gespiegelt werden
(P3) und wie der serverseitige Sync-/Flagging-Agent arbeitet (P4).

Der ausfuehrbare Agent folgt in der Code-Struktur unter
`server/knowledge/firebase_sync/` (noch anzulegen); diese Spezifikation
ist dem Agenten vorgelagert und verbindlich.

## V1-Scope

### In Scope

- `server/knowledge/knowledge_base.json`
- `server/knowledge/reference_learning/*.json`
- `server/knowledge/reference_learning/*.md`

### Out of Scope fuer V1

- Literatur-PDFs unter `server/knowledge/Literatur/`
- Unstrukturierte Altbestaende ohne Headings oder Keys
- LITERATURE_*.md Langdokumente (separate Entscheidung je Datei,
  standardmaessig ausgeschlossen)

### Mirror-Prinzip

- Das Repo bleibt Source of Truth (`sourceOfTruth = "repo"`).
- Firebase spiegelt den V1-Scope unter
  `knowledge-base/current/<relativePath>` in Storage
  und unter `kb_documents/{docId}` in Firestore.
- Firebase ist Lesepfad und Retrieval-Schicht, nicht Authoring-System.

## Pipeline-Uebersicht

```
[Backend Startup]
     |
     v
[Background Task: kb_sync_agent.run_startup_sync]
     |
     +--> Scan V1-Scope-Dateien
     |
     +--> SHA-256 berechnen
     |
     +--> mit Firestore-Stand vergleichen (Delta)
     |
     +--> fuer geaenderte Dateien:
     |        - Storage Upload -> knowledge-base/current/...
     |        - Chunks bauen (deterministisch)
     |        - baseTags / keywords ableiten
     |        - optional: aiFlags berechnen
     |        - kb_documents / chunks upserten
     |
     +--> kb_sync_runs/{runId} mit Ergebnisse updaten
```

## Startup-Verhalten

- Der Agent startet als *nicht blockierender* Hintergrund-Task im
  FastAPI-Lifecycle (`@app.on_event("startup")` oder aequivalent).
- Der API-Start darf nicht scheitern, wenn der Sync fehlschlaegt.
- Bei Fehlstart laeuft die API weiter; der letzte Laufstatus wird in
  `kb_sync_runs/{runId}` mit `status="failed"` oder `"partial"`
  persistiert.
- Budgetgrenze: Ein Lauf bricht spaetestens nach einer konfigurierbaren
  Zeit (`DRAWFORM_KB_SYNC_MAX_SECONDS`, Default 300) ab und markiert sich
  als `partial`.

## Delta-Strategie

1. Liste aller V1-Scope-Dateien im Repo aufbauen (normalisierter Pfad).
2. SHA-256 je Datei berechnen.
3. Aktuellen Stand aus Firestore lesen
   (`kb_documents`, Projektion auf `sha256` + `storagePath`).
4. Menge der Dateien bilden:
   - NEU: im Repo, nicht in Firestore
   - GEAENDERT: Pfad vorhanden, aber `sha256` unterschiedlich
   - UNVERAENDERT: beide gleich
   - OBSOLET: in Firestore, aber nicht mehr im Repo-Scope
5. Nur NEU und GEAENDERT werden hochgeladen und neu indiziert.
6. OBSOLETE Dokumente werden auf `isActive=false` gesetzt (kein
   Hard-Delete, kein Storage-Delete in V1).
7. UNVERAENDERTE Dokumente werden nicht geschrieben; `syncedAt` wird
   nicht erneuert, wenn der Inhalt gleich bleibt.

Ein Vollreindex bei jedem Start ist ausdruecklich **nicht** akzeptabel.

## Chunking

- JSON mit Top-Level-Keys: je Key ein Chunk, `sectionPath = [key]`.
- Geschachtelte JSON-Strukturen: tiefer nur, wenn Keys semantisch
  sichtbar sind (z. B. `rules.milling.*`).
- Markdown: Split auf `##`-Ueberschriften; `sectionPath` spiegelt die
  Headings-Hierarchie ab.
- `text`-Obergrenze pro Chunk: ~8 KB. Laengere Abschnitte werden in
  stabile Teilchunks mit fortlaufendem `ordinal` geteilt.
- `chunkId = "<docId>_<ordinal>"`; damit bleiben Ids stabil, solange
  Reihenfolge und Chunking-Regel stabil bleiben.

## Hybrid-Tagging

Das Tagging laeuft in zwei klar getrennten Stufen:

### Deterministische `baseTags`

Quellen:

- Pfad-Segmente unter `server/knowledge/` (z. B. `reference_learning`,
  `knowledge_base`)
- Dateityp (`json`, `markdown`)
- JSON-Top-Level-Keys (z. B. `milling`, `sheet_metal`, `tolerance`)
- Markdown-Top-Level-Headings
- Bekannte Domainbegriffe aus
  `server/rules/failure_classes.py` und
  `server/docs/DRAWFORM_ERROR_TAXONOMY.md`

Regeln:

- Lowercase, trim, keine Leerzeichen, keine Umlaute (ASCII-fold).
- Stabiles Set pro Input; keine Zufallssignale.
- `baseTags` ist auch dann gefuellt, wenn kein AI-Signal vorliegt.

### Optionale `aiFlags`

- Nur als Zusatzsignal.
- Fehlt die AI-Konfiguration (`DRAWFORM_AI_PROVIDER` o. ae.), bleiben
  `aiFlags` mit `status="skipped"` leer. Der Sync endet **trotzdem**
  erfolgreich (ggf. `partial`, aber niemals `failed` wegen fehlender AI).
- Inhalte koennen sein: `topics`, `failureClasses`, `searchAliases`,
  `relevanceScore`, `modelId`, `generatedAt`.
- Kosten-Guard: AI-Flagging laeuft nur auf NEU/GEAENDERT, nie auf
  unveraenderte Dokumente.

## Retrieval-Vorbereitung (keine Suche in V1)

- Chunks sind die Retrieval-Einheit, nicht Dokumente.
- Harte Filter fuer spaetere Suche:
  - `kb_documents.isActive == true`
  - `kb_documents.visibility == 'authenticated'`
  - `kb_documents.reviewStatus != 'rejected'`
- `keywords` und `baseTags` sind das primaere Filter- und
  Ranking-Signal.
- `aiFlags.topics` / `aiFlags.searchAliases` sind optionale Booster,
  niemals die alleinige Wahrheit.
- Freier Textabgleich ueber `searchTextPreview` ist nur ein
  Low-Confidence-Fallback und wird in V1 noch nicht aktiviert.

## Agent-Module (geplant)

Alle Pfade unter `server/knowledge/firebase_sync/`:

- `__init__.py`
- `agent.py` - `run_startup_sync()`, Orchestrierung
- `scope.py` - Scope-Definition (V1-Liste, Path-Filter)
- `hashing.py` - SHA-256 + normalisierte Pfade
- `chunker.py` - deterministisches Chunking fuer JSON/MD
- `tagging.py` - `baseTags` + `keywords`
- `ai_flagging.py` - optionaler AI-Adapter mit Skip-Pfad
- `firestore_client.py` - Admin SDK Wrapper, Upserts mit Batching
- `storage_client.py` - Admin SDK Wrapper fuer Uploads + Compare
- `run_state.py` - `kb_sync_runs` Persistenz

Diese Module werden in einer Folge-TODO implementiert. Die
Schnittstelle zu `server/main.py` ist dabei:

```python
from knowledge.firebase_sync import kb_sync_agent

@app.on_event("startup")
async def _schedule_kb_sync():
    asyncio.create_task(kb_sync_agent.run_startup_sync())
```

## Fehlerverhalten und Idempotenz

- Jeder Upsert ist idempotent; mehrfacher Lauf auf dem gleichen Scope
  produziert denselben Firestore-Zustand.
- Einzelne Fehler pro Datei werden in `kb_sync_runs.errors` gesammelt
  und markieren den Lauf als `partial`, ohne den Gesamtlauf abzubrechen.
- Ein vollstaendig fehlgeschlagener Lauf (`status="failed"`) darf die
  zuletzt gueltigen Firestore-Dokumente nicht beschaedigen; es gibt
  kein "halbfertiges" Dokument ohne `syncReleaseId`.

## Abgrenzung

- Kein produktiver Firestore-Schreibpfad fuer Analyzer- oder
  Reconstruct-Jobs. Diese Jobs bleiben in V1 lokal persistiert; nur die
  Anschlussfaehigkeit (`users/{uid}/analyzer/{jobId}`,
  `users/{uid}/reconstruct/{jobId}`) ist in
  [DATA_MODEL.md](DATA_MODEL.md) als reservierter Namensraum markiert.
- Kein clientseitiger Schreibzugriff auf KB-Daten. Jede
  KB-Schreiboperation laeuft ueber dieses Agenten-Modul und damit ueber
  das Admin SDK.
