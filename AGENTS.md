# Drawform v2 - Globale Policy und Routing

## Zweck

Diese Datei ist der gemeinsame Vertrag fuer alle Drawform-Agenten.
Sie definiert globale Regeln, Taxonomien, Routing, Laufkontext und Artefaktpflichten.
Sie ersetzt nicht die Rollenidentitaet der Dateien `Agent_*.md`.
Die Fachrollen behalten ihre Rolle; `AGENTS.md` liefert den gemeinsamen Rahmen.

## Produktkontext

Drawform ist eine CAD-nahe Plattform fuer die Automatisierung von ingenieur- und fertigungsnahen Prozessen.
Im aktuellen MVP liegt der Fokus auf der automatisierten Erstellung professioneller 2D-Fertigungszeichnungen aus 3D-Modellen.

## Repository Sync Contract

- `AGENTS.md` ist die kanonische Quelle fuer Workflow, Routing, Gates und Failure Classes.
- `REPO_SYNC_POLICY.md` regelt die Besitzverhaeltnisse zwischen `AGENTS.md`, `.claude/`, `.github/`, `.vscode/`, `README.md` und `DEVELOPER_DOCS.md`.
- Live-Pass/Fail-Staende gehoeren nicht in Spiegel-Dokumente, sondern in aktuelle Command-Evidenz und `run_state.json`.

## Oberstes Ziel im MVP

Erzeuge nicht nur eine exportierbare Datei, sondern eine fachlich brauchbare, professionell wirkende technische Zeichnung.

## Erfolgskriterium

Ein Ergebnis ist nur dann erfolgreich, wenn ein erfahrener Konstrukteur die Zeichnung als plausibel, lesbar und weitgehend brauchbar akzeptieren wuerde.

## Nicht verhandelbare Grundregeln

- Ein technisch erfolgreicher Export ist kein Erfolg.
- PDF, SVG, DXF oder andere Ausgabedateien gelten nur dann als erfolgreich, wenn auch die Zeichnungsqualitaet tragfaehig ist.
- Schoenrede keine schwachen Zeichnungen.
- Gib keine allgemeine Kritik ohne konkrete technische Folgerung.
- Wenn derselbe Fehler erneut auftritt, benenne die Root Cause explizit.
- Wenn Unsicherheit ueber den Domain Impact besteht, waehle mindestens `FULL-PATH`.
- Jede Rolle liest zuerst `AGENTS.md` und arbeitet dann erst in ihrer Fachrolle weiter.
- Lange Laeufe duerfen keinen Kontext verlieren; derselbe `run_id` und derselbe Artefaktordner muessen ueber alle Handoffs erhalten bleiben.

## Reale Kernmodule im Repo

Pruefe bei Aufgaben rund um die Zeichnungsqualitaet immer zuerst diese Dateien:

- `server/main.py`
- `server/freecad/step_to_pdf.py`
- `server/freecad/step_feature_probe.py`
- `server/freecad/step_unfold.py`
- `server/rules/dimension_strategy.py`
- `server/rules/dimension_plan_schema.py`
- `server/test_views.py`
- `server/_debug/*`
- `server/docs/DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`

## Task Routing

### Pflichtausgabe zur Einordnung

Jeder Task beginnt mit dieser Einordnung:

```md
TASK CLASSIFICATION
- Task summary:
- Domain impact:
- Path type: FAST-PATH, MEDIUM-PATH, FULL-PATH or LONG-RUN
- Required agents:
- Required artifacts:
- Main acceptance risk:
```

### Pflichtausgabe zum Laufkontext

Jeder Lauf ab `FULL-PATH` fuehrt denselben Kontext ueber alle Rollen:

```md
RUN CONTEXT
- Run ID:
- Iteration:
- Path type:
- Target case:
- Benchmark set:
- Artifact dir:
- Previous verdict:
- Previous failure classes:
- Required commands:
```

### FAST-PATH

Nutze `FAST-PATH` nur, wenn die Aenderung klein ist und keinen sinnvollen Einfluss auf Zeichnungslogik, Benchmark-Verhalten oder fachliche Zeichnungsqualitaet hat.

Typische Faelle:

- UI-Fix ohne Einfluss auf Export- oder Zeichnungslogik
- Dateibenennung oder Pfadlogik
- Logging oder Observability
- harmloses Parser-Cleanup ohne Verhaltensaenderung
- kleine Infrastruktur- oder Dokumentationsaenderung ohne Aenderung der Agenten- oder Qualitaetslogik

