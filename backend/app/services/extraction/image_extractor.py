"""Extract images from shapes and slide backgrounds."""

import os
import logging
from app.services.extraction.utils import get_border_data

logger = logging.getLogger(__name__)

CONTENT_TYPE_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/svg+xml": ".svg",
    "image/x-wmf": ".wmf",
    "image/x-emf": ".emf",
}


def extract_image_shape(shape, base: dict, media_dir: str, presentation_id: int, slide_index: int = 0) -> dict:
    """Extract an image shape, saving the image file to media_dir."""
    try:
        image = shape.image
        content_type = image.content_type
        ext = CONTENT_TYPE_MAP.get(content_type, ".png")

        # Include slide index in filename to prevent collisions across slides
        filename = f"image_s{slide_index}_{shape.shape_id}{ext}"
        filepath = os.path.join(media_dir, filename)

        with open(filepath, "wb") as f:
            f.write(image.blob)

        # Convert WMF/EMF to PNG if possible
        if ext in (".wmf", ".emf"):
            try:
                from PIL import Image
                img = Image.open(filepath)
                png_filename = f"image_s{slide_index}_{shape.shape_id}.png"
                png_path = os.path.join(media_dir, png_filename)
                img.save(png_path, "PNG")
                filename = png_filename
            except Exception:
                pass

        # Get image dimensions
        original_width = None
        original_height = None
        try:
            from PIL import Image
            img = Image.open(os.path.join(media_dir, filename))
            original_width, original_height = img.size
        except Exception:
            pass

        # Crop info
        crop = None
        try:
            crop_left = getattr(shape, 'crop_left', 0) or 0
            crop_top = getattr(shape, 'crop_top', 0) or 0
            crop_right = getattr(shape, 'crop_right', 0) or 0
            crop_bottom = getattr(shape, 'crop_bottom', 0) or 0
            if any([crop_left, crop_top, crop_right, crop_bottom]):
                crop = {
                    "left": round(float(crop_left), 6),
                    "top": round(float(crop_top), 6),
                    "right": round(float(crop_right), 6),
                    "bottom": round(float(crop_bottom), 6),
                }
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

        # Alt text
        alt_text = ""
        try:
            alt_text = shape.name or ""
        except Exception:
            pass

        border = {"color": None, "width_pt": None, "dash_style": None}
        try:
            border = get_border_data(shape.line)
        except Exception:
            pass

        base.update({
            "shape_type": "image",
            "image": {
                "media_path": f"media/{filename}",
                "original_width_px": original_width,
                "original_height_px": original_height,
                "crop": crop,
                "alt_text": alt_text,
            },
            "border": border,
            "hyperlink": hyperlink,
        })
        return base

    except Exception as e:
        base.update({
            "shape_type": "image",
            "image": {
                "media_path": None,
                "original_width_px": None,
                "original_height_px": None,
                "crop": None,
                "alt_text": f"Image extraction failed: {str(e)}",
            },
            "border": {"color": None, "width_pt": None, "dash_style": None},
            "hyperlink": None,
        })
        return base


def extract_background(slide, media_dir: str, slide_index: int, presentation_id: int) -> dict:
    """Extract slide background information with robust fallbacks."""
    ns_a = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    ns_r = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    ns_p = '{http://schemas.openxmlformats.org/presentationml/2006/main}'

    # --- Method 1: Try python-pptx fill API ---
    try:
        background = slide.background
        fill = background.fill

        if fill is not None and fill.type is not None:
            fill_type_str = str(fill.type).lower()

            if "solid" in fill_type_str:
                color = None
                try:
                    from app.services.extraction.utils import get_color_hex
                    color = get_color_hex(fill.fore_color)
                except Exception:
                    pass
                return {"type": "solid", "color": color or "#FFFFFF"}

            elif "gradient" in fill_type_str:
                stops = []
                try:
                    for stop in fill.gradient_stops:
                        from app.services.extraction.utils import get_color_hex
                        stop_color = get_color_hex(stop.color)
                        stops.append({
                            "color": stop_color or "#FFFFFF",
                            "position": round(stop.position, 4),
                        })
                except Exception:
                    pass
                if stops:
                    return {"type": "gradient", "gradient_stops": stops}

            elif "picture" in fill_type_str or "image" in fill_type_str:
                result = _extract_bg_image_from_fill(slide, media_dir, slide_index)
                if result:
                    return result

            elif "pattern" in fill_type_str:
                color = None
                try:
                    from app.services.extraction.utils import get_color_hex
                    color = get_color_hex(fill.fore_color)
                except Exception:
                    pass
                if color:
                    return {"type": "solid", "color": color}
    except Exception:
        pass

    # --- Method 2: Direct XML inspection for background image ---
    # This catches cases where fill.type doesn't report "picture"
    try:
        result = _extract_bg_image_from_xml(slide, media_dir, slide_index)
        if result:
            return result
    except Exception:
        pass

    # --- Method 3: Check slide layout background ---
    try:
        layout = slide.slide_layout
        if layout and layout.background:
            layout_fill = layout.background.fill
            if layout_fill and layout_fill.type is not None:
                fill_type_str = str(layout_fill.type).lower()
                if "solid" in fill_type_str:
                    from app.services.extraction.utils import get_color_hex
                    color = get_color_hex(layout_fill.fore_color)
                    if color:
                        return {"type": "solid", "color": color}
                elif "picture" in fill_type_str or "image" in fill_type_str:
                    result = _extract_bg_image_from_fill_obj(layout, media_dir, slide_index, "layout")
                    if result:
                        return result
    except Exception:
        pass

    # --- Method 4: Check slide master background ---
    try:
        master = slide.slide_layout.slide_master
        if master and master.background:
            master_fill = master.background.fill
            if master_fill and master_fill.type is not None:
                fill_type_str = str(master_fill.type).lower()
                if "solid" in fill_type_str:
                    from app.services.extraction.utils import get_color_hex
                    color = get_color_hex(master_fill.fore_color)
                    if color:
                        return {"type": "solid", "color": color}
    except Exception:
        pass

    return {"type": "none"}


