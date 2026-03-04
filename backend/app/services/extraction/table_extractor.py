"""Extract table shapes with cell formatting and merged cells."""

from app.services.extraction.text_extractor import extract_text_body
from app.services.extraction.utils import get_fill_data, get_color_hex


def extract_table_shape(shape, base: dict) -> dict:
    """Extract a table shape with all cell data."""
    table = shape.table

    rows_count = len(table.rows)
    cols_count = len(table.columns)

    # Column widths
    column_widths_emu = []
    for col in table.columns:
        try:
            column_widths_emu.append(col.width)
        except Exception:
            column_widths_emu.append(0)

    # Row heights
    row_heights_emu = []
    for row in table.rows:
        try:
            row_heights_emu.append(row.height)
        except Exception:
            row_heights_emu.append(0)

    # Track which cells are "consumed" by merges
    consumed = set()
    cells = []

    for row_idx in range(rows_count):
        for col_idx in range(cols_count):
            if (row_idx, col_idx) in consumed:
                continue

            try:
                cell = table.cell(row_idx, col_idx)
            except Exception:
                continue

            # Determine span
            row_span = 1
            col_span = 1
            try:
                # Check if this cell spans multiple rows/cols by checking merge
                if cell.is_merge_origin:
                    # Find the extent of the merge
                    for r in range(row_idx, rows_count):
                        for c in range(col_idx, cols_count):
                            if r == row_idx and c == col_idx:
                                continue
                            try:
                                other = table.cell(r, c)
                                if other._tc is cell._tc:
                                    # Same underlying cell = part of merge
                                    consumed.add((r, c))
                                    if r - row_idx + 1 > row_span:
                                        row_span = r - row_idx + 1
                                    if c - col_idx + 1 > col_span:
                                        col_span = c - col_idx + 1
                            except Exception:
                                break
                else:
                    # Check if this cell is part of a merge but not the origin
                    # In that case it shares _tc with the merge origin
                    for r in range(rows_count):
                        for c in range(cols_count):
                            if r == row_idx and c == col_idx:
                                continue
                            try:
                                other = table.cell(r, c)
                                if other._tc is cell._tc and (r < row_idx or (r == row_idx and c < col_idx)):
                                    # This cell is consumed by an earlier merge origin
                                    consumed.add((row_idx, col_idx))
                                    break
                            except Exception:
                                continue
                        else:
                            continue
                        break

                    if (row_idx, col_idx) in consumed:
                        continue
            except Exception:
                pass

            # Extract cell fill
            cell_fill = {"type": "none"}
            try:
                cell_fill = get_fill_data(cell.fill)
            except Exception:
                pass

            # Extract cell borders
            cell_border = _extract_cell_borders(cell)

            # Vertical alignment
            vert_align = "top"
            try:
                if cell.vertical_anchor is not None:
                    vert_align = str(cell.vertical_anchor).split(".")[-1].split("(")[0].strip().lower()
            except Exception:
                pass

            # Extract cell margins
            margin_emu = {"left": 91440, "right": 91440, "top": 45720, "bottom": 45720}
            try:
                tc_elem = cell._tc
                if tc_elem is not None:
                    tcPr = tc_elem.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tcPr')
                    if tcPr is not None:
                        mar_l = tcPr.get('marL')
                        mar_r = tcPr.get('marR')
                        mar_t = tcPr.get('marT')
                        mar_b = tcPr.get('marB')
                        if mar_l is not None:
                            margin_emu["left"] = int(mar_l)
                        if mar_r is not None:
                            margin_emu["right"] = int(mar_r)
                        if mar_t is not None:
                            margin_emu["top"] = int(mar_t)
                        if mar_b is not None:
                            margin_emu["bottom"] = int(mar_b)
            except Exception:
                pass

            # Extract text content
            text_body = {"paragraphs": []}
            try:
                text_body = extract_text_body(cell.text_frame)
            except Exception:
                pass

            cells.append({
                "row": row_idx,
                "col": col_idx,
                "row_span": row_span,
                "col_span": col_span,
                "fill": cell_fill,
                "border": cell_border,
                "vertical_alignment": vert_align,
                "margin_emu": margin_emu,
                "text_body": text_body,
            })

    base.update({
        "shape_type": "table",
        "table": {
            "rows": rows_count,
            "columns": cols_count,
            "column_widths_emu": column_widths_emu,
            "row_heights_emu": row_heights_emu,
            "cells": cells,
        },
    })
    return base


def _extract_cell_borders(cell) -> dict:
    """Extract borders from a table cell using XML."""
    default = {"color": "#D0D0D0", "width_pt": 0.5}
    result = {
        "top": dict(default),
        "bottom": dict(default),
        "left": dict(default),
        "right": dict(default),
    }

    try:
        tc_elem = cell._tc
        tcPr = tc_elem.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tcPr')
        if tcPr is None:
            return result

        ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
        border_map = {
            'top': f'{ns}tcBorders/{ns}top' if False else None,
            'bottom': None,
            'left': None,
            'right': None,
        }

        for side in ['top', 'bottom', 'left', 'right']:
            elem_name = {
                'top': 'lnT', 'bottom': 'lnB', 'left': 'lnL', 'right': 'lnR'
            }[side]
            ln = tcPr.find(f'{ns}{elem_name}')
            if ln is not None:
                w = ln.get('w')
                if w:
                    result[side]["width_pt"] = round(int(w) / 12700, 2)

                solidFill = ln.find(f'{ns}solidFill')
                if solidFill is not None:
                    srgbClr = solidFill.find(f'{ns}srgbClr')
                    if srgbClr is not None:
                        result[side]["color"] = f"#{srgbClr.get('val', 'D0D0D0')}"
    except Exception:
        pass

    return result