Nicht `FAST-PATH`, wenn Prompt-, Regel- oder Prozesslogik fuer die Agenten selbst geaendert wird und dadurch Routing, Freigabe oder Qualitaetsmassstaebe beeinflusst werden koennen.

### MEDIUM-PATH

`MEDIUM-PATH` ist fuer Aenderungen, die den Zeichnungsoutput beeinflussen, aber kein neues Rendering erfordern, weil sich das sichtbare Ergebnis vorhersagbar aendert.

Typische Faelle:

- Schriftfeld-Aenderungen (Title-Block-Felder, Labels, Formatierung)
- Skalenlabel-Logik ohne Aenderung der tatsaechlichen Skalierung
- Aenderungen an Annotationstext oder Info-Zeilen
- Testtoleranzen oder Check-Logik in `test_views.py`
- DSE-Plan-Pipeline-Aenderungen ohne Aenderung der Planlogik selbst

Nicht `MEDIUM-PATH`, wenn Ansichtswahl, Massstab, Bemaessungsplatzierung oder Layoutlogik betroffen sind.

MEDIUM-PATH Workflow:

1. Task klassifizieren.
2. Aenderung umsetzen.
3. Baseline-Golden regenerieren (`--update-golden`).
4. Regression pruefen (20/20 baseline).
5. Delta-Scoring: Critic bewertet nur die geaenderten Kriterien (nicht alle 7).
6. Iteration dokumentieren.

### FULL-PATH

`FULL-PATH` ist verpflichtend, wenn die Aufgabe einen der folgenden Bereiche betrifft:

- Hauptansichtsauswahl
- Ableitung von Top-, Seiten- oder Isometrieansicht
- Bemaessungslogik
- Lochbildklarheit
- Hidden-Line-, Sichtbarkeits- oder Projektionsthemen
- Blattlayout, Massstab oder Blattnutzung
- Regel- oder Heuristiksystem
- Qualitaetsbewertung oder Scores
- Fertigbarkeit oder fachliche Nutzbarkeit
- Benchmark-Verhalten
- regressionsempfindlichen Output
- Agentenlogik, wenn sie Routing oder Qualitaetsfreigabe veraendert

### LONG-RUN

`LONG-RUN` ist verpflichtend, wenn eine Aufgabe nicht nur richtig, sondern ueber mehrere Laeufe hinweg stabil und release-nah abgesichert werden muss.

Typische Faelle:

- Release-Kandidat oder Uebergabe an externe Reviewer
- Aenderung betrifft mehrere Geometrieklassen oder Querschnitts-Heuristiken
- derselbe Fehler tritt ab Iteration `2` erneut auf
- Instabilitaet oder nicht deterministischer Output wird vermutet
- ein `FULL-PATH` reicht als Nachweis qualitativ nicht aus

`LONG-RUN` ist ein verschaerfter `FULL-PATH` mit persistentem Laufstatus, erweitertem Benchmark-Umfang, Stabilitaetslaeufen und doppelter Freigabelogik.

### Routing-Regeln

- `FAST-PATH` => `Agent_planner.md` in `LIGHT` mode -> `Agent_builder.md` -> `Agent_critic.md` in `LIGHT` mode -> `Agent_report.md`
- `MEDIUM-PATH` => `Agent_builder.md` -> Baseline-Golden regenerieren -> Regression (20/20) -> `Agent_critic.md` in `DELTA` mode -> `Agent_report.md`
- `FULL-PATH` => `Agent_planner.md` -> `Agent_builder.md` -> `Agent_artifact_steward.md` -> `Agent_critic.md` -> `Agent_regression.md` -> `Agent_report.md`
- `LONG-RUN` => `Agent_planner.md` -> `Agent_builder.md` -> `Agent_artifact_steward.md` -> `Agent_critic.md` -> `Agent_regression.md` -> iterative `Agent_builder.md` / `Agent_artifact_steward.md` / `Agent_critic.md` / `Agent_regression.md` cycles as needed -> `Agent_report.md`

## Run Context und Persistenz

### Ziel

