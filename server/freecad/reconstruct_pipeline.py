"""
reconstruct_pipeline.py — Voxel-Carving 3D-Rekonstruktion aus 5 orthogonalen Fotos.

Eingabe:
    5 Bilder: front, top, left, right, back  (JPEG/PNG)
    Bauteil-Dimensionen in mm: width, height, depth
    Auflösung: voxel_res (Standard 128 → 128³ Voxel, ~10-30s CPU)

Algorithmus:
    1. Hintergrund entfernen → binäre Silhouette (OpenCV GrabCut)
    2. Voxelgitter (alle Voxel = 1/gefüllt) initialisieren
    3. Pro Ansicht: Silhouette auf entsprechende Achse projizieren
       → alle Voxel außerhalb der Silhouette auf 0 setzen (carven)
    4. Marching Cubes → Dreiecksnetz
    5. Mesh bereinigen (trimesh) + als STL schreiben

Achsen-Konvention:
    Koordinatensystem (x=Breite, y=Höhe, z=Tiefe):
    - front  → Projektion auf XY-Ebene (entlang +Z)
    - back   → Projektion auf XY-Ebene (entlang -Z, gespiegelt X)
    - top    → Projektion auf XZ-Ebene (entlang +Y)
    - left   → Projektion auf YZ-Ebene (entlang -X, gespiegelt Z)
    - right  → Projektion auf YZ-Ebene (entlang +X)
"""

import json
import os
import sys
import traceback

import cv2
import numpy as np
from skimage.measure import marching_cubes
import trimesh


# --------------------------------------------------------------------------- #
# Hintergrundentfernung
# --------------------------------------------------------------------------- #

