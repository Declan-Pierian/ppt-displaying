"""Extract grouped shapes recursively."""


def extract_group_shape(shape, base: dict, media_dir: str, presentation_id: int, extract_shape_fn) -> dict:
    """Extract a group shape by recursively extracting its child shapes.

    Args:
        shape: The group shape object from python-pptx
        base: Base shape data dict with position, rotation, z_order
        media_dir: Directory to save extracted media
        presentation_id: ID of the presentation
        extract_shape_fn: Reference to the main extract_shape function for recursion
    """
    child_shapes = []
    parent_z = base.get("z_order", 0)

    try:
        for z_idx, child_shape in enumerate(shape.shapes):
            child_data = extract_shape_fn(
                child_shape, media_dir, parent_z * 1000 + z_idx, presentation_id
            )
            if child_data:
                child_shapes.append(child_data)
    except Exception:
        pass

    # Group coordinate space
    group_data = {
        "child_offset_x_emu": 0,
        "child_offset_y_emu": 0,
        "child_extent_x_emu": base["position"]["width_emu"],
        "child_extent_y_emu": base["position"]["height_emu"],
        "shapes": child_shapes,
    }

    # Try to get the actual group transform coordinates
    try:
        grpSp = shape._element
        ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
        pns = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
        sp_ns = '{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'

        grpSpPr = grpSp.find(f'{ns}grpSpPr')
        if grpSpPr is None:
            grpSpPr = grpSp.find(f'{pns}grpSpPr')

        if grpSpPr is not None:
            xfrm = grpSpPr.find(f'{ns}xfrm')
            if xfrm is not None:
                chOff = xfrm.find(f'{ns}chOff')
                chExt = xfrm.find(f'{ns}chExt')
                if chOff is not None:
                    group_data["child_offset_x_emu"] = int(chOff.get('x', 0))
                    group_data["child_offset_y_emu"] = int(chOff.get('y', 0))
                if chExt is not None:
                    group_data["child_extent_x_emu"] = int(chExt.get('cx', 0))
                    group_data["child_extent_y_emu"] = int(chExt.get('cy', 0))
    except Exception:
        pass

    base.update({
        "shape_type": "group",
        "group": group_data,
    })
    return base
