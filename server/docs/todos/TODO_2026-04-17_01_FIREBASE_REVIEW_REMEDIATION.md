# TODO Senior Developer - Firebase Review Remediation

Stand: 2026-04-18
Status: erledigt
Prioritaet: hoch

## TASK CLASSIFICATION

- Task summary: Die im Senior-Review gefundenen Firebase-/Auth-/Rules-/Storage-Probleme gezielt schliessen, ohne neue Seiteneffekte oder Token-Verschwendung in der Umsetzungsarbeit zu erzeugen.
- Domain impact: hoch
- Path type: FULL-PATH
- Required agents: Senior Developer, anschliessend Review/Regression
- Required artifacts: Code-Diff, gezielte Tests, aktualisierte Docs, klare Auth-/Rules-/Pfadentscheidungen
- Main acceptance risk: Sicherheitslogik, Dev-/CI-Betrieb und Spec-/Code-Drift gleichzeitig anfassen und dabei nur Symptome statt Root Causes zu fixen

## Ziel

Die aktuelle Firebase-Haertung so nacharbeiten, dass sie:

1. lokal, in CI und produktionsnah konsistent laeuft,
2. die dokumentierten Sicherheitsregeln wirklich durchsetzt,
3. nicht gegen die eigene Daten- und Pfadspezifikation arbeitet,
4. den Frontend-/Backend-Gate wieder gruen bekommt,
5. fuer spaetere Firestore- und KB-Implementierung stabil anschlussfaehig bleibt.

## Kontext

Die letzte Challenge hat vier technische Kernprobleme gezeigt:

1. Backend-Endpunkte sind jetzt auth-pflichtig, aber es gibt keinen sauberen Dev-/CI-Modus und keine angepassten Tests.
2. `kb_documents/{docId}/chunks/{chunkId}` sind in den Firestore Rules lesbar, auch wenn das Parent-Dokument fachlich nicht lesbar sein duerfte.
3. Die implementierten Storage-Pfade weichen von der dokumentierten Spezifikation ab.
4. Das Frontend-Lint-Gate ist wegen eines synchronen `setState` im Effect gebrochen.

Zusatzproblem:

- README- und Betriebsbeispiele laufen noch gegen eine alte Annahme ohne Bearer-Token bzw. ohne klaren lokalen Auth-Modus.

## Leitprinzipien

- Keine symptomatischen Quick-Fixes.
- Kein weiterer Scope-Slide in Firestore-Implementierung, KB-Agent oder Vollintegration.
- Keine grossen "Refactor alles in einem Commit"-Aenderungen.
- Jede Teilkorrektur bekommt einen klaren technischen Vertrag und einen eigenen Nachweis.
- Security- und Betriebslogik werden nicht nur dokumentiert, sondern technisch und per Test beweisbar gemacht.

## Token-Sparmodus fuer das KI-Modell

Diese Liste ist explizit so formuliert, dass eine KI fuer die Umsetzung wenig irrelevanten Kontext laden muss.

### Kontextgrenzen

- Nicht das ganze Repo laden.
- Nicht `package-lock.json` lesen, ausser eine Dependency-Frage ist direkt betroffen.
- Nicht ganze grosse Dateien am Stueck lesen, wenn gezielte `rg`-Treffer reichen.
- Archivierte TODOs nur oeffnen, wenn ein historischer Entscheid wirklich unklar ist.
- Fuer `server/main.py` nur die Auth-relevanten Bereiche laden.

### Zuerst nur diese Dateien lesen

- `server/main.py`
- `server/test_api_endpoints.py`
- `.env.example`
- `README.md`
- `server/README.md`
- `firestore.rules`
- `server/docs/firebase/RULES.md`
- `server/docs/firebase/DATA_MODEL.md`
- `src/providers/AuthProvider.tsx`
- `src/services/firebaseStorageService.ts`
- `src/services/exportService.ts`
- `src/services/analyzerService.ts`
- `src/services/reconstructService.ts`
- `src/pages/profile/ProfilePage.tsx`

### Kontext sparsam ziehen

Empfohlene erste Kommandos:

```powershell
rg -n "DRAWFORM_REQUIRE_FIREBASE_AUTH|FIREBASE_AUTH_ENABLED|require_current_user|Depends\(require_current_user\)" server/main.py server/test_api_endpoints.py .env.example README.md server/README.md
rg -n "kb_documents|chunks|isActive|visibility" firestore.rules server/docs/firebase/RULES.md server/docs/firebase/DATA_MODEL.md
rg -n "buildStoragePath|uploadUserFile|uploadUserBlob|makeStorageFolder|storagePath" src/services/firebaseStorageService.ts src/services/exportService.ts src/services/analyzerService.ts src/services/reconstructService.ts src/pages/profile/ProfilePage.tsx
rg -n "setLoading\\(|useEffect\\(" src/providers/AuthProvider.tsx
```

