"""Generate a beautiful HTML webpage from presentation content using Claude API.

Flow:
1. Read extracted slides.json + rendered slide images (PNGs)
2. Send slide images + extracted text to Claude API
3. Claude generates a self-contained HTML page (dark theme, navigation, transitions)
4. Save as webpage.html in the presentation directory
"""

import os
import json
import base64
import logging
from pathlib import Path

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

# Load the reference HTML template (style guide for Claude)
_REFERENCE_PATH = Path(__file__).parent / "reference_style.html"
_REFERENCE_HTML = ""
if _REFERENCE_PATH.exists():
    _REFERENCE_HTML = _REFERENCE_PATH.read_text(encoding="utf-8")


def _extract_text_from_shapes(shapes: list) -> list[str]:
    """Extract readable text lines from a slide's shapes."""
    texts = []
    for shape in shapes:
        shape_type = shape.get("shape_type", "")

        # Text boxes
        if shape_type == "text_box" and shape.get("text_body"):
            for para in shape["text_body"].get("paragraphs", []):
                para_text = "".join(
                    run.get("text", "") for run in para.get("runs", [])
                )
                if para_text.strip():
                    texts.append(para_text.strip())

        # Tables
        elif shape_type == "table" and shape.get("table"):
            table = shape["table"]
            for row in table.get("rows", []):
                row_texts = []
                for cell in row.get("cells", []):
                    cell_text = cell.get("text", "")
                    if not cell_text and cell.get("paragraphs"):
                        cell_text = " ".join(
                            "".join(r.get("text", "") for r in p.get("runs", []))
                            for p in cell["paragraphs"]
                        )
                    row_texts.append(cell_text.strip())
                row_line = " | ".join(row_texts)
                if row_line.strip(" |"):
                    texts.append(f"[Table] {row_line}")

        # Groups (recursive)
        elif shape_type == "group" and shape.get("children"):
            texts.extend(_extract_text_from_shapes(shape["children"]))

    return texts


def _get_image_refs(shapes: list, presentation_id: int) -> list[str]:
    """Get image URLs referenced in slide shapes."""
    images = []
    for shape in shapes:
        if shape.get("shape_type") == "image":
            img_data = shape.get("image", {})
            path = img_data.get("image_path", "")
            if path:
                filename = path.replace("media/", "", 1)
                url = f"/api/v1/media/{presentation_id}/{filename}"
                images.append(url)
        elif shape.get("shape_type") == "group" and shape.get("children"):
            images.extend(_get_image_refs(shape["children"], presentation_id))
    return images


def _get_background_images(slides: list, presentation_id: int) -> dict:
    """Get background image URLs per slide."""
    bg_map = {}
    for slide in slides:
        bg = slide.get("background", {})
        if bg.get("type") == "image" and bg.get("image_path"):
            filename = bg["image_path"].replace("media/", "", 1)
            url = f"/api/v1/media/{presentation_id}/{filename}"
            bg_map[slide["slide_number"]] = url
    return bg_map


