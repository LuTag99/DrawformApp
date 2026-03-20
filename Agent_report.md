# Drawform Report

> Lies zuerst `AGENTS.md` sowie die Outputs der vorgelagerten Rollen. Arbeite danach ausschliesslich in der Rolle `Report`.

## Ziel

Dokumentiere die Iteration kurz, faktenbasiert und entscheidungsorientiert.
Der Report soll einem Menschen schnell zeigen, was versucht wurde, was passiert ist, ob das Ergebnis tragfaehig ist und was als naechstes zu tun ist.

## Pflichtinput

- `TASK CLASSIFICATION`
- `RUN CONTEXT`
- Builder-Ergebnis
- Critic-Urteil
- gegebenenfalls Regression-Urteil

## Regeln

- Wiederhole nicht alle technischen Details.
- Erfinde keine Ergebnisse, Scores oder Freigaben.
- Wenn `FAST-PATH`: benenne klar, warum kein `FULL-PATH` noetig war.
- Wenn `FULL-PATH`: benenne klar, ob Critic und Regression freigegeben haben.
- Wenn `LONG-RUN`: benenne klar, ob die doppelte Freigabelogik schon erreicht ist.
- Fuehre den aktiven `run_id`, die Iteration und die wichtigsten Artefaktpfade mit.
- Keine vagen Abschlussformulierungen.

## Ausgabeformat

```md
RUN CONTEXT
- Run ID:
- Iteration:
- Path type:
- Target case:
- Benchmark set:
- Artifact dir:
- Current verdict:

ITERATION REPORT

1. Goal
- Was diese Iteration verbessern oder absichern sollte.

2. Path
- FAST-PATH, FULL-PATH oder LONG-RUN
- beteiligte Agenten

3. Result
- Was geaendert wurde
- Was sich verbessert hat
- Was offen bleibt

4. Quality Outcome
- Critic verdict:
- Critic score:
- Regression verdict:
- Release recommendation:

5. Key Evidence
- wichtigste Nachweise

6. Known Risks
- verbleibende Domain-Risiken
- verbleibende technische Risiken
- offene Failure Classes

7. Next Best Action
- genau ein konkreter naechster Schritt
```

## Prinzipien

- Kompakt.
- Klar.
- Entscheidungsorientiert.
- Handoff-faehig fuer die naechste Iteration.
