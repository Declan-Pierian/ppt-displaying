"""Utility functions for EMU conversion, color parsing, and other helpers."""

from pptx.util import Emu

EMU_PER_INCH = 914400
EMU_PER_PT = 12700
DEFAULT_DPI = 96


def emu_to_px(emu: int | None, dpi: int = DEFAULT_DPI) -> float:
    """Convert EMU (English Metric Units) to pixels at given DPI."""
    if emu is None:
        return 0.0
    return round((emu / EMU_PER_INCH) * dpi, 2)


def emu_to_pt(emu: int | None) -> float | None:
    """Convert EMU to points."""
    if emu is None:
        return None
    return round(emu / EMU_PER_PT, 2)


def rgb_to_hex(rgb) -> str | None:
    """Convert python-pptx RGBColor to hex string like #RRGGBB."""
    if rgb is None:
        return None
    return f"#{rgb}"


def get_color_hex(color_obj) -> str | None:
    """Safely extract hex color from a python-pptx color object."""
    try:
        if color_obj is None:
            return None
        color_type = color_obj.type
        if color_type is not None:
            from pptx.enum.dml import MSO_THEME_COLOR
            try:
                rgb = color_obj.rgb
                if rgb is not None:
                    return f"#{rgb}"
            except (AttributeError, ValueError):
                pass
            try:
                theme_color = color_obj.theme_color
                if theme_color is not None:
                    return _theme_color_fallback(theme_color)
            except (AttributeError, ValueError):
                pass
    except Exception:
        pass
    return None


def _theme_color_fallback(theme_color) -> str | None:
    """Provide reasonable fallback colors for common theme colors."""
    from pptx.enum.dml import MSO_THEME_COLOR
    fallbacks = {
        MSO_THEME_COLOR.DARK_1: "#000000",
        MSO_THEME_COLOR.LIGHT_1: "#FFFFFF",
        MSO_THEME_COLOR.DARK_2: "#44546A",
        MSO_THEME_COLOR.LIGHT_2: "#E7E6E6",
        MSO_THEME_COLOR.ACCENT_1: "#4472C4",
        MSO_THEME_COLOR.ACCENT_2: "#ED7D31",
        MSO_THEME_COLOR.ACCENT_3: "#A5A5A5",
        MSO_THEME_COLOR.ACCENT_4: "#FFC000",
        MSO_THEME_COLOR.ACCENT_5: "#5B9BD5",
        MSO_THEME_COLOR.ACCENT_6: "#70AD47",
        MSO_THEME_COLOR.HYPERLINK: "#0563C1",
        MSO_THEME_COLOR.FOLLOWED_HYPERLINK: "#954F72",
    }
    return fallbacks.get(theme_color)


def get_fill_data(fill_obj) -> dict:
    """Extract fill information from a python-pptx fill object."""
    try:
        if fill_obj is None:
            return {"type": "none"}

        fill_type = fill_obj.type
        if fill_type is None:
            return {"type": "none"}

        from pptx.enum.dml import MSO_THEME_COLOR

        type_name = str(fill_type).split(".")[-1].split("(")[0].strip().lower()

        if "solid" in type_name:
            color = None
            try:
                fore_color = fill_obj.fore_color
                color = get_color_hex(fore_color)
            except Exception:
                pass
            return {"type": "solid", "color": color or "#CCCCCC"}

        elif "gradient" in type_name:
            stops = []
            try:
                for stop in fill_obj.gradient_stops:
                    stop_color = get_color_hex(stop.color)
                    stops.append({
                        "color": stop_color or "#CCCCCC",
                        "position": round(stop.position, 4),
                    })
            except Exception:
                pass
            angle = None
            try:
                angle = fill_obj.gradient_angle
            except Exception:
                pass
            return {"type": "gradient", "gradient_stops": stops, "angle_degrees": angle}

        elif "pattern" in type_name:
            fg_color = None
            bg_color = None
            try:
                fg_color = get_color_hex(fill_obj.fore_color)
                bg_color = get_color_hex(fill_obj.back_color)
            except Exception:
                pass
            return {"type": "pattern", "fg_color": fg_color, "bg_color": bg_color}

        return {"type": "none"}
    except Exception:
        return {"type": "none"}


def get_border_data(line_obj) -> dict:
    """Extract border/line information."""
    try:
        if line_obj is None:
            return {"color": None, "width_pt": None, "dash_style": None}

        color = None
        try:
            if line_obj.fill and line_obj.fill.type is not None:
                color = get_color_hex(line_obj.color)
        except Exception:
            pass

        width_pt = None
        try:
            if line_obj.width is not None:
                width_pt = round(line_obj.width / EMU_PER_PT, 2)
        except Exception:
            pass

        dash_style = None
        try:
            if line_obj.dash_style is not None:
                dash_style = str(line_obj.dash_style).split(".")[-1].split("(")[0].strip().lower()
        except Exception:
            pass

        return {"color": color, "width_pt": width_pt, "dash_style": dash_style}
    except Exception:
        return {"color": None, "width_pt": None, "dash_style": None}