def _extract_bg_image_from_fill(slide, media_dir: str, slide_index: int) -> dict | None:
    """Extract background image using slide's background element."""
    return _extract_bg_image_from_fill_obj(slide, media_dir, slide_index, "slide")


def _extract_bg_image_from_fill_obj(obj, media_dir: str, slide_index: int, source: str) -> dict | None:
    """Extract background image from any object's background element."""
    ns_a = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    ns_r = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

    try:
        bg_elem = obj.background._element if hasattr(obj, 'background') else obj._element
        blip_fill = bg_elem.find(f'.//{ns_a}blipFill')

        if blip_fill is not None:
            blip = blip_fill.find(f'{ns_a}blip')
            if blip is not None:
                r_embed = blip.get(f'{ns_r}embed')
                if r_embed:
                    part = obj.part if hasattr(obj, 'part') else obj
                    rel = part.rels.get(r_embed)
                    if rel and hasattr(rel, 'target_part'):
                        image_blob = rel.target_part.blob

                        # Detect format from content type
                        ext = ".png"
                        try:
                            ct = rel.target_part.content_type
                            ext = CONTENT_TYPE_MAP.get(ct, ".png")
                        except Exception:
                            pass

                        filename = f"bg_slide{slide_index}{ext}"
                        filepath = os.path.join(media_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(image_blob)

                        logger.info(f"Extracted background image for slide {slide_index + 1}: {filename}")
                        return {
                            "type": "image",
                            "image_path": f"media/{filename}",
                        }
    except Exception as e:
        logger.warning(f"Background image extraction from {source} failed: {e}")

    return None


def _extract_bg_image_from_xml(slide, media_dir: str, slide_index: int) -> dict | None:
    """Extract background image by directly inspecting slide XML."""
    ns_a = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    ns_r = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    ns_p = '{http://schemas.openxmlformats.org/presentationml/2006/main}'

    try:
        slide_elem = slide._element

        # Look for background element with blipFill
        for bg in slide_elem.iter():
            if bg.tag.endswith('}bg') or bg.tag.endswith('}background'):
                blip_fill = bg.find(f'.//{ns_a}blipFill')
                if blip_fill is None:
                    blip_fill = bg.find(f'.//{ns_a}blip')

                if blip_fill is not None:
                    # Find the actual blip element
                    if blip_fill.tag.endswith('}blip'):
                        blip = blip_fill
                    else:
                        blip = blip_fill.find(f'{ns_a}blip')

                    if blip is not None:
                        r_embed = blip.get(f'{ns_r}embed')
                        if r_embed:
                            rel = slide.part.rels.get(r_embed)
                            if rel and hasattr(rel, 'target_part'):
                                image_blob = rel.target_part.blob

                                ext = ".png"
                                try:
                                    ct = rel.target_part.content_type
                                    ext = CONTENT_TYPE_MAP.get(ct, ".png")
                                except Exception:
                                    pass

                                filename = f"bg_slide{slide_index}{ext}"
                                filepath = os.path.join(media_dir, filename)
                                with open(filepath, "wb") as f:
                                    f.write(image_blob)

                                logger.info(f"Extracted background image (XML) for slide {slide_index + 1}")
                                return {
                                    "type": "image",
                                    "image_path": f"media/{filename}",
                                }
    except Exception as e:
        logger.warning(f"XML background extraction failed: {e}")

    return None