### Arbeitsweise

- Erst Root Cause festziehen, dann patchen.
- Immer nur die direkt betroffenen Dateien oeffnen.
- Nach jedem Arbeitspaket nur den kleinsten relevanten Testlauf ausfuehren.
- Erst am Ende die kombinierten Gates laufen lassen.
- Keine breit formulierten KI-Prompts wie "analysiere die Firebase-Integration komplett".
- Stattdessen immer file- und problemgebunden arbeiten.

## P0 - Auth-Vertrag fuer Backend, Dev und CI sauber ziehen

### Problem

Der aktuelle Zustand erzwingt Bearer-Auth fuer produktive Endpunkte, bietet aber weder:

- einen klaren lokalen Dev-Bypass,
- noch einen sauberen Testpfad,
- noch aktualisierte Beispiele,
- noch konsistente Testanpassungen.

### Ziel

Ein expliziter Auth-Vertrag mit genau zwei klaren Modi:

1. `AUTH_REQUIRED`
2. `AUTH_DISABLED_FOR_LOCAL_DEV_AND_TEST`

Kein Zwischenzustand, in dem "disabled" trotzdem nur 503 produziert.

### Exakte Dateien

- `server/main.py`
- `server/test_api_endpoints.py`
- `.env.example`
- `README.md`
- `server/README.md`

### Erwartete Root-Cause-Fixes

1. Auth-Entscheidung kapseln
   - Nicht jede Route indirekt an globale, schwer testbare Initialisierung haengen.
   - Auth-Check und Firebase-Admin-Initialisierung in eine klar testbare Schicht ziehen.

2. Dev-/Test-Verhalten explizit modellieren
   - Wenn `DRAWFORM_REQUIRE_FIREBASE_AUTH=0`, darf der Backend-Pfad lokal nicht mit 503 blockieren.
   - Entweder:
     - ein lokaler Stub-User wird fuer Dev/Test geliefert,
     - oder die Dependency wird fuer Tests/Dev ueberschreibbar gemacht.
   - Die Entscheidung muss bewusst und dokumentiert sein.

3. Tests an den Vertrag anbinden
   - `server/test_api_endpoints.py` darf nicht mehr stillschweigend von "keine Auth" ausgehen.
   - Tests muessen entweder:
     - einen Dev-Bypass explizit aktivieren,
     - oder `require_current_user` kontrolliert overriden,
     - oder gueltige Test-Claims injizieren.

4. Dokumentation synchronisieren
   - Curl-/README-Beispiele muessen den realen Auth-Vertrag zeigen.
   - Wenn fuer lokale Quickstarts Auth optional ist, muss das sichtbar und copy-paste-faehig beschrieben sein.

### Nicht akzeptabel

- `DRAWFORM_REQUIRE_FIREBASE_AUTH=0` bleibt praktisch unbenutzbar.
- Tests werden nur "gruen gemacht", indem sie Auth komplett umgehen, ohne den Vertrag zu dokumentieren.
- README bleibt auf tokenlose Beispiele stehen, waehrend der Server Auth erzwingt.

### Empfohlene Implementierungsreihenfolge

1. Auth-Modus in `server/main.py` entkoppeln.
2. Teststrategie in `server/test_api_endpoints.py` festziehen.
3. Erst danach `.env.example`, `README.md`, `server/README.md` angleichen.

### Akzeptanz

- `python -m pytest server/test_api_endpoints.py -q` ist gruen.
- Ein lokaler Probe-Call gegen `/api/ai-insight` oder `/api/export` hat in Dev/Test einen klaren, dokumentierten Pfad.
- README-Beispiele sind real ausfuehrbar.

## P1 - Firestore-Chunk-Sichtbarkeit gegen Parent-Dokument haerten

### Problem

Die Rules erlauben Chunk-Reads bereits fuer jeden angemeldeten Nutzer, ohne Parent-Status (`isActive`, `visibility`) technisch mitzupuefen.

### Ziel

Chunks sind nur dann lesbar, wenn das zugehoerige Parent-Dokument lesbar waere.

### Exakte Dateien

- `firestore.rules`
- `server/docs/firebase/RULES.md`
- optional spaeter Testdateien fuer Emulator-Regeln

### Erwartete Root-Cause-Fixes

1. Parent-basierte Guard in Rules
   - Kein rein textlicher Kommentar mehr.
   - Die Rule muss das Parent-Dokument wirklich referenzieren und dessen Flags pruefen.

