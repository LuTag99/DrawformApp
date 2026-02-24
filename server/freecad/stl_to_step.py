"""
stl_to_step.py — Headless FreeCAD: STL → tesselliertes STEP.

Usage:
    <freecad-python> stl_to_step.py <input.stl> <output.step>

Wichtiger Hinweis:
    Das erzeugte STEP enthält einen TESSELLIERTEN Solid (Shell aus Dreiecken),
    KEINE parametrischen CAD-Features (Bohrungen, Radien bleiben Dreiecke).
    Geeignet für: Import in CAD als Referenz, grobe Maßüberprüfung.
"""

import json
import os
import sys
import traceback

import FreeCAD as App
import Part
import Mesh


def _log(msg: str):
    sys.stderr.write(f"[stl_to_step] {msg}\n")
    sys.stderr.flush()


def run_stl_to_step(stl_path: str, step_path: str, tolerance_mm: float = 0.1) -> dict:
    """
    Konvertiert STL → STEP (tesselliert).

    tolerance_mm: Sewing-Toleranz für makeShapeFromMesh (0.05–0.5mm typisch).
    Gibt {"ok": True/False, "error": None/"..."} zurück.
    """
    result = {"ok": False, "error": None}

    _log(f"Lade STL: {stl_path}")
    doc = App.newDocument("STL2STEP")

    try:
        # STL importieren
        Mesh.insert(stl_path, doc.Name)
        doc.recompute()

        mesh_objs = [o for o in doc.Objects if hasattr(o, "Mesh")]
        if not mesh_objs:
            result["error"] = "Kein Mesh-Objekt im STL gefunden"
            return result

        mesh_obj = mesh_objs[0]
        _log(f"Mesh: {mesh_obj.Mesh.CountPoints} Punkte, {mesh_obj.Mesh.CountFacets} Dreiecke")

        # Mesh → Part-Shape (tessellierter Solid)
        shape = Part.Shape()
        shape.makeShapeFromMesh(mesh_obj.Mesh.Topology, tolerance_mm)

        # Shell zu Solid machen (für sauberen STEP-Export)
        try:
            solid = Part.makeSolid(shape)
        except Exception as e:
            _log(f"makeSolid fehlgeschlagen ({e}), verwende Shell")
            solid = shape

        # STEP exportieren
        _log(f"Exportiere STEP: {step_path}")
        solid.exportStep(step_path)

        if not os.path.exists(step_path):
            result["error"] = "STEP-Datei wurde nicht erstellt"
            return result

        result["ok"] = True
        _log("Fertig.")

    except Exception as e:
        result["error"] = traceback.format_exc()
        _log(f"Fehler: {e}")

    finally:
        try:
            App.closeDocument(doc.Name)
        except Exception:
            pass

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Verwendung: {sys.argv[0]} <input.stl> <output.step>", file=sys.stderr)
        sys.exit(1)

    stl_in = os.path.abspath(sys.argv[1])
    step_out = os.path.abspath(sys.argv[2])
    tol = float(os.environ.get("DRAWFORM_STL_TOLERANCE", "0.1"))

    try:
        res = run_stl_to_step(stl_in, step_out, tolerance_mm=tol)
    except Exception:
        res = {"ok": False, "error": traceback.format_exc()}

    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)
