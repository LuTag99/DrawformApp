# Semester 4 — Entwicklungsroadmap DrawformApp

Stand: Feb 2026 | Basis: 20/20 Baseline-Tests bestehen, FreeCAD SheetMetal Unfold integriert

---

## 0. Kritische Stack-Bewertung: Foto → STEP Pipeline

### Was funktioniert — warum

**COLMAP (SfM)** ✅ behalten
- Einzige Open-Source SfM-Lösung mit stabilem Python-API (`pycolmap`), CPU-only möglich
- CPU-only für ~50 Bilder: ca. 20–60 Min. — akzeptabel für Demo, zu langsam für Produktion
- **Empfehlung:** Lokal CPU-only entwickeln, RunPod GPU für Produktion

**OpenMVS (Dense Reconstruction)** ✅ behalten
- Direkt-Integration mit COLMAP-Output (kein Konvertierungsschritt)
- Bessere Mesh-Qualität als COLMAP-eigenes MVS
- Memory: ~2–4 GB RAM für moderate Qualität — kein Problem

**Open3D (Mesh-Cleanup + Poisson-Rekonstruktion)** ✅ behalten, mit Einschränkung
- Schneller als PyMeshLab, einfaches API
- Poisson-Rekonstruktion: gut für organische Formen, akzeptabel für Bauteile
- **PyMeshLab als Ergänzung** nur wenn spezielle Filter gebraucht werden

**Meshroom** ❌ ersetzen durch COLMAP + OpenMVS
- Fokus auf GUI, schlecht automatisierbar
- Keine Python-API

**FreeCAD Python für STL→STEP** ⚠️ mit stark angepasster Erwartungshaltung
- FreeCAD kann STL **nicht parametrisch** konvertieren — nur tessellierter Solid (Mesh-Wrapper)
- Ergebnis: importierbar in SolidWorks/FreeCAD, aber **keine Features** (Bohrungen, Verrundungen bleiben Dreiecke)
- Das ist für "Prototypen und einfache Bauteile reichen" ausreichend — aber Nutzer müssen das **explizit sehen**
- **Falle:** Wenn du das nicht kommunizierst, werden Nutzer enttäuscht sein

**Google Colab** ❌ für Produktion
- Sessions laufen ab, kein persistenter API-Endpunkt
- Nur für initiale Entwicklertests akzeptabel

**RunPod Serverless** ✅ für GPU-Burst
- Cold Start: 10–30 Sek. — damit asynchrone Architektur von Tag 1 nötig
- Kosten: ~$0.20–0.50/GPU-h — überschaubar für niedrige Nutzerzahl
- **Python SDK verfügbar**

**FastAPI BackgroundTasks** ❌ für GPU-Jobs (>5 Min.)
- Gehen bei Server-Restart verloren
- Kein Retry, kein Job-State nach Neustart
- **Ersatz:** Celery + Redis (aber erst wenn nötig — s. Stufenplan)

**Apple OAuth** ⚠️ hinten anstellen
- 2–3 Wochen Entwicklungsaufwand (private email relay, JWT validation, Developer Account)
- Für Semester 4 weglassen — hat kaum Einfluss auf Zielgruppe (Ingenieure nutzen überwiegend Google/Microsoft)

---

## 1. Warum diese Reihenfolge

```
Zeichnungsqualität jetzt → CI härten → Docker → Auth → Foto-Pipeline → Deployment
```

**Begründung:**

1. **Zeichnungsqualität zuerst:** Bugs die aktuellen Nutzern heute auffallen, kosten Vertrauen. Neue Features helfen nichts wenn die Basis wackelt.

2. **CI vor Auth/Docker:** Der GitHub Workflow existiert schon (`quality-gate.yml`) — er läuft aber mit Chocolatey-FreeCAD ohne SheetMetal-Addon. Solange CI auf main grün ist, arbeite ich sicher. SheetMetal-Unfold scheitert in CI graceful (Fallback auf mathematische Berechnung), also kein unmittelbares Problem — aber das muss dokumentiert sein.

3. **Docker vor Foto-Pipeline:** COLMAP + OpenMVS in einer reproduzierbaren Container-Umgebung aufzusetzen ist zeitaufwändiger als gedacht (Xvfb für FreeCAD, CUDA-Image für COLMAP). Frühzeitig angehen, nicht am Ende.