2. Sichtbarkeit zentralisieren
   - Idealerweise eine kleine Helper-Funktion fuer KB-Lesbarkeit definieren, statt dieselbe Logik mehrfach inline zu verteilen.

3. Doc-Sync
   - Die Spezifikation darf nur behaupten, was die Rule auch wirklich tut.

### Nicht akzeptabel

- Chunk-Zugriff bleibt breiter als Dokument-Zugriff.
- Der Fix wird nur in Markdown nachgezogen, nicht in den Rules.
- Parent-Logik wird dupliziert und driftet spaeter wieder auseinander.

### Akzeptanz

- Rule-Ausdruck fuer Chunk-Reads ist an Parent-Lesbarkeit gekoppelt.
- Spezifikation und Rule-Text sind deckungsgleich.
- Falls Regeltests vorhanden oder neu angelegt werden, gibt es mindestens:
  - pass fuer aktives `authenticated`-Dokument,
  - fail fuer `internal`,
  - fail fuer `isActive=false`.

## P2 - Storage-Pfade auf einen kanonischen Vertrag umstellen

### Problem

Aktueller Code schreibt unter generische Pfade wie:

- `users/{uid}/profile/...`
- `users/{uid}/exports/<random-folder>...`
- `users/{uid}/reconstruct/<random-folder>...`

Die Spezifikation erwartet aber fachlich stabile Pfade wie:

- `users/{uid}/avatar/<name>`
- `users/{uid}/exports/{exportId}/source/<name>`
- `users/{uid}/exports/{exportId}/output/<name>`
- `users/{uid}/reconstruct/{jobId}/...`

### Ziel

Ein klarer, stabiler Storage-Pfadvertrag, der:

- mit der Spec uebereinstimmt,
- spaetere Firestore-Metadaten sauber referenzieren kann,
- keine zufaelligen Ordner als fachliche IDs missbraucht.

### Exakte Dateien

- `src/services/firebaseStorageService.ts`
- `src/services/exportService.ts`
- `src/services/analyzerService.ts`
- `src/services/reconstructService.ts`
- `src/pages/profile/ProfilePage.tsx`
- `server/docs/firebase/DATA_MODEL.md`
- optional `server/docs/firebase/OPERATIONS.md`

### Technische Entscheidung, die zuerst fallen muss

Es gibt nur zwei saubere Wege:

1. Code an Spec angleichen.
2. Spec bewusst an Code angleichen.

Empfehlung:

- Code an Spec angleichen, nicht umgekehrt.
- Die aktuelle Spec ist fuer spaetere Metadaten-/Job-Korrelation deutlich besser.

### Erwartete Root-Cause-Fixes

1. Storage-Path-Builder fachlich modellieren
   - Nicht nur `area + folder + filename`.
   - Stattdessen semantische Pfadtypen, z. B.:
     - Avatar
     - Export Source
     - Export Output
     - Reconstruct Input
     - Analyzer Input

2. Fachliche IDs sauber einfuehren
   - Export braucht eine stabile `exportId`.
   - Reconstruct braucht eine stabile `jobId`.
   - Falls die ID clientseitig vor dem Backend-Call entstehen muss, dann bewusst und dokumentiert.

3. Zufallsordner nur dort, wo sie fachlich legitim sind
   - Nicht als Ersatz fuer `exportId`/`jobId`.
   - Fuer einmalige Avatar-Dateinamen kann ein Suffix legitim sein, aber der Pfadtyp selbst muss kanonisch bleiben.

4. Analyzer bewusst entscheiden
   - Wenn Analyzer noch kein final spezifizierter Firestore-Pfad ist, trotzdem einen klaren internen Storage-Vertrag definieren.
   - Kein halber Spezialfall im selben allgemeinen Helper.

### Nicht akzeptabel

- Nur die Spec wird weich formuliert, damit der bestehende Code "irgendwie passt".
- `makeStorageFolder()` bleibt fachlicher ID-Ersatz fuer Export/Reconstruct.
- Avatar bleibt unter `profile/` statt unter einem klar benannten Avatar-Pfad.

### Akzeptanz

- Pfadlogik ist zentral und semantisch.
- Export- und Reconstruct-Pfade enthalten stabile IDs statt Zufallsordnern.
- Spec und Code referenzieren dieselben Pfade.

## P3 - Frontend-Lint-Gate und AuthProvider sauberstellen

### Problem

`npm run lint` scheitert wegen synchronem `setState` im Effect des `AuthProvider`.

### Ziel

Lint wieder gruen, ohne die Semantik des Auth-Flows zu verschlechtern.

### Exakte Dateien

- `src/providers/AuthProvider.tsx`
- optional angrenzend `src/providers/authTypes.ts`

### Erwarteter Root-Cause-Fix