Lange oder komplexe Laeufe duerfen ihren Zustand nicht nur im Chat behalten.
Ab `FULL-PATH` muss derselbe Laufkontext ueber Planner, Builder, Critic, Regression und Report hinweg explizit gefuehrt werden.
Der Laufstatus ist logisch ein Single-Writer-Artefakt; derselbe `run_state.json` darf nicht parallel aus veralteten Stage-Staenden fortgeschrieben werden.

### Standardpfad

Verwende fuer laufbezogene Artefakte standardmaessig:

- `server/_debug/agent_runs/<run_id>/`

### Pflichtdatei ab FULL-PATH

Im Artefaktordner muss ein `run_state.json` gefuehrt oder mindestens vorbereitet werden.
Der minimale Inhalt ist:

- `run_id`
- `revision`
- `iteration`
- `path_type`
- `target_case`
- `benchmark_set`
- `artifact_dir`
- `latest_builder_change`
- `latest_artifacts`
- `critic_verdict`
- `critic_scores`
- `failure_classes`
- `regression_summary`
- `open_risks`

Wenn eine Rolle die Datei nicht direkt schreiben kann, muss sie dieselben Felder in ihrer Ausgabe referenzieren, damit der naechste Handoff verlustfrei bleibt.

## LIGHT Mode

`LIGHT` ist kein eigener Agent, sondern ein reduzierter Modus fuer bestehende Rollen.

### Planner in LIGHT mode

- bestaetigt, dass der Domain Impact wirklich gering ist
- nennt nur die relevanten Dateien und Hauptrisiken
- erstellt maximal `3` Schritte
- fuehrt nur einen minimalen Laufkontext
- eskaliert sofort auf `FULL-PATH`, wenn doch Zeichnungslogik, Benchmark-Verhalten oder Agentenfreigabe betroffen sind

### Critic in LIGHT mode

- prueft zuerst, ob `FAST-PATH` ueberhaupt gerechtfertigt war
- darf auf vollstaendiges `35/35`-Scoring nur verzichten, wenn keine Zeichnungslogik und keine Exportartefakte betroffen sind
- eskaliert auf `FULL-PATH`, sobald fachlicher oder visueller Einfluss auf den Output moeglich ist

### Critic in DELTA mode

- wird bei `MEDIUM-PATH` eingesetzt
- bewertet nur die Kriterien, die von der Aenderung direkt betroffen sind
- begruendet, welche Kriterien bewertet und welche uebersprungen werden
- Mindestgrenze: betroffene Kriterien muessen jeweils mindestens `4/5` erreichen
- eskaliert auf `FULL-PATH`, wenn die Aenderung doch breitere Auswirkungen hat

## Pflichtworkflow je Iteration

### FAST-PATH

1. Task sauber klassifizieren.
2. Geringen Domain Impact begruenden.
3. Kleine Aenderung gezielt umsetzen.
4. Relevante technische Pruefung ausfuehren.
5. Durch Critic `LIGHT` bestaetigen oder auf `FULL-PATH` eskalieren.
6. Iteration dokumentieren.

Ein fehlender Render- oder Exportlauf ist nur zulaessig, wenn der geringe Domain Impact explizit begruendet und durch den Critic bestaetigt wurde.

### MEDIUM-PATH

1. Task klassifizieren und begruenden, warum kein `FULL-PATH` noetig ist.
2. Aenderung umsetzen.
3. DSE-Unittests ausfuehren (`64/64`).
4. Baseline-Golden regenerieren (`--update-golden --stability-runs 1`).
5. Regression pruefen (`--stability-runs 1`, `20/20`).
6. Critic in `DELTA` mode: nur betroffene Kriterien bewerten (z.B. nur Kriterium 7 bei Schriftfeld-Aenderung).
7. Iteration dokumentieren.

### FULL-PATH

1. Task klassifizieren und `RUN CONTEXT` anlegen.
2. Bestehende Logik analysieren.
3. Relevante Dateien und Module benennen.
4. Primaeren Testfall und Regression-Set bestimmen.
5. Zeichnung rendern oder exportieren und Artefakte in den Laufkontext legen.
6. Ergebnis fachlich pruefen und Fehlerklassen benennen.
7. Ursache im Code oder in der Regel-Logik nennen.
8. Gezielt verbessern.
9. Neu rendern oder exportieren.
10. Artifact Steward synchronisiert aktuelle Artefakte und `run_state.json`.
11. Regression ueber betroffene Benchmark-Faelle oder Geometrieklassen pruefen.
12. Iteration dokumentieren.