4. **Auth vor Multi-User-Features:** Ohne Auth kann kein Feature pro Nutzer gespeichert werden. Aber Auth-Implementierung ist weitgehend unabhängig von der Zeichnungslogik — paralleler Strang möglich.

5. **Foto-Pipeline zuletzt:** Sie hat die meisten Unbekannten. Alles andere muss stehen bevor die Pipeline live geht.

---

## 2. Semesterplan (4 Monate, ~16 Wochen)

### Monat 1 (KW 1–4): Zeichnungsqualität + CI-Absicherung

**Ziel:** Keine bekannten Bugs mehr in der Drawing-Pipeline. CI läuft zuverlässig.

| Woche | Aufgabe | Warum |
|-------|---------|-------|
| 1 | Maßlinien-Alignment: Extension Lines enden genau an View-Kanten | Aktuell sichtbares Problem in PDFs; ISO 129-1 konformität |
| 2 | Mittellinien ISO 128-2: echte Strich-Punkt-Linie für Bohrungsachsen | Bisher nur gestrichelt, nicht normkonform |
| 3 | Abwicklungs-SVG normalisieren: `transform="scale(1,-1)"` aus FreeCAD-Output entfernen, Koordinaten direkt umrechnen | SVG-Koordinaten müssen konsistent sein |
| 4 | GitHub CI: `SheetMetal addon fehlt in CI` dokumentieren + Test-Skip oder CI-Step zum Addon-Download | CI grün halten auch mit Unfold-Feature |

**Meilenstein M1:** `python test_views.py --sample-set baseline` → 20/20. CI auf main grün. PDFs sehen professionell aus (Abnahme durch Sichtprüfung).

---

### Monat 2 (KW 5–8): Docker + Authentifizierung

**Ziel:** Backend containerisiert, Google + Microsoft OAuth funktionieren.

| Woche | Aufgabe | Warum |
|-------|---------|-------|
| 5 | Dockerfile für FastAPI Backend (Python 3.12 + FreeCAD + Xvfb) | Grundlage für Deployment + GPU-Container |
| 5 | docker-compose: Backend + Redis + PostgreSQL | Redis wird für Celery gebraucht, Postgres für User-Model |
| 6 | Datenbankmodell: User, Project, Export (SQLAlchemy async + Alembic) | Persistenz für Auth und Dateihistorie |
| 7 | Google OAuth + Microsoft OAuth via `authlib` + JWT | Login für reale Nutzung |
| 8 | Frontend AuthProvider verdrahten (localStorage → echtes JWT) | AuthProvider existiert als Stub |

**Falle:** FreeCAD 1.0 in einem offiziellen Debian/Ubuntu Container einzurichten ist ungetestet. Frühzeitig prüfen ob `freecadcmd` ohne GUI + Xvfb funktioniert. Falls nicht: eigenes Dockerfile mit `RUN apt-get install xvfb && freecadcmd` + `xvfb-run` Wrapper.

**Meilenstein M2:** `docker-compose up` → Backend läuft, Login mit Google funktioniert, erste PDF-Export über localhost:3000.

---

### Monat 3 (KW 9–12): Foto → STL Pipeline

**Ziel:** Nutzer lädt 30–50 Fotos hoch, bekommt STL zurück.

| Woche | Aufgabe | Warum |
|-------|---------|-------|
| 9 | COLMAP Proof-of-Concept: 10 Test-Bilder lokal, CPU-only | Machbarkeit validieren bevor Architektur baut |
| 9 | pycolmap installieren, Skript schreiben: `images/ → sparse_cloud/ → dense_cloud/` | |
| 10 | Open3D Pipeline: `dense_cloud → poisson_mesh → cleaned_mesh.stl` | |
| 10 | Job-Architektur: FastAPI `POST /api/reconstruct` → BackgroundTask → Job-State in Redis | Async weil 10–60 Min. Laufzeit |
| 11 | Frontend: Foto-Upload UI, Job-Status-Polling (`GET /api/reconstruct/{id}`) | |
| 12 | RunPod Integration: COLMAP-Job auf GPU-VM auslagern wenn verfügbar | Für akzeptable Demo-Performance |

