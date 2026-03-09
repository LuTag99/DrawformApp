"""
step_unfold.py — Headless FreeCAD SheetMetal Unfold for STEP files.

Usage:
    <freecad-python> step_unfold.py <input.step> <output.json>

Requires:
    - FreeCAD SheetMetal addon in Mod/SheetMetal (user or system)
    - networkx Python package

Output JSON:
    {
        "ok": true/false,
        "flat_length_mm": ...,
        "flat_width_mm": ...,
        "thickness_mm": ...,
        "bend_count": ...,
        "bend_lines": [ {"x1": ..., "y1": ..., "x2": ..., "y2": ...}, ... ],
        "outline_svg": "<svg>...</svg>",
        "error": null or "message"
    }
"""

import json
import math
import os
import sys
import traceback

# --------------------------------------------------------------------------- #
# FreeCAD bootstrap
# --------------------------------------------------------------------------- #

import FreeCAD as App
import Part
import importOCA          # noqa: F401 — registers STEP importer
try:
    import Import          # noqa: F401
except ImportError:
    pass

# Add SheetMetal addon to path (user Mod dir)
_user_mod = os.path.join(App.getUserAppDataDir(), "Mod", "SheetMetal")
_sys_mod = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Mod", "SheetMetal")
for _p in [_user_mod, _sys_mod]:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def _log(msg):
    sys.stderr.write(f"[unfold] {msg}\n")
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# Core logic
# --------------------------------------------------------------------------- #

def find_largest_planar_face(shape):
    """Return (face_index, face) for the largest planar face in the shape."""
    best_idx, best_area = -1, 0.0
    for i, face in enumerate(shape.Faces):
        surface = getattr(face, "Surface", None)
        if surface is None:
            continue
        if surface.__class__.__name__ != "Plane":
            continue
        area = face.Area
        if area > best_area:
            best_area = area
            best_idx = i
    return best_idx, best_area


def shape_to_2d_svg(shape, normal):
    """Project a 3D shape onto a 2D plane perpendicular to `normal` and return SVG."""
    try:
        # Use TechDraw projection
        import TechDraw
        svg_str = TechDraw.projectToSVG(shape, normal)
        return svg_str
    except Exception:
        pass
    # Fallback: project edges manually
    try:
        edges = shape.Edges
        svg_parts = []
        for edge in edges:
            pts = edge.discretize(Number=20)
            if len(pts) < 2:
                continue
            path_d = f"M {pts[0].x:.3f},{-pts[0].y:.3f}"
            for p in pts[1:]:
                path_d += f" L {p.x:.3f},{-p.y:.3f}"
            svg_parts.append(f'<path d="{path_d}" fill="none" stroke="#000" stroke-width="0.3"/>')
        return "\n".join(svg_parts)
    except Exception:
        return ""


def edges_to_svg_lines(edges):
    """Convert FreeCAD edges to simple line data [{x1,y1,x2,y2}, ...]."""
    lines = []
    for edge in edges:
        try:
            v1, v2 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
            lines.append({
                "x1": round(v1.x, 3),
                "y1": round(v1.y, 3),
                "x2": round(v2.x, 3),
                "y2": round(v2.y, 3),
            })
        except Exception:
            continue
    return lines