def generate_webpage(
    presentation_id: int,
    slides_json_path: str,
    media_dir: str,
    pres_dir: str,
) -> str | None:
    """Generate an HTML webpage from the presentation using Claude API.

    Returns the path to the generated webpage.html, or None on failure.
    """
    api_key = settings.CLAUDE_API_KEY
    if not api_key:
        logger.warning("CLAUDE_API_KEY not set — skipping webpage generation.")
        return None

    # Load slides data
    with open(slides_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    slides = data["slides"]
    title = data.get("title", "Presentation")
    total = len(slides)

    if total == 0:
        logger.warning("No slides found — skipping webpage generation.")
        return None

    # Collect all available images (for reference in the prompt)
    all_images = set()
    for slide in slides:
        bg = slide.get("background", {})
        if bg.get("type") == "image" and bg.get("image_path"):
            all_images.add(bg["image_path"].replace("media/", "", 1))
        for shape in slide.get("shapes", []):
            if shape.get("shape_type") == "image":
                path = shape.get("image", {}).get("image_path", "")
                if path:
                    all_images.add(path.replace("media/", "", 1))

    image_url_map = {
        img: f"/api/v1/media/{presentation_id}/{img}"
        for img in sorted(all_images)
    }

    bg_images = _get_background_images(slides, presentation_id)

    # ── Build the Claude API message ──

    content_blocks = []

    # Instructions + reference
    instructions = f"""You are an expert web designer. Your task is to convert a PowerPoint presentation into a stunning, self-contained HTML web page.

## Style Reference
Below is a reference HTML page demonstrating the desired design language. Follow the same patterns:
- Dark theme (#0f172a background, light text)
- Gradient accents (indigo→cyan)
- Card-based layouts with subtle borders
- Full-screen slides with smooth transitions
- Progress bar, slide counter, prev/next navigation, keyboard + touch support
- Professional typography (Inter font family)
- Tags, metric cards, feature lists, dividers as content elements
- A back button (top-left) linking to "/" so users can return to the presentation list

```html
{_REFERENCE_HTML}
```

## Presentation Details
- Title: "{title}"
- Total Slides: {total}
- Presentation ID: {presentation_id}

## Available Images from the Presentation
Use these exact URLs for any images you include in the HTML:
{json.dumps(image_url_map, indent=2)}

## Background Images per Slide
{json.dumps(bg_images, indent=2) if bg_images else "No background images detected. Use the dark theme background."}

## CRITICAL INSTRUCTIONS
1. Output ONLY the raw HTML code. Start with <!DOCTYPE html> and end with </html>. No markdown fencing, no explanations before or after.
2. Each slide becomes one full-screen page with animated transitions.
3. Include: progress bar at top, slide counter at bottom-right, circular prev/next arrows at left/right, keyboard navigation (arrows, space, Home, End), touch swipe support.
4. DO NOT just display slide images. Extract and recreate all text content as proper HTML elements.
5. For images FROM the presentation (logos, photos, diagrams), use <img> tags with the URLs listed above.
6. If a slide has a background image, use it as that slide's CSS background (background-image with cover).
7. Structure content intelligently: use cards, grids, metric displays, feature lists, tags — choose the best layout for each slide's content.
8. Make it visually stunning with gradients, subtle animations, and professional spacing.
9. The HTML must be completely self-contained (all CSS in <style>, all JS in <script>).
10. Include a back button (top-left, linking to "/") so users can return to the presentation list.
11. Adapt layouts to content: title slides get centered hero treatment, content-heavy slides get multi-column layouts, list slides get feature-list styling.

## Slides
Below I will show you each slide as a rendered image (so you can see the exact visual design and layout) followed by the extracted text content (for accuracy).
"""

    content_blocks.append({"type": "text", "text": instructions})

    # Add each slide: image + extracted text
    for slide in slides:
        slide_num = slide["slide_number"]

        # Slide image (rendered PNG)
        img_path = os.path.join(media_dir, "slide_images", f"slide_{slide_num}.png")
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64,
                },
            })

        # Extracted text + image references
        texts = _extract_text_from_shapes(slide.get("shapes", []))
        image_refs = _get_image_refs(slide.get("shapes", []), presentation_id)

        slide_info = f"\n--- Slide {slide_num} of {total} ---"

        bg = slide.get("background", {})
        if bg.get("type") == "image" and bg.get("image_path"):
            filename = bg["image_path"].replace("media/", "", 1)
            slide_info += f"\nBackground image: /api/v1/media/{presentation_id}/{filename}"

        if texts:
            slide_info += "\nText content:\n" + "\n".join(f"  - {t}" for t in texts)
        if image_refs:
            slide_info += "\nImages on this slide:\n" + "\n".join(f"  [img] {url}" for url in image_refs)
        if not texts and not image_refs:
            slide_info += "\n  (Visual/decorative slide — no extractable text)"

        content_blocks.append({"type": "text", "text": slide_info})

    # ── Call Claude API ──
    logger.info(
        "Calling Claude API for webpage generation (model=%s, slides=%d)...",
        settings.CLAUDE_MODEL, total,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=16384,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return None

    html_content = response.content[0].text

    # Clean up — remove markdown fencing if present
    if html_content.strip().startswith("```"):
        lines = html_content.strip().split("\n")
        # Remove first line (```html) and last line (```)
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    # Validate we got HTML
    if "<!DOCTYPE" not in html_content.upper() and "<html" not in html_content.lower():
        logger.warning(
            "Generated content may not be valid HTML (%d chars). Saving anyway.",
            len(html_content),
        )

    # Save the webpage
    webpage_path = os.path.join(pres_dir, "webpage.html")
    with open(webpage_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(
        "Webpage generated successfully: %s (%d chars, stop_reason=%s)",
        webpage_path,
        len(html_content),
        response.stop_reason,
    )

    if response.stop_reason == "max_tokens":
        logger.warning(
            "Response was truncated (max_tokens reached). "
            "The HTML may be incomplete. Consider increasing max_tokens."
        )

    return webpage_path
