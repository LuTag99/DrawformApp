#!/usr/bin/env python
"""
Automated test script for view selection and alignment.
Generates PDFs and JSON reports, then validates the results.
"""
import json
import subprocess
import sys
from pathlib import Path

FREECAD_PYTHON = r"C:\Program Files\FreeCAD 1.0\bin\python.exe"
SAMPLES_DIR = Path(__file__).parent / "_samples"
DEBUG_DIR = Path(__file__).parent / "_debug"
SCRIPT_PATH = Path(__file__).parent / "freecad" / "step_to_pdf.py"

# Expected results for each test part
EXPECTED = {
    "10x10x10": {
        "longest_axis": "X",  # Cube, any axis is fine
        "is_flat": False,
        "alignment_ok": True,
    },
    "rechteck": {
        "longest_axis": "Y",  # 300mm is Y
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 300mm should be horizontal (wider than tall)
    },
    "cylinder": {
        "longest_axis": "Z",  # 80mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
    },
    "shaft": {
        "longest_axis": "Z",  # 100mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
    },
    "flange": {
        "longest_axis": "X",  # Diameter 100mm
        "is_flat": True,  # 10mm thick << 100mm diameter
        "alignment_ok": True,
        "front_aspect_near_1": True,  # Circle should be ~square
    },
    "sheet_metal": {
        "longest_axis": "X",  # 200mm
        "is_flat": True,  # 3mm thick
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200x100 rectangle
    },
    "l_shape": {
        "longest_axis": "X",  # 100mm (tied with Y)
        "is_flat": False,
        "alignment_ok": True,
    },
    "angle_profile": {
        "longest_axis": "X",  # 150mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
    },
    "tall_thin": {
        "longest_axis": "Z",  # 200mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200mm should be horizontal
    },
    "slot_plate": {
        "longest_axis": "X",  # 120mm
        "is_flat": True,  # 8mm thick
        "alignment_ok": True,
    },
    "bracket": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
    },
    "housing": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
    },
    "t_profile": {
        "longest_axis": "Y",
        "is_flat": False,
        "alignment_ok": True,
    },
    "rect_part": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
    },
}


def run_conversion(step_file: Path) -> dict:
    """Run the PDF conversion and return the JSON report."""
    pdf_path = DEBUG_DIR / f"{step_file.stem}_test.pdf"
    json_path = DEBUG_DIR / f"{step_file.stem}_report.json"
    
    env = {"DRAWFORM_DEBUG_DIR": str(DEBUG_DIR)}
    
    result = subprocess.run(
        [FREECAD_PYTHON, str(SCRIPT_PATH), str(step_file), str(pdf_path)],
        capture_output=True,
        text=True,
        env={**subprocess.os.environ, **env},
    )
    
    if not json_path.exists():
        return {"error": f"No report generated. stderr: {result.stderr}"}
    
    return json.loads(json_path.read_text(encoding="utf-8"))


def check_alignment(report: dict) -> tuple[bool, list[str]]:
    """Check if views are properly aligned."""
    issues = []
    alignment = report.get("alignment", {})
    
    if not alignment.get("front_top_left_match", False):
        diff = abs(alignment.get("front_left_edge", 0) - alignment.get("top_left_edge", 0))
        issues.append(f"Front/Top left edges differ by {diff:.2f}mm")
    
    if not alignment.get("front_left_top_match", False):
        diff = abs(alignment.get("front_top_edge", 0) - alignment.get("left_top_edge", 0))
        issues.append(f"Front/Left top edges differ by {diff:.2f}mm")
    
    return len(issues) == 0, issues


def check_view_orientation(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Check if the view selection is correct."""
    issues = []
    detection = report.get("detection", {})
    views = report.get("views", {})
    
    expected_axis = expected.get("longest_axis")
    actual_axis = detection.get("longest_axis")
    if expected_axis and actual_axis != expected_axis:
        issues.append(f"Wrong longest axis: expected {expected_axis}, got {actual_axis}")
    
    expected_flat = expected.get("is_flat", False)
    # Check if flat detection worked (look at flatness in debug info)
    bb = report.get("bounding_box", {})
    dims = sorted([bb.get("X", 0), bb.get("Y", 0), bb.get("Z", 0)], reverse=True)
    if len(dims) == 3 and dims[1] > 0:
        actual_flat = (dims[2] / dims[1]) < 0.3
        if expected_flat != actual_flat:
            issues.append(f"Flat detection: expected {expected_flat}, got {actual_flat}")
    
    # Check Front view orientation
    front = views.get("Front", {})
    if front:
        paper_w, paper_h = front.get("paper_size", [0, 0])
        
        # Check if width > height (longest axis horizontal)
        if expected.get("front_width_gt_height"):
            if paper_w <= paper_h:
                issues.append(f"Front not horizontal: w={paper_w:.1f} <= h={paper_h:.1f}")
        
        # Check if aspect ratio is near 1 (for circles/squares)
        if expected.get("front_aspect_near_1"):
            aspect = paper_w / max(paper_h, 0.1)
            if aspect < 0.7 or aspect > 1.4:
                issues.append(f"Front not square-ish: aspect={aspect:.2f}")
    
    return len(issues) == 0, issues


def main():
    DEBUG_DIR.mkdir(exist_ok=True)
    
    step_files = sorted(SAMPLES_DIR.glob("*.stp"))
    
    results = []
    all_passed = True
    
    print(f"\n{'='*60}")
    print(f"Testing {len(step_files)} STEP files")
    print(f"{'='*60}\n")
    
    for step_file in step_files:
        name = step_file.stem
        print(f"Testing: {name}...", end=" ", flush=True)
        
        report = run_conversion(step_file)
        
        if "error" in report:
            print(f"❌ ERROR: {report['error'][:50]}")
            all_passed = False
            continue
        
        expected = EXPECTED.get(name, {})
        
        # Check alignment
        align_ok, align_issues = check_alignment(report)
        
        # Check view orientation
        orient_ok, orient_issues = check_view_orientation(report, expected)
        
        all_issues = align_issues + orient_issues
        
        if all_issues:
            print(f"❌ FAILED")
            for issue in all_issues:
                print(f"   - {issue}")
            all_passed = False
        else:
            bb = report["bounding_box"]
            det = report["detection"]
            print(f"✅ OK (axis={det['longest_axis']}, conf={det['confidence']:.2f})")
        
        results.append({
            "name": name,
            "passed": len(all_issues) == 0,
            "issues": all_issues,
            "report": report,
        })
    
    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["passed"])
    print(f"Results: {passed}/{len(results)} passed")
    print(f"{'='*60}\n")
    
    # Summary table
    print(f"\n{'Part':<20} {'Axis':<6} {'Flat':<6} {'Align':<8} {'Front W×H':<16} {'Conf':<6}")
    print("-" * 70)
    for r in results:
        if "error" not in r.get("report", {}):
            det = r["report"]["detection"]
            align = r["report"]["alignment"]
            front = r["report"]["views"].get("Front", {})
            paper = front.get("paper_size", [0, 0])
            align_ok = align["front_top_left_match"] and align["front_left_top_match"]
            orientation = "→" if paper[0] > paper[1] else "↓" if paper[1] > paper[0] else "□"
            print(f"{r['name']:<20} {det['longest_axis']:<6} {str(det.get('is_flat', '?')):<6} {str(align_ok):<8} {paper[0]:>6.1f}×{paper[1]:<6.1f} {orientation}  {det['confidence']:.2f}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
