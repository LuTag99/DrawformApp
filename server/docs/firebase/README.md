# Firebase Integration

Stand: 2026-04-17

Dieser Ordner enthaelt die verbindlichen Spezifikationen fuer die
Firebase-Integration von Drawform. Er ist die kanonische Quelle fuer:

- das Firestore-Datenmodell fuer Nutzer, Exports und Knowledge Base
- die Firebase Rules fuer Firestore und Storage
- den serverseitigen KB-Sync-/Flagging-Agenten
- die Kosten- und Betriebsgrenzen

## Dokumente

- [DATA_MODEL.md](DATA_MODEL.md) - Firestore-Collections und Feldvertraege
- [RULES.md](RULES.md) - Zugriffslogik fuer Firestore und Storage
- [KB_SYNC_AGENT.md](KB_SYNC_AGENT.md) - Startup-Delta-Sync, Hybrid-Tagging,
  Retrieval-Vorbereitung
- [OPERATIONS.md](OPERATIONS.md) - Kosten, Budget Alerts, Secret-Disziplin

## Geltungsbereich

- Authoritativer Code-Aufhaenger fuer Client: `src/lib/firebase.ts`
- Authoritativer Code-Aufhaenger fuer Server: `server/main.py` (Admin SDK)
- Rules-/Config-Dateien liegen im Repo-Root:
  - `firebase.json`
  - `firestore.rules`
  - `firestore.indexes.json`
  - `storage.rules`

## Grundprinzipien

1. Das Repo bleibt die Source of Truth fuer strukturierte KB-Inhalte;
   Firebase ist Mirror und Zugriffsschicht.
2. Jede Client-Schreiboperation ist auf den eigenen Nutzerpfad begrenzt.
3. KB-Schreibzugriffe erfolgen ausschliesslich serverseitig ueber das Admin SDK.
4. Analyzer- und Reconstruct-Jobs sind in dieser Stufe bewusst nicht als
   produktive Firestore-Migration eingeplant; nur Anschlussfaehigkeit wird
   vorbereitet.