def extract_silhouette(img_path: str, target_size: int) -> np.ndarray:
    """
    Gibt binäre Maske (H × W, uint8: 0=Hintergrund, 1=Objekt) zurück.
    Verwendet OpenCV GrabCut mit breitem Randprior.
    Voraussetzung: gleichmäßiger, kontrastierender Hintergrund.
    """
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError(f"Bild nicht lesbar: {img_path}")

    h, w = img.shape[:2]

    # GrabCut benötigt Mindestgröße
    min_side = min(h, w)
    if min_side < 64:
        raise ValueError(f"Bild zu klein ({w}×{h}): mindestens 64px benötigt")

    # Rand-Prior: Bauteil ist mittig, Ränder sind Hintergrund
    margin = max(10, min(h, w) // 20)
    rect = (margin, margin, w - 2 * margin, h - 2 * margin)

    mask = np.zeros((h, w), np.uint8)
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(img, mask, rect, bg_model, fg_model, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error as e:
        # Fallback: einfache Threshold-Methode bei GrabCut-Fehler
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = (binary > 0).astype(np.uint8)
        return cv2.resize(binary, (target_size, target_size), interpolation=cv2.INTER_NEAREST)

    # GrabCut-Maske: 0=sicher BG, 1=sicher FG, 2=wohl BG, 3=wohl FG
    binary = np.where((mask == 1) | (mask == 3), 1, 0).astype(np.uint8)

    # Morphologische Bereinigung: kleine Lücken schließen, Rauschen entfernen
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # Auf Zielgröße skalieren (quadratisch)
    return cv2.resize(binary, (target_size, target_size), interpolation=cv2.INTER_NEAREST)


# --------------------------------------------------------------------------- #
# Voxel-Carving
# --------------------------------------------------------------------------- #

def voxel_carve(silhouettes: dict, voxel_res: int) -> np.ndarray:
    """
    Erstellt 3D-Voxelgitter (voxel_res³) durch Voxel-Carving.
    silhouettes: Dict mit Keys 'front','back','top','left','right'
                 → je ndarray (voxel_res × voxel_res, uint8: 0/1)
    Gibt bool-Array (X × Y × Z) zurück: True = gefüllt.

    Achsen: grid[x, y, z]
        x = Breite (0..res-1)
        y = Höhe   (0..res-1, oben=res-1)
        z = Tiefe  (0..res-1, vorne=0)
    """
    grid = np.ones((voxel_res, voxel_res, voxel_res), dtype=bool)

    def _carve_xy(sil: np.ndarray, flip_x: bool = False):
        """Front/Back: Silhouette in XY, für alle Z-Schichten anwenden."""
        s = sil.copy()
        if flip_x:
            s = np.fliplr(s)
        # sil[row, col] → row=y (unten=0 im Bild=oben im Modell), col=x
        # Bild-Y ist invertiert (Pixel 0 = oben, Modell-Y 0 = unten)
        s_flipped = np.flipud(s)  # jetzt s_flipped[y, x]
        for z in range(voxel_res):
            grid[:, :, z] &= s_flipped.T  # Transponieren: s_flipped[y,x] → grid[x,y]

    def _carve_xz(sil: np.ndarray, flip_x: bool = False):
        """Top: Silhouette in XZ (von oben), für alle Y-Schichten anwenden."""
        s = sil.copy()
        if flip_x:
            s = np.fliplr(s)
        # sil[row, col] → row=z (hinten=0 im Draufsicht=vorne im Modell), col=x
        for y in range(voxel_res):
            grid[:, y, :] &= s.T  # s[z, x] → grid[x, z]

    def _carve_yz(sil: np.ndarray, flip_z: bool = False):
        """Left/Right: Silhouette in YZ, für alle X-Schichten anwenden."""
        s = sil.copy()
        if flip_z:
            s = np.fliplr(s)
        s_flipped = np.flipud(s)  # Bild-Y invertiert
        for x in range(voxel_res):
            grid[x, :, :] &= s_flipped  # s_flipped[y, z] → grid[x, y, z]

    if "front" in silhouettes:
        _carve_xy(silhouettes["front"], flip_x=False)
    if "back" in silhouettes:
        _carve_xy(silhouettes["back"], flip_x=True)
    if "top" in silhouettes:
        _carve_xz(silhouettes["top"], flip_x=False)
    if "left" in silhouettes:
        _carve_yz(silhouettes["left"], flip_z=True)
    if "right" in silhouettes:
        _carve_yz(silhouettes["right"], flip_z=False)

    return grid


# --------------------------------------------------------------------------- #
# Mesh-Generierung und Export
# --------------------------------------------------------------------------- #

def grid_to_stl(
    grid: np.ndarray,
    dimensions_mm: tuple,
    output_stl: str,
    target_triangles: int = 8000,
) -> dict:
    """
    Marching Cubes auf Voxelgitter → Mesh → Skalieren → STL schreiben.
    Gibt {'vertex_count': int, 'triangle_count': int} zurück.
    """
    # Marching Cubes: voxel_res³ float-Array nötig
    volume = grid.astype(np.float32)
    verts, faces, normals, _ = marching_cubes(volume, level=0.5, spacing=(1.0, 1.0, 1.0))

    if len(verts) == 0:
        raise ValueError("Marching Cubes hat kein Mesh erzeugt — Silhouetten zu klein oder leer?")

    # Koordinaten skalieren: Voxel-Einheiten → mm
    voxel_res = grid.shape[0]
    wx, wy, wz = dimensions_mm
    verts[:, 0] *= wx / voxel_res
    verts[:, 1] *= wy / voxel_res
    verts[:, 2] *= wz / voxel_res

    # Mesh mit trimesh bereinigen
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh.remove_duplicate_faces()
    mesh.remove_degenerate_faces()

    # Vereinfachen wenn zu viele Dreiecke
    if len(mesh.faces) > target_triangles * 2:
        mesh = mesh.simplify_quadric_decimation(target_triangles)

    # Normalen neu berechnen
    mesh.fix_normals()

    mesh.export(output_stl)

    return {
        "vertex_count": len(mesh.vertices),
        "triangle_count": len(mesh.faces),
    }


# --------------------------------------------------------------------------- #
# Haupt-Pipeline
# --------------------------------------------------------------------------- #

def run_reconstruction(
    image_paths: dict,
    dimensions_mm: tuple,
    output_stl: str,
    voxel_res: int = 128,
) -> dict:
    """
    Vollständige Rekonstruktions-Pipeline.

    image_paths: {'front': str, 'top': str, ...}  — mindestens 'front' nötig
    dimensions_mm: (width_mm, height_mm, depth_mm)
    output_stl: Ausgabepfad für STL-Datei
    voxel_res: Voxelauflösung (64=schnell/grob, 128=Standard, 256=langsam/fein)

    Gibt Dict zurück:
        {"ok": True, "stl_path": ..., "vertex_count": ..., "triangle_count": ...}
        {"ok": False, "error": "..."}
    """
    result = {
        "ok": False,
        "stl_path": None,
        "vertex_count": 0,
        "triangle_count": 0,
        "error": None,
    }

    required_views = {"front", "top", "left", "right", "back"}
    missing = required_views - set(image_paths.keys())
    if missing:
        result["error"] = f"Fehlende Ansichten: {', '.join(sorted(missing))}"
        return result

    # 1. Silhouetten extrahieren
    silhouettes = {}
    for view, path in image_paths.items():
        if not os.path.exists(path):
            result["error"] = f"Bild nicht gefunden: {path}"
            return result
        try:
            sil = extract_silhouette(path, voxel_res)
            silhouettes[view] = sil
        except Exception as e:
            result["error"] = f"Silhouetten-Fehler ({view}): {e}"
            return result

    # 2. Voxel-Carving
    try:
        grid = voxel_carve(silhouettes, voxel_res)
    except Exception as e:
        result["error"] = f"Voxel-Carving-Fehler: {e}"
        return result

    filled_ratio = grid.sum() / grid.size
    if filled_ratio < 0.001:
        result["error"] = (
            "Voxelgitter fast leer nach Carving — Silhouetten möglicherweise falsch. "
            "Bitte einfarbigen Hintergrund und gute Beleuchtung verwenden."
        )
        return result

    # 3. STL generieren
    try:
        os.makedirs(os.path.dirname(output_stl) if os.path.dirname(output_stl) else ".", exist_ok=True)
        mesh_info = grid_to_stl(grid, dimensions_mm, output_stl)
    except Exception as e:
        result["error"] = f"STL-Generierungsfehler: {e}"
        return result

    result["ok"] = True
    result["stl_path"] = output_stl
    result["vertex_count"] = mesh_info["vertex_count"]
    result["triangle_count"] = mesh_info["triangle_count"]
    result["filled_voxel_ratio"] = round(float(filled_ratio), 4)
    return result


# --------------------------------------------------------------------------- #
# CLI-Einstiegspunkt (für Tests)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Voxel-Carving Rekonstruktion aus 5 Fotos")
    parser.add_argument("--front",  required=True)
    parser.add_argument("--top",    required=True)
    parser.add_argument("--left",   required=True)
    parser.add_argument("--right",  required=True)
    parser.add_argument("--back",   required=True)
    parser.add_argument("--width",  type=float, default=100.0)
    parser.add_argument("--height", type=float, default=100.0)
    parser.add_argument("--depth",  type=float, default=100.0)
    parser.add_argument("--output", default="output.stl")
    parser.add_argument("--res",    type=int, default=128)
    args = parser.parse_args()

    paths = {
        "front": args.front,
        "top":   args.top,
        "left":  args.left,
        "right": args.right,
        "back":  args.back,
    }
    dims = (args.width, args.height, args.depth)

    try:
        res = run_reconstruction(paths, dims, args.output, voxel_res=args.res)
    except Exception:
        res = {"ok": False, "error": traceback.format_exc()}

    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)
