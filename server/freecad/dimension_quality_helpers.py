from __future__ import annotations


def boxes_overlap(box_a, box_b, margin=0.0):
    if box_a is None or box_b is None:
        return False
    return not (
        (box_a[1] + margin) < box_b[0]
        or (box_b[1] + margin) < box_a[0]
        or (box_a[3] + margin) < box_b[2]
        or (box_b[3] + margin) < box_a[2]
    )


def text_collision_box(text, x, y, text_size, anchor):
    width = max(text_size * 1.6, text_size * 0.58 * max(1, len(str(text))))
    height = max(text_size * 1.15, 0.4)
    if anchor == "start":
        left = x
    elif anchor == "end":
        left = x - width
    else:
        left = x - width * 0.5
    right = left + width
    bottom = y - height * 0.30
    top = y + height * 0.85
    return (left, right, bottom, top)


def rotated_text_collision_box(text, x, y, text_size):
    rotated_extent = max(text_size * 1.15, text_size * 0.58 * max(1, len(str(text))))
    return (
        x - text_size * 0.7,
        x + text_size * 0.7,
        y - rotated_extent * 0.55,
        y + rotated_extent * 0.55,
    )


def summarize_view_dimension_quality(geometry_bounds, overall_dimensions=None, feature_dimensions=None):
    geom_box = tuple(geometry_bounds or ())
    overall_dimensions = list(overall_dimensions or [])
    feature_dimensions = list(feature_dimensions or [])

    overall_visual_boxes = []
    feature_visual_boxes = []
    text_entries = []

    overall_geom_overlap_count = 0
    feature_geom_overlap_count = 0
    feature_overall_overlap_count = 0
    text_overlap_count = 0

    for entry in overall_dimensions:
        measurement_box = entry.get("measurement_box")
        text_box = entry.get("text_box")
        if measurement_box is not None:
            overall_visual_boxes.append(measurement_box)
            if geom_box and boxes_overlap(measurement_box, geom_box, margin=0.0):
                overall_geom_overlap_count += 1
        if text_box is not None:
            overall_visual_boxes.append(text_box)
            text_entries.append(
                {
                    "box": text_box,
                    "outside": False,
                    "style": str(entry.get("style") or "line"),
                    "kind": "overall",
                }
            )
            if geom_box and boxes_overlap(text_box, geom_box, margin=0.0):
                overall_geom_overlap_count += 1

    for entry in feature_dimensions:
        measurement_box = entry.get("measurement_box")
        text_box = entry.get("text_box")
        is_outside = bool(entry.get("outside"))
        style = str(entry.get("style") or "line")
        if measurement_box is not None:
            if style == "line":
                feature_visual_boxes.append(measurement_box)
            if is_outside and style == "line" and geom_box and boxes_overlap(measurement_box, geom_box, margin=0.0):
                feature_geom_overlap_count += 1
        if text_box is not None:
            feature_visual_boxes.append(text_box)
            text_entries.append(
                {
                    "box": text_box,
                    "outside": is_outside,
                    "style": style,
                    "kind": "feature",
                }
            )
            text_margin = -1.5 if is_outside and style == "leader" else 0.0
            if is_outside and geom_box and boxes_overlap(text_box, geom_box, margin=text_margin):
                feature_geom_overlap_count += 1

    for feature_box in feature_visual_boxes:
        for overall_box in overall_visual_boxes:
            if boxes_overlap(feature_box, overall_box, margin=0.05):
                feature_overall_overlap_count += 1

    for index, left in enumerate(text_entries):
        for right in text_entries[index + 1 :]:
            margin = 0.05
            if (
                left.get("kind") == "feature"
                and right.get("kind") == "feature"
                and left.get("outside")
                and right.get("outside")
                and left.get("style") == "leader"
                and right.get("style") == "leader"
            ):
                margin = -2.0
            if boxes_overlap(left.get("box"), right.get("box"), margin=margin):
                text_overlap_count += 1

    return {
        "overall_count": len(overall_dimensions),
        "feature_count": len(feature_dimensions),
        "outside_feature_count": sum(1 for entry in feature_dimensions if bool(entry.get("outside"))),
        "overall_geom_overlap_count": int(overall_geom_overlap_count),
        "feature_geom_overlap_count": int(feature_geom_overlap_count),
        "feature_overall_overlap_count": int(feature_overall_overlap_count),
        "text_overlap_count": int(text_overlap_count),
    }
