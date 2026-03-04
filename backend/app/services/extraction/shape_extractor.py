"""Extract AutoShape properties (rectangles, ellipses, arrows, etc.)."""

from app.services.extraction.text_extractor import extract_text_body
from app.services.extraction.utils import get_fill_data, get_border_data


# Map common MSO auto shape types to descriptive names
SHAPE_TYPE_NAMES = {
    1: "rectangle",
    2: "roundRect",
    3: "ellipse",
    4: "diamond",
    5: "triangle",
    6: "rightTriangle",
    7: "parallelogram",
    8: "trapezoid",
    9: "pentagon",
    10: "hexagon",
    13: "arrow",
    14: "star5",
    15: "star8",
    16: "star16",
    17: "star24",
    20: "line",
    21: "rightArrow",
    22: "leftArrow",
    23: "upArrow",
    24: "downArrow",
    66: "cloud",
    106: "heart",
    183: "freeform",
}


def extract_auto_shape(shape, base: dict) -> dict:
    """Extract an AutoShape with fill, border, text, and shape type."""
    # Determine the specific auto shape type
    auto_shape_type = "rectangle"
    try:
        if shape.auto_shape_type is not None:
            type_val = int(shape.auto_shape_type)
            auto_shape_type = SHAPE_TYPE_NAMES.get(type_val, f"shape_{type_val}")
    except Exception:
        pass

    # Fill
    fill_data = {"type": "none"}
    try:
        fill_data = get_fill_data(shape.fill)
    except Exception:
        pass

    # Border
    border_data = {"color": None, "width_pt": None, "dash_style": None}
    try:
        border_data = get_border_data(shape.line)
    except Exception:
        pass

    # Text body (many AutoShapes contain text)
    text_body = None
    try:
        if shape.has_text_frame:
            text_body = extract_text_body(shape.text_frame)
    except Exception:
        pass

    # Hyperlink
    hyperlink = None
    try:
        click_action = shape._element.find(
            './/{http://schemas.openxmlformats.org/drawingml/2006/main}hlinkClick'
        )
        if click_action is not None:
            r_id = click_action.get(
                '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
            )
            if r_id:
                rel = shape.part.rels.get(r_id)
                if rel and hasattr(rel, 'target_ref'):
                    hyperlink = rel.target_ref
    except Exception:
        pass

    # Shadow (basic extraction)
    shadow = None
    try:
        sp_elem = shape._element
        ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
        effectLst = sp_elem.find(f'.//{ns}effectLst')
        if effectLst is not None:
            outerShdw = effectLst.find(f'{ns}outerShdw')
            if outerShdw is not None:
                shadow = {
                    "blur_radius_emu": int(outerShdw.get('blurRad', 0)),
                    "dist_emu": int(outerShdw.get('dist', 0)),
                    "direction": int(outerShdw.get('dir', 0)),
                }
                srgbClr = outerShdw.find(f'{ns}srgbClr')
                if srgbClr is not None:
                    shadow["color"] = f"#{srgbClr.get('val', '000000')}"
                    alpha = srgbClr.find(f'{ns}alpha')
                    if alpha is not None:
                        shadow["opacity"] = int(alpha.get('val', '100000')) / 1000
    except Exception:
        pass

    base.update({
        "shape_type": "auto_shape",
        "auto_shape_type": auto_shape_type,
        "fill": fill_data,
        "border": border_data,
        "text_body": text_body,
        "hyperlink": hyperlink,
        "shadow": shadow,
    })
    return base