**Warum BackgroundTasks jetzt statt Celery?**
BackgroundTasks reichen für Einzelnutzer-Demo (Semester 4). Bei Server-Restart verliert man den Job — das ist für Showcase akzeptabel. Celery später einführen wenn wirkliche Nutzer kommen.

**Falle:** Foto-Qualität ist kritisch. Nutzer müssen verstehen: gleichmäßige Beleuchtung, 60–80% Bild-Überlappung, keine spiegelnden Oberflächen. Ohne Guidance wird die Qualität immer enttäuschend. → Foto-Checkliste im UI einbauen.

**Meilenstein M3:** Test-Objekt (kleines Metallteil, mattiert) → 40 Fotos vom Handy → STL herunterladbar. Laufzeit < 30 Min. auf RunPod GPU.

---

### Monat 4 (KW 13–16): STL→STEP + PWA + Deployment

**Ziel:** Vollständige Pipeline, deployed, PWA-fähig.

| Woche | Aufgabe | Warum |
|-------|---------|-------|
| 13 | FreeCAD STL→STEP Konvertierung (tessellierter Solid) | Ausgabe die in CAD importierbar ist |
| 13 | UI: Erwartungshinweis "STEP enthält tessellierte Oberfläche — keine parametrischen Features" | Muss klar kommuniziert werden |
| 14 | PWA: `manifest.json` + Service Worker (Vite PWA Plugin) | Installierbar auf Windows + Mobile |
| 14 | Gewindeannotation: Kernlöcher → `M5`, `M6`, `M8` Annotation in Zeichnung | Kernlöcher bereits erkannt |
| 15 | Deployment: Plesk/VPS + Docker, HTTPS, Reverse Proxy | |
| 16 | Puffer: Bugfixes, Abnahmetests, Dokumentation aktualisieren | |

**Meilenstein M4:** Foto → STL → STEP → Zeichnung, öffentlich erreichbar unter HTTPS, Google Login funktioniert.

---

## 3. Konkrete Startpunkte

### Woche 1: Maßlinien-Alignment (heute anfangen)

```python
# server/freecad/step_to_pdf.py
# Dimension-Extension-Lines: aktuell wird der Start vom Label-Offset berechnet
# Fix: Extension Line beginnt genau an der Bounding-Box-Kante der View
# Suche: build_dimension_line(), draw_dimension(), add_dimension_svg()
```

**Werkzeuge:** Grep nach `extension_line`, `dim_line`, `leader` in `step_to_pdf.py`.

### Woche 5: Docker-Grundgerüst

```dockerfile
# Basis: python:3.12-slim + FreeCAD AppImage oder apt-based install
# Xvfb wrapper nötig für FreeCAD PDF-Export
FROM python:3.12-slim
RUN apt-get update && apt-get install -y xvfb libgl1 libglib2.0-0
# FreeCAD als AppImage oder via PPA
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Woche 9: COLMAP Proof-of-Concept

```python
# pip install pycolmap open3d
import pycolmap
from pathlib import Path

