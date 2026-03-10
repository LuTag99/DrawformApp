# Musterzeichnungen als Lerninhalt

Dieser Ordner haelt die hochgeladenen Musterzeichnungen als wiederverwendbaren
Lern- und Bewertungsbestand fest.

## Zweck

- reale STEP/PDF-Paare nicht nur als Samples, sondern als Referenzbasis nutzen
- Layout-, Bemaessungs- und Normabweichungen systematisch dokumentieren
- Planner/Builder/Critic-Iterationen auf reale Musterteile stuetzen
- spaeter die Knowledge Base und die Quality Gates mit echten Referenzmustern verdrahten

## Bestand

- `reference_drawings_index.json`
  - maschinenlesbarer Index aller realen STEP/PDF-Paare
  - enthaelt STEP-Featurekurzfassung, Referenz-PDF-Metriken, generierte PDF-Metriken und Vergleichsflags
- `reference_drawings_summary.md`
  - lesbare Kurzfassung fuer Reviews und Priorisierung

## Aktualisierung

Der Bestand wird neu gebaut mit:

```bash
python server/build_reference_learning.py --refresh-exports
```

Optional fuer visuelle Kontaktboegen:

```bash
python server/build_reference_learning.py --refresh-exports --render-contact-sheets
```

Die Kontaktboegen liegen dann in `server/_debug/reference_learning`.

## Wichtige Einordnung

Diese Musterzeichnungen sind `tier_2`-naher interner Lerninhalt im Sinn von
`server/knowledge/QUALITY_GUIDE.md`.

Sie sind bewusst mehr als Testdaten:

- Sie zeigen, wie reale freigegebene oder als gut betrachtete Zeichnungen aussehen.
- Sie bilden eine Referenz fuer Blattnutzung, Ansichtslogik, Massdichte und Titelblockstruktur.
- Sie ersetzen trotzdem keine fachliche Endbewertung durch einen Konstrukteur.

## Naechster Anschluss

Die hier abgelegten Muster sollten als Input fuer folgende naechste Schritte dienen:

1. Featuregruppen aus den STEP-Modellen ableiten
2. `dimension_plan` auf reale Musterlogik heben
3. Renderer gegen diese Referenzteile regressionsfaehig machen
4. Quality Gates mit harten Grenzwerten aus dem Referenzkorpus erweitern