- `loading` nicht im Effect fuer den Fall "Firebase nicht konfiguriert" synchron umstellen.
- Stattdessen den Initialzustand so modellieren, dass:
  - bei konfiguriertem Firebase `loading=true` startet,
  - bei nicht konfiguriertem Firebase `loading=false` startet.

Beispielrichtung:

- `const [loading, setLoading] = useState(firebaseConfigured);`

Danach laeuft der Effect nur noch fuer den echten Subscribe-Fall.

### Nicht akzeptabel

- ESLint-Regel deaktivieren.
- Workaround mit `setTimeout`.
- Mehr Kontext- oder State-Komplexitaet als noetig.

### Akzeptanz

- `npm run lint` ist gruen.
- Das Login-/Protected-Route-Verhalten bleibt funktional korrekt.

## P4 - Docs, Beispiele und Betriebsdisziplin synchronisieren

### Problem

Die derzeitigen README-Texte und Betriebsbeispiele sind nicht mehr deckungsgleich mit dem echten Auth-/Storage-Vertrag.

### Ziel

Ein Senior Developer soll nach der Aenderung weder raetseln muessen, welcher Modus lokal gilt, noch welches Beispiel veraltet ist.

### Exakte Dateien

- `README.md`
- `server/README.md`
- `.env.example`
- optional `server/docs/firebase/OPERATIONS.md`

### Erwartete Fixes

1. Auth-Voraussetzungen explizit machen
   - Bearer-Token noetig oder Dev-Bypass explizit.
   - Keine impliziten Annahmen.

2. Lokale Schnellstartpfade trennen
   - "Mit Firebase Auth"
   - "Lokaler Dev/Test ohne Firebase Auth", falls bewusst unterstuetzt

3. Storage-/Firestore-Versprechen auf den realen Scope begrenzen
   - Keine Formulierungen, die bereits produktive Firestore-Integration suggerieren, wenn diese laut Haupt-TODO noch offen ist.

### Nicht akzeptabel

- README bleibt marketingnah, aber technisch ungenau.
- `.env.example` beschreibt einen Modus, der praktisch nicht funktioniert.

### Akzeptanz

- Ein neuer Entwickler kann die lokale Betriebsart ohne Rueckfragen starten.
- Die Docs behaupten nicht mehr als der Code aktuell kann.

## Empfohlene Umsetzungsreihenfolge

1. P0 Auth-Vertrag und Testfaehigkeit
2. P3 Lint-Fix fuer schnellen Frontend-Gate
3. P1 Firestore-Chunk-Absicherung
4. P2 Storage-Pfade auf kanonischen Vertrag
5. P4 Docs final synchronisieren

Grund:

- P0 und P3 geben schnell wieder gruenes technisches Feedback.
- P1 schliesst den klarsten Security-Fehler.
- P2 ist der groesste semantische Eingriff und braucht danach aktualisierte Docs.

## Minimaler Testplan je Arbeitspaket

### Nach P0

```powershell
python -m pytest server/test_api_endpoints.py -q
```

### Nach P1

Wenn bereits Regeltests existieren oder parallel angelegt werden:

```powershell
firebase emulators:exec --only firestore "npm run build"
```

Wenn noch keine Regeltests existieren:

- mindestens Rule-Review mit dokumentiertem Parent-Check
- anschliessend eigener Folgepunkt fuer Emulator-Regeltests in der Hauptliste referenzieren

### Nach P2

```powershell
npm run build
```

Gezielt pruefen:

- Avatar-Upload
- Export Source/Output Upload
- Reconstruct Input Upload

### Nach P3

```powershell
npm run lint
```

### Abschlusslauf

```powershell
npm run lint
npm run build
python -m pytest server/test_api_endpoints.py -q
python -m pytest server/tests -q
```

## Definition of Done

- Auth-Vertrag fuer lokale Entwicklung, Tests und produktionsnahe Nutzung ist explizit und technisch umsetzbar.
- `server/test_api_endpoints.py` ist wieder gruen.
- Firestore-Chunk-Reads sind an Parent-Sichtbarkeit gekoppelt.
- Storage-Pfade folgen einem kanonischen, stabilen Vertrag.
- `npm run lint` ist wieder gruen.
- README, Server-README und `.env.example` sind konsistent mit dem realen Verhalten.
- Keine neue Firestore-Vollintegration wird stillschweigend in diesen Scope hineingezogen.

## Nicht akzeptabel

- Sicherheitsfix nur in Docs, nicht in Rules.
- Testfix nur ueber globales Abschalten von Auth ohne klaren Vertrag.
- Pfadfix nur ueber "Spec weichschreiben".
- Lintfix ueber Rule-Disable.
- README-Beispiele bleiben unbrauchbar.