### LONG-RUN

1. Fuehre alle `FULL-PATH`-Schritte aus.
2. Nutze einen persistenten `run_id` ueber alle Iterationen.
3. Fuehre Stabilitaetslaeufe mit mindestens `5` Wiederholungen fuer markierte Faelle aus.
4. Pruefe mindestens Baseline plus betroffene Geometrieklasse und, falls vorhanden, reale Referenzfaelle.
5. Fordere zwei aufeinanderfolgende Critic- und Regression-Freigaben vor Release.
6. Wenn derselbe Fehler erneut auftritt, benenne nicht nur die Root Cause, sondern auch warum die vorige Korrektur unzureichend war.
7. Dokumentiere jede Iteration knapp, aber zustandsbehaftet.

## Pflichtartefakte

### FAST-PATH

- `TASK CLASSIFICATION`
- kurzer Planner-Output im `LIGHT` mode
- Liste der geaenderten Dateien
- relevanter Test- oder Pruefnachweis
- explizite Aussage, warum kein Export oder Renderlauf noetig war
- Critic-Entscheidung im `LIGHT` mode
- Iteration Report

### MEDIUM-PATH

- `TASK CLASSIFICATION`
- Liste der geaenderten Dateien
- DSE-Unittest-Ergebnis
- Baseline-Regression (`20/20`)
- Delta-Scoring (nur betroffene Kriterien)
- Iteration Report

### FULL-PATH

- `TASK CLASSIFICATION`
- `RUN CONTEXT`
- Planner-Output
- Liste der geaenderten Dateien
- exakte Commands
- relevante Tests
- mindestens ein aktueller Export- oder Renderlauf
- `server/_debug/agent_runs/<run_id>/run_state.json`
- aktuelles `*_debug.svg`
- aktuelles `*_preview.png`
- aktuelles `*_report.json`
- Regression ueber betroffene Benchmark-Faelle oder Geometrieklassen
- Critic-Scoring und Entscheidung
- `KB_PROPOSAL`-Bloecke fuer MAJOR/SHOWSTOPPER Failures (Critic, siehe Agent_critic.md Abschnitt 8)
- `PROPOSED KB RULES`-Tabelle im Report (siehe Agent_report.md Abschnitt 8)
- Iteration Report

### LONG-RUN

- alle `FULL-PATH`-Artefakte (inkl. `KB_PROPOSAL` und `PROPOSED KB RULES`)
- persistenter `run_id` ueber alle Iterationen
- mindestens ein Stabilitaetslauf mit `>= 5` Wiederholungen
- Regression ueber `baseline` plus betroffene Geometrieklassen
- reale Referenzfaelle oder explizite Begruendung, warum keine verfuegbar sind
- zwei aufeinanderfolgende Critic- und Regression-Freigaben vor Release
- Iterationsvergleich mit Voriteration im Report
- kumulierte KB-Regelvorschlaege ueber alle Iterationen

## Qualitaetskriterien

Eine Zeichnung muss mindestens diese Kriterien erfuellen:

- Hauptansicht sinnvoll gewaehlt
- Ansichten korrekt und logisch angeordnet
- Blattflaeche sinnvoll genutzt
- Teil ausreichend gross dargestellt
- Bemaessung vollstaendig genug fuer die gezeigte Funktion
- Bemaessung nicht redundant oder chaotisch
- Loecher klar bemaesst
- Masse sinnvoll gewaehlt und an sinnvollen Bezugskanten oder Bezugsmerkmalen angeordnet
- Isometrie vorhanden, aber nachrangig
- Zeichnung wirkt professionell und nicht wie ein roher CAD-Export

## Normbezug

Bewerte im Rahmen des aktuellen MVP normnah und fachlich plausibel.
Unterstelle keine vollstaendige Normabdeckung, wenn diese im System noch nicht implementiert ist.

## Fehlerklassen

- `VIEW_SELECTION_ERROR`
- `VIEW_ALIGNMENT_ERROR`
- `SCALE_LAYOUT_ERROR`
- `DIMENSION_MISSING`
- `DIMENSION_REDUNDANT`
- `DIMENSION_POOR_PLACEMENT`
- `SHEET_SPACE_WASTE`
- `ISOMETRIC_OVEREMPHASIS`
- `HOLE_PATTERN_UNCLEAR`
- `PROJECTION_INCONSISTENT`
- `TITLEBLOCK_INCOMPLETE`
- `GDT_MISSING`
- `SECTION_VIEW_MISSING`
- `ANNOTATION_OVERLAP`
- `CHAMFER_UNLABELED`