def run_sfm(image_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "database.db"
    pycolmap.extract_features(database_path, image_dir)
    pycolmap.match_exhaustive(database_path)
    maps = pycolmap.incremental_mapping(database_path, image_dir, output_dir)
    return maps  # sparse reconstruction
```

### Woche 7: Auth-Grundgerüst

```python
# server/auth.py
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends

oauth = OAuth()
oauth.register("google", client_id=..., client_secret=..., ...)
oauth.register("microsoft", client_id=..., ...)

# User-Model (SQLAlchemy):
class User(Base):
    __tablename__ = "users"
    id = Column(UUID, primary_key=True)
    email = Column(String, unique=True)
    provider = Column(String)  # "google" | "microsoft"
    created_at = Column(DateTime)
```

---

## 4. Fallen — bevor du sie machst

### Falle 1: STL→STEP Erwartungsmanagement
**Problem:** Nutzer erwarten parametrisches STEP (wie SolidWorks Reverse Engineering). Sie bekommen tessellierte Oberflächen (Dreiecke).
**Lösung:** Im UI explizit anzeigen: *"STEP-Datei enthält tessellierte Oberfläche. Features (Bohrungen, Radien) wurden nicht rekonstruiert. Für Fertigungszeichnungen Modell in CAD nacharbeiten."*

### Falle 2: FreeCAD in Docker — früh testen
**Problem:** FreeCAD PDF-Export benötigt intern Display-Kontext (Cairo, Qt-internals). In Docker ohne Xvfb schlägt PDF-Export stumm fehl.
**Lösung:** Im Dockerfile `xvfb-run freecadcmd ...` als Wrapper. Das muss in Woche 5 getestet werden — nicht erst in Woche 15 bei Deployment.

### Falle 3: COLMAP Cold-Start auf RunPod
**Problem:** 10–30 Sek. Cold-Start auf RunPod + 10–60 Min. Berechnung = Nutzer wartet sehr lange.
**Lösung:** Asynchrones Job-Pattern von Anfang an. Kein synchroner API-Call. Polling-UI mit Fortschrittsanzeige. Nutzer muss nicht vor dem Bildschirm warten.

### Falle 4: Foto-Qualität — Nutzer-Guidance fehlt
**Problem:** Spiegelnde Oberflächen, ungleichmäßige Beleuchtung, zu wenig Overlap → COLMAP findet keine Features → leeres Ergebnis.
**Lösung:** Foto-Upload-UI enthält Checkliste: mattierte Oberfläche, Tageslicht, 40–80% Bildüberlappung, rundum fotografieren. Evtl. Kalibrierungsobjekt (Schachbrettmuster) mitfotografieren.

### Falle 5: Apple OAuth
**Problem:** Apple Sign-In erfordert Apple Developer Account ($99/Jahr), private email relay, JWT mit Apple's eigenem Public Key, separate Bundle-IDs per App. Dokumentation ist komplex.
**Lösung:** Für Semester 4 weglassen. Google + Microsoft reichen für Ingenieure.

### Falle 6: CI + SheetMetal Addon
**Problem:** `quality-gate.yml` installiert FreeCAD via Chocolatey, aber nicht das SheetMetal-Addon. Die `step_unfold.py`-Integration schlägt in CI fehl — scheitert aber graceful (Fallback auf math). Solange unklar ob CI wirklich grün ist.
**Lösung:** In CI entweder den SheetMetal-Addon-Download als Step hinzufügen, oder den Unfold-Test explizit als "expected fallback" markieren.

### Falle 7: Celery zu früh einführen
**Problem:** Celery + Redis + Flower + Worker-Management ist signifikant komplexer als BackgroundTasks.
**Lösung:** Mit FastAPI BackgroundTasks + Redis als Job-Store starten. Nur auf Celery migrieren wenn BackgroundTasks tatsächlich ein Problem werden (Server-Restart verliert Jobs — für Showcase akzeptabel).

---

## 5. Technologie-Entscheidungen (Zusammenfassung)

| Bereich | Wahl | Begründung |
|---------|------|------------|
| SfM | `pycolmap` | Einzige stabile Python-API, headless, CPU+GPU |
| Dense Reconstruction | OpenMVS | Beste Qualität mit COLMAP-Output |
| Mesh-Cleanup | `open3d` | Einfach, schnell, ausreichend |
| STL→STEP | FreeCAD Python | Tesselliert — kommunizieren! |
| Auth | `authlib` + SQLAlchemy | Stabil, FastAPI-native |
| OAuth Provider | Google + Microsoft | Apple weglassen |
| Session | JWT (stateless) | Skalierbar, Docker-freundlich |
| Job-Queue | FastAPI BackgroundTasks + Redis Job-Store | Einfach für Semester 4; Celery später |
| GPU Hosting | RunPod Serverless | Kosten-effizient für niedrige Last |
| Container | Docker + docker-compose | Standard |
| Frontend PWA | Vite PWA Plugin | Minimaler Aufwand auf bestehendem Stack |

---

## 6. Was NICHT dieses Semester

- **G-Code / CAM:** Das ist ein eigenes 6-Monats-Projekt. Nicht anschneiden.
- **Vollständiges GD&T:** Zu komplex, kein klarer Nutzen für Semester 4.
- **Parametrische STL→STEP Konvertierung:** Noch ein Forschungsproblem (keine Open-Source-Lösung).
- **Apple OAuth:** 2–3 Wochen für 5% der Nutzer.
- **Vollständiges Celery-Stack:** Overkill für Semester 4.