def run_unfold(step_path, k_factor=0.40, k_standard="din", dxf_output_path=None):
    """
    Import a STEP file, unfold it using SheetMetal addon, return result dict.
    Optionally export the unfolded shape as DXF if dxf_output_path is given.
    """
    result = {
        "ok": False,
        "flat_length_mm": None,
        "flat_width_mm": None,
        "thickness_mm": None,
        "bend_count": 0,
        "bend_lines": [],
        "outline_svg": "",
        "error": None,
    }

    # 1. Import STEP
    _log(f"Importing: {step_path}")
    doc = App.newDocument("UnfoldDoc")
    Part.insert(step_path, doc.Name)
    doc.recompute()

    # Get the imported shape
    obj = doc.Objects[0] if doc.Objects else None
    if obj is None or not hasattr(obj, "Shape"):
        result["error"] = "No shape found in STEP file"
        return result

    # 2. Refine shape (critical for STEP imports)
    _log("Refining shape...")
    try:
        refined = obj.Shape.removeSplitter()
        # Create a new Part::Feature with the refined shape
        refined_obj = doc.addObject("Part::Feature", "Refined")
        refined_obj.Shape = refined
        doc.recompute()
        work_obj = refined_obj
    except Exception as e:
        _log(f"Refine failed ({e}), using original")
        work_obj = obj

    shape = work_obj.Shape

    # 3. Find largest planar face
    face_idx, face_area = find_largest_planar_face(shape)
    if face_idx < 0:
        result["error"] = "No planar face found"
        return result
    face_name = f"Face{face_idx + 1}"
    _log(f"Base face: {face_name} (area={face_area:.1f}mm²)")

    # 4. Try new unfolder (V2, networkx-based)
    try:
        from SheetMetalNewUnfolder import BendAllowanceCalculator, getUnfold

        bac = BendAllowanceCalculator.from_single_value(k_factor, k_standard)
        sel_face, unfolded_shape, bend_lines_compound, root_normal = getUnfold(
            bac, work_obj, face_name
        )
        _log("V2 unfold succeeded")

        # Normalize unfolded shape to origin (XMin=YMin=0) for consistent SVG coordinates.
        # Without this, the shape might be at arbitrary offset in model space, causing
        # the outline SVG to have unexpected x/y offsets that break the drawing layout.
        bbox = unfolded_shape.BoundBox
        origin_x, origin_y = bbox.XMin, bbox.YMin
        if abs(origin_x) > 0.01 or abs(origin_y) > 0.01:
            norm_shape = unfolded_shape.copy()
            norm_shape.translate(App.Vector(-origin_x, -origin_y, 0))
            unfolded_shape = norm_shape
            _log(f"Normalized shape: offset ({origin_x:.2f}, {origin_y:.2f}) → (0, 0)")
            if bend_lines_compound and hasattr(bend_lines_compound, "Edges"):
                bl_norm = bend_lines_compound.copy()
                bl_norm.translate(App.Vector(-origin_x, -origin_y, 0))
                bend_lines_compound = bl_norm

        # Extract dimensions from normalized shape (sorted: length > width > thickness)
        bbox = unfolded_shape.BoundBox
        dims = sorted([bbox.XLength, bbox.YLength, bbox.ZLength], reverse=True)
        result["flat_length_mm"] = round(dims[0], 2)   # largest = unfolded length
        result["flat_width_mm"] = round(dims[1], 2)     # second  = unfolded width
        result["thickness_mm"] = round(dims[2], 3) if dims[2] > 0.01 else None

        # Bend lines (keep as fallback data)
        if bend_lines_compound and hasattr(bend_lines_compound, "Edges"):
            result["bend_lines"] = edges_to_svg_lines(bend_lines_compound.Edges)
            result["bend_count"] = len(bend_lines_compound.Edges)
        else:
            result["bend_count"] = 0

        # Generate outline SVG with embedded (styled) bend lines.
        # Both outline and bend lines are projected through the same TechDraw call,
        # so they share the exact same SVG coordinate system — no offset mismatch.
        try:
            import TechDraw
            svg_raw = TechDraw.projectToSVG(unfolded_shape, root_normal)
            # Embed bend lines as styled SVG elements in the same coordinate space
            if bend_lines_compound and hasattr(bend_lines_compound, "Edges") and result["bend_count"] > 0:
                try:
                    bend_svg = TechDraw.projectToSVG(bend_lines_compound, root_normal)
                    svg_raw += (
                        '\n<g stroke="rgb(40,40,160)" stroke-width="0.35" '
                        'stroke-dasharray="2.5,1.0" fill="none" class="bend-lines">'
                        + bend_svg
                        + "</g>"
                    )
                    _log(f"Embedded {result['bend_count']} bend lines in outline SVG")
                except Exception as be:
                    _log(f"Bend line SVG embed failed: {be} — using separate bend_lines array")
            result["outline_svg"] = svg_raw
        except Exception as e:
            _log(f"SVG projection failed: {e}")
            result["outline_svg"] = shape_to_2d_svg(unfolded_shape, root_normal)

        result["ok"] = True
        _log(f"Result: {result['flat_length_mm']}x{result['flat_width_mm']}mm, "
             f"{result['bend_count']} bends")

        # Optional DXF export of the unfolded shape
        if dxf_output_path:
            try:
                import importDXF
                doc = App.ActiveDocument or App.newDocument("DXFExport")
                outline_obj = doc.addObject("Part::Feature", "Outline")
                outline_obj.Shape = unfolded_shape
                objs = [outline_obj]
                if bend_lines_compound and hasattr(bend_lines_compound, "Edges") and result["bend_count"] > 0:
                    bl_obj = doc.addObject("Part::Feature", "BendLines")
                    bl_obj.Shape = bend_lines_compound
                    objs.append(bl_obj)
                doc.recompute()
                importDXF.export(objs, str(dxf_output_path))
                result["dxf_exported"] = True
                _log(f"DXF exported: {dxf_output_path}")
            except Exception as dxf_err:
                result["dxf_exported"] = False
                result["dxf_error"] = str(dxf_err)
                _log(f"DXF export failed: {dxf_err}")

    except ImportError:
        result["error"] = "SheetMetal addon or networkx not available"
        _log(result["error"])

    except Exception as e:
        # 5. Fallback: try old unfolder
        _log(f"V2 unfold failed: {e}")
        try:
            import SheetMetalUnfolder
            k_dict = {1.0: k_factor}
            tree = SheetMetalUnfolder.SMBendWall(shape, face_idx, k_dict, work_obj)
            tree.buildBendTree()
            _log("Old unfolder tree built")
            # The old unfolder modifies the tree in place; extract what we can
            result["error"] = f"V2 failed ({e}); old unfolder partial"
        except Exception as e2:
            result["error"] = f"Both unfolders failed: V2={e}, Old={e2}"
            _log(result["error"])

    # Cleanup
    try:
        App.closeDocument(doc.Name)
    except Exception:
        pass

    return result


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.step> <output.json> [output.dxf]", file=sys.stderr)
        sys.exit(1)

    step_path = os.path.abspath(sys.argv[1])
    out_path = os.path.abspath(sys.argv[2])
    dxf_path = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else None

    # Optional K-factor from env
    k_factor = float(os.environ.get("DRAWFORM_K_FACTOR", "0.40"))
    k_standard = os.environ.get("DRAWFORM_K_STANDARD", "din")

    try:
        result = run_unfold(step_path, k_factor=k_factor, k_standard=k_standard,
                            dxf_output_path=dxf_path)
    except Exception:
        result = {
            "ok": False,
            "error": traceback.format_exc(),
            "flat_length_mm": None,
            "flat_width_mm": None,
            "thickness_mm": None,
            "bend_count": 0,
            "bend_lines": [],
            "outline_svg": "",
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    _log(f"Written: {out_path}")
    sys.exit(0 if result.get("ok") else 1)