## Mangelklassen

- `SHOWSTOPPER`
- `MAJOR`
- `MINOR`

## Bewertung

### Scoring

Der Critic bewertet bei `FULL-PATH` und `LONG-RUN` jede Zeichnung mit `0-5` Punkten je Kriterium:

1. Hauptansicht / View Correctness
2. Ansichtsanordnung / Projection Consistency
3. Blattlayout / Scale Use
4. Massvollstaendigkeit / Dimension Completeness
5. Masslogik und Lochbildklarheit
6. Lesbarkeit sowie Platzierung von Massen, Text und Symbolen
7. Gesamtprofessionalitaet und Fertigungsnutzen

### Mindestgrenze

- Bei `FULL-PATH`: kein Hauptkriterium unter `4/5`
- Bei `FULL-PATH`: Gesamt mindestens `30/35`
- Bei `LONG-RUN`: dieselbe Grenze in zwei aufeinanderfolgenden Freigaben
- Sonst neue Iteration

Im `FAST-PATH` ist ein vollstaendiges Scoring nur dann entbehrlich, wenn der Critic `LIGHT` sauber begruendet, dass keine Zeichnungslogik und kein fachlich relevanter Output betroffen sind.

## Freigaberegeln

- `FAST-PATH` ist nur freigegeben, wenn Critic `LIGHT` bestaetigt, dass kein fachlich relevanter Output betroffen ist.
- `MEDIUM-PATH` ist nur freigegeben, wenn Baseline-Regression `20/20` besteht und die betroffenen Critic-Kriterien jeweils `4/5` erreichen.
- `FULL-PATH` ist nur freigegeben, wenn kein KO-Kriterium greift, jedes Hauptkriterium mindestens `4/5` erreicht, die Summe mindestens `30/35` betraegt und Regression keine fachliche Verschlechterung im Zielbereich zeigt.
- `LONG-RUN` ist nur freigegeben, wenn zwei aufeinanderfolgende Critic- und Regression-Durchlaeufe dieselben Mindestgrenzen halten, die Stabilitaetslaeufe sauber bleiben und kein relevanter Benchmark-Fall degradiert.

## Iterationsregeln

- Maximal `5` Iterationen pro Task, ausser ein `LONG-RUN` wird explizit als offene Serie dokumentiert.
- Wenn derselbe Fehler erneut auftritt: Root Cause benennen.
- Wenn das Ziel nach `5` Iterationen nicht erreicht wird:
  - ehrlich scheitern
  - Ursachenliste schreiben
  - betroffene Module nennen
  - naechste technische Massnahmen vorschlagen

## Rollen und Handoffs

- Planner analysiert die bestehende Logik, initialisiert den Laufkontext und erstellt den Verbesserungsplan.
- Builder setzt nur den naechsten sinnvollen Schritt oder die naechsten eng zusammenhaengenden Schritte um.
- Artifact Steward synchronisiert `run_state.json`, Artefaktpfade, Iterationsvergleich und Command-Evidenz.
- Critic bewertet das Ergebnis streng, fachlich und visuell anhand der aktuellen Artefakte.
- Regression prueft Seiteneffekte auf andere Benchmark-Faelle und bewertet den Release-Risiko-Status.
- Report dokumentiert Iteration, Risiken, Entscheidungen, Laufstatus und den naechsten konkreten Schritt.

Empfohlener Ablauf: `Planner -> Builder -> Critic -> Regression -> Report`

## Rollenbezogene Markdown-Dateien

- `Agent_planner.md`
- `Agent_builder.md`
- `Agent_artifact_steward.md`
- `Agent_critic.md`
- `Agent_regression.md`
- `Agent_report.md`

## Denkweise

Handle wie ein Senior-Konstrukteur und CNC-Fertiger mit hohem Qualitaetsanspruch und gleichzeitig wie ein pragmatischer Softwareentwickler.
Beurteile nicht nur technische Funktion, sondern vor allem die Qualitaet der erzeugten Zeichnung.
