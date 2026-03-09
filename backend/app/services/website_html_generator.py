"""Generate a beautiful multi-slide HTML presentation from crawled website content.

The key insight: each crawled PAGE should produce MULTIPLE presentation slides.
A homepage with 5 sections becomes 5+ slides, not 1 slide.
This creates a proper pitch-deck style presentation.

Token optimization: if a template shell exists (from any prior generation), Claude
only generates the slide <div> elements — not the full HTML document.  This cuts
output tokens by ~50-60%.
"""

import os
import json
import base64
import logging
import re
from io import BytesIO
from pathlib import Path

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


def _compress_screenshot_to_jpeg(png_path: str, quality: int = 75) -> tuple[str, str]:
    """Compress a PNG screenshot to JPEG for Claude API input (fewer tokens).

    Returns (base64_data, media_type).
    """
    try:
        from PIL import Image as PILImage
        img = PILImage.open(png_path)
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
    except Exception:
        # Fallback: use raw PNG
        with open(png_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8"), "image/png"

_REFERENCE_PATH = Path(__file__).parent / "reference_style.html"
_REFERENCE_HTML = ""
if _REFERENCE_PATH.exists():
    _REFERENCE_HTML = _REFERENCE_PATH.read_text(encoding="utf-8")


def _analyse_template_brightness(image_path: str) -> str:
    """Analyse a background template image to determine if it's light or dark.

    Returns 'light' or 'dark'.
    """
    try:
        from PIL import Image as PILImage
        img = PILImage.open(image_path).convert("RGB")
        # Sample the image (resize to small for speed)
        img = img.resize((50, 50))
        pixels = list(img.getdata())
        # Calculate average perceived brightness using luminance formula
        total_brightness = sum(
            0.299 * r + 0.587 * g + 0.114 * b
            for r, g, b in pixels
        )
        avg_brightness = total_brightness / len(pixels)
        # Threshold: 128 is mid-point on 0-255 scale
        return "light" if avg_brightness > 140 else "dark"
    except Exception as e:
        logger.warning("Could not analyse template brightness: %s", e)
        return "dark"  # Default to dark assumption


def generate_website_webpage(
    presentation_id: int,
    slides_json_path: str,
    media_dir: str,
    pres_dir: str,
    background_template_path: str | None = None,
) -> dict | None:
    """Generate an HTML slideshow from crawled website data using Claude API.

    Uses a two-path strategy for token optimization:
    - Path A (template): If any prior webpage.html exists, extract the static shell
      and ask Claude to generate ONLY the slide <div> elements.  ~50-60% fewer tokens.
    - Path B (full): First-ever generation with no template — full HTML output.

    Returns a dict with 'webpage_path', 'token_usage', and 'generation_mode'.
    """
    api_key = settings.CLAUDE_API_KEY
    if not api_key:
        logger.warning("CLAUDE_API_KEY not set — skipping webpage generation.")
        return None

    with open(slides_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    slides = data["slides"]
    title = data.get("title", "Website Presentation")
    source_url = data.get("source_url", "")
    total_pages = len(slides)

    if total_pages == 0:
        logger.warning("No pages crawled — skipping webpage generation.")
        return None

    # Build screenshot URL map
    screenshot_url_map = {}
    for slide in slides:
        sp = slide.get("screenshot_path", "")
        if sp:
            filename = sp.replace("media/", "", 1)
            screenshot_url_map[f"page_{slide.get('slide_number', 0)}"] = (
                f"/api/v1/media/{presentation_id}/{filename}"
            )

    # ── TOKEN OPTIMIZATION: Try template-based generation first ──
    from app.services.html_template import (
        get_template, build_static_template, inject_slides,
        cache_template_from_webpage, apply_background_to_template,
    )

    template_brightness = "dark"
    if background_template_path and os.path.exists(background_template_path):
        template_brightness = _analyse_template_brightness(background_template_path)

    template_shell = get_template()
    if template_shell is None:
        # Try building from reference_style.html
        template_shell = build_static_template(background_template_path, template_brightness)
        if not template_shell or "<!-- SLIDES_PLACEHOLDER -->" not in template_shell:
            template_shell = None

    if template_shell:
        # PATH A: Template-based generation (slides only)
        logger.info(
            "Using template-based generation for presentation %d (saves ~50%% output tokens)",
            presentation_id,
        )
        # Apply the correct background to the template
        template_shell = apply_background_to_template(
            template_shell, background_template_path, template_brightness,
        )
        result = _generate_slides_only(
            presentation_id, slides, title, source_url, total_pages,
            screenshot_url_map, media_dir, pres_dir,
            background_template_path, template_brightness,
            template_shell,
        )
        if result:
            result["generation_mode"] = "template"
        return result

    # PATH B: Full generation (first-ever, no template available)
    logger.info("No template available — using full generation for presentation %d", presentation_id)
    result = _generate_full_html(
        presentation_id, slides, title, source_url, total_pages,
        screenshot_url_map, media_dir, pres_dir,
        background_template_path, template_brightness,
    )
    if result:
        result["generation_mode"] = "full"
        # Cache the template for future use
        cache_template_from_webpage(result["webpage_path"])
    return result


def _generate_slides_only(
    presentation_id: int,
    slides: list,
    title: str,
    source_url: str,
    total_pages: int,
    screenshot_url_map: dict,
    media_dir: str,
    pres_dir: str,
    background_template_path: str | None,
    template_brightness: str,
    template_shell: str,
) -> dict | None:
    """Generate ONLY slide <div> elements via Claude, then inject into the template.

    This is the token-optimized path — output tokens reduced by ~50-60%.
    """
    from app.services.html_template import inject_slides
    from app.services.extraction.progress import is_cancelled

    api_key = settings.CLAUDE_API_KEY
    content_blocks = []

    # ── Build the SHORTER prompt (no CSS/JS/toolbar/navigation instructions) ──
    bg_template_instruction = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name = os.path.basename(background_template_path)
        if template_brightness == "light":
            contrast_instruction = (
                "- LIGHT background: use DARK text (#0f172a, #1e293b, #334155). "
                "Cards: rgba(255,255,255,0.7) with backdrop-filter blur."
            )
        else:
            contrast_instruction = (
                "- DARK background: use LIGHT text (#f1f5f9, #e2e8f0, #cbd5e1). "
                "Cards: rgba(30,41,59,0.8) with backdrop-filter blur."
            )
        bg_template_instruction = f"""
## Background Template
Use `background-size: cover` to fill the slide. Background URL: /api/v1/admin/background-templates/{bg_name}
Use separate CSS properties: background-image, background-size, background-position (NOT the shorthand `background:`).
{contrast_instruction}
"""

    instructions = f"""You are an expert presentation designer. Generate ONLY the slide <div> elements for an HTML presentation.

## OUTPUT FORMAT — CRITICAL
- Output ONLY a sequence of <div class="slide">...</div> elements
- Do NOT output <!DOCTYPE>, <html>, <head>, <style>, <script>, or any other wrapper
- Start your output directly with the first <div class="slide"> and end with the last </div>
- Each slide MUST use class="slide" and contain a <div class="zoom-wrapper"> inside it

## Slide Structure
1. **Title Slide** — Company name, tagline, hero visual. Big, bold.
2. **Overview Slide** — What the company/product does. 2-3 bullet points.
3. **Feature/Product Slides** (one per feature) — headline + 2-4 bullets + screenshot
4. **Stats/Metrics Slide** — Any numbers, counts, metrics
5. **Details Slides** — Deeper content: how it works, categories, use cases
6. **Summary/CTA Slide** — Final slide with key takeaway

## Design Rules
- {"Light theme: DARK text (#0f172a, #1e293b, #334155)" if template_brightness == "light" and background_template_path else "Dark theme: LIGHT text (#f1f5f9, #e2e8f0, #cbd5e1)"}
- Gradient accents: linear-gradient(135deg, #6366f1, #06b6d4)
- {"Glassmorphism cards: background rgba(255,255,255,0.7), backdrop-filter blur" if template_brightness == "light" and background_template_path else "Glassmorphism cards: background rgba(30,41,59,0.8), backdrop-filter blur"}
- Each slide: position absolute, inset 0, 100vw x 100vh, overflow hidden
- Padding: 60px top/bottom, 100px left/right
{bg_template_instruction}

## Website Images — EVERY image MUST appear with its NAME displayed!
**CRITICAL IMAGE RULES:**
1. EVERY provided image MUST appear in the presentation
2. NAME must be visible below every image — MANDATORY
3. For people/team photos, use:
```html
<div class="person-card">
  <img class="team-photo" src="IMAGE_URL" alt="NAME" style="width:120px;height:120px;border-radius:50%;object-fit:cover;">
  <div class="person-name">PERSON NAME</div>
  <div class="person-role">ROLE/TITLE</div>
</div>
```
4. Wrap person cards in: <div class="team-grid">...</div>
5. MAX 6-8 people per slide — create MULTIPLE team slides if needed

## Screenshots
Use these URLs for page screenshots:
{json.dumps(screenshot_url_map, indent=2)}

- Two-column layouts: add class="two-col" to the flex container
- Text column: 55%, Image column: 38%, gap 40px
- Screenshot images: max-width:38%; max-height:36vh; object-fit:contain

## LAYOUT RULES
- EVERY slide MUST fit 100vw x 100vh. NO overflow.
- MAX 3 content cards per slide. EXCEPTION: team-grid can have 6-8 person-cards.
- Max 3 bullet points per slide, short sentences
- Create at LEAST 10-15 slides — each section/feature = its own slide
- Content overflowing the viewport is a CRITICAL BUG

## Presentation Info
- Title: "{title}"
- Source: {source_url}
- Presentation ID: {presentation_id}
- Pages crawled: {total_pages}

## Website Content
"""

    content_blocks.append({"type": "text", "text": instructions})

    # ── Add screenshots (JPEG compressed) + content for each page ──
    _append_page_content_blocks(
        content_blocks, slides, total_pages, screenshot_url_map,
        media_dir, presentation_id,
    )

    # Final reminder (shorter version)
    bg_reminder = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name = os.path.basename(background_template_path)
        bg_reminder = f" Use background-size:cover for the template image."
    content_blocks.append({
        "type": "text",
        "text": (
            "\n\nREMINDER: Create at LEAST 10-15 slides. Output ONLY <div class=\"slide\"> elements. "
            "No DOCTYPE, no <html>, no <head>, no <style>, no <script>."
            f"{bg_reminder}\n"
            "ALL provided images MUST appear with their NAME visible. "
            "Missing names = CRITICAL BUG. Use class='person-card' and class='team-grid'."
        ),
    })

    # ── Call Claude API ──
    if is_cancelled(presentation_id):
        return None

    logger.info(
        "Calling Claude API (SLIDES ONLY mode, model=%s, pages=%d)...",
        settings.CLAUDE_MODEL, total_pages,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        html_parts = []
        token_usage = None
        with client.messages.stream(
            model=settings.CLAUDE_MODEL,
            max_tokens=32000,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            for text in stream.text_stream:
                html_parts.append(text)
                if len(html_parts) % 50 == 0 and is_cancelled(presentation_id):
                    return None
            final_message = stream.get_final_message()
            if hasattr(final_message, "usage") and final_message.usage:
                token_usage = {
                    "input_tokens": final_message.usage.input_tokens,
                    "output_tokens": final_message.usage.output_tokens,
                }
    except Exception as e:
        logger.error("Claude API call failed (slides-only): %s", e)
        return None

    slides_html = "".join(html_parts)

    # Clean up: strip markdown fencing if present
    if slides_html.strip().startswith("```"):
        lines = slides_html.strip().split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        slides_html = "\n".join(lines)

    # Strip anything before first <div class="slide" and after last </div>
    first_slide = re.search(r'<div\s+class="slide', slides_html)
    if first_slide:
        slides_html = slides_html[first_slide.start():]

    # Inject into template
    html_content = inject_slides(template_shell, slides_html)

    # Save
    webpage_path = os.path.join(pres_dir, "webpage.html")
    with open(webpage_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(
        "Website webpage generated (TEMPLATE mode): %s (%d chars, tokens=%s)",
        webpage_path, len(html_content), token_usage,
    )

    return {
        "webpage_path": webpage_path,
        "token_usage": token_usage,
    }


def _append_page_content_blocks(
    content_blocks: list,
    slides: list,
    total_pages: int,
    screenshot_url_map: dict,
    media_dir: str,
    presentation_id: int,
) -> None:
    """Append screenshot images + extracted text for each page to the content blocks.

    Used by both _generate_slides_only() and _generate_full_html().
    Screenshots are JPEG-compressed for fewer input tokens.
    """
    for idx, slide in enumerate(slides):
        slide_num = slide.get("slide_number") or slide.get("page_number", idx + 1)
        page_url = slide.get("page_url", "")
        page_title = slide.get("page_title", f"Page {slide_num}")
        content = slide.get("content", {})

        # Page screenshot (JPEG compressed for fewer tokens)
        screenshot_path_rel = slide.get("screenshot_path", "")
        if screenshot_path_rel:
            filename = screenshot_path_rel.replace("media/", "", 1)
            screenshot_abs = os.path.join(media_dir, filename)
            if not os.path.exists(screenshot_abs):
                screenshot_abs = os.path.join(os.path.dirname(media_dir), screenshot_path_rel)

            if os.path.exists(screenshot_abs):
                img_b64, media_type = _compress_screenshot_to_jpeg(screenshot_abs)
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_b64,
                    },
                })

        screenshot_url = screenshot_url_map.get(f"page_{slide_num}", "")

        # Build text description
        page_info = f"\n{'='*60}\nPAGE {slide_num} of {total_pages}: {page_title}\n{'='*60}"
        page_info += f"\nURL: {page_url}"
        if screenshot_url:
            page_info += f"\nScreenshot <img> URL: {screenshot_url}"

        if content.get("meta_description"):
            page_info += f"\nDescription: {content['meta_description']}"

        if content.get("sections"):
            page_info += f"\n\nSECTIONS ({len(content['sections'])} found):"
            for section in content["sections"]:
                page_info += f"\n  [{section['level'].upper()}] {section['heading']}"
                for text in section.get("content", []):
                    page_info += f"\n    - {text}"

        if content.get("cards"):
            page_info += f"\n\nCARDS/FEATURES ({len(content['cards'])} found):"
            for card in content["cards"]:
                page_info += f"\n  - {card}"

        if content.get("list_items"):
            page_info += f"\n\nLIST ITEMS:"
            for item in content["list_items"]:
                page_info += f"\n  - {item}"

        if content.get("key_paragraphs"):
            page_info += "\n\nKEY CONTENT:"
            for para in content["key_paragraphs"]:
                page_info += f"\n  {para}"

        if content.get("images"):
            img_count = len(content["images"])
            named_imgs = [img for img in content["images"] if img.get("name")]
            page_info += f"\n\n{'='*40}"
            page_info += f"\nIMAGES FOUND: {img_count} total ({len(named_imgs)} with names)"
            page_info += f"\nYou MUST include ALL {img_count} images with their NAME displayed!"
            if img_count > 8:
                slides_needed = (img_count + 7) // 8
                page_info += f"\nCreate {slides_needed}+ team slides (max 6-8 per slide)"
            page_info += f"\n{'='*40}"
            for i, img in enumerate(content["images"], 1):
                page_info += f"\n  [{i}/{img_count}] IMAGE:"
                page_info += f"\n    URL: {img['src']}"
                page_info += f"\n    NAME: {img.get('name') or '(unnamed)'}"
                page_info += f"\n    ROLE: {img.get('role') or '(no role)'}"
                if img.get("alt"):
                    page_info += f"\n    ALT: {img['alt']}"
                if img.get("description"):
                    page_info += f"\n    INFO: {img['description']}"

        if content.get("nav_items"):
            page_info += f"\n\nNavigation: {', '.join(content['nav_items'][:10])}"

        content_blocks.append({"type": "text", "text": page_info})


def _generate_full_html(
    presentation_id: int,
    slides: list,
    title: str,
    source_url: str,
    total_pages: int,
    screenshot_url_map: dict,
    media_dir: str,
    pres_dir: str,
    background_template_path: str | None,
    template_brightness: str,
) -> dict | None:
    """Full HTML generation (original flow) — used only when no template exists."""
    api_key = settings.CLAUDE_API_KEY

    # ── Background template handling ──
    bg_template_instruction = ""
    bg_template_b64 = None
    if background_template_path and os.path.exists(background_template_path):
        # Compress background template too
        bg_template_b64, _ = _compress_screenshot_to_jpeg(background_template_path, quality=70)
        bg_name = os.path.basename(background_template_path)
        logger.info("Template '%s' brightness: %s", bg_name, template_brightness)

        if template_brightness == "light":
            contrast_instruction = """
- **CRITICAL: This is a LIGHT background template!**
- You MUST use DARK text colors for readability: #0f172a, #1e293b, #334155 for body text
- Headings: #0f172a or #1e293b (very dark)
- Body text: #334155 or #475569
- Muted text: #64748b
- Accent colors: #4f46e5, #6366f1 (indigo) — these work on both light and dark
- Card backgrounds: rgba(255,255,255,0.7) with backdrop-filter blur
- Borders: rgba(0,0,0,0.1)
- DO NOT use light/white text — it will be invisible on this light background!
- Use a semi-transparent dark overlay if needed: linear-gradient(rgba(255,255,255,0.6), rgba(255,255,255,0.7))
"""
        else:
            contrast_instruction = """
- This is a DARK background template — use LIGHT text as usual
- Text colors: #f1f5f9, #e2e8f0, #cbd5e1
- Card backgrounds: rgba(30,41,59,0.8) with backdrop-filter blur
- Use a semi-transparent dark overlay: linear-gradient(rgba(15,23,42,0.75), rgba(15,23,42,0.85))
"""

        if template_brightness == "light":
            overlay_css = "linear-gradient(rgba(255,255,255,0.15), rgba(255,255,255,0.15))"
        else:
            overlay_css = "linear-gradient(rgba(15,23,42,0.35), rgba(15,23,42,0.45))"

        bg_template_instruction = f"""
## Background Template — MANDATORY
The user has selected a specific background template image: "{bg_name}"
**YOU MUST use this ACTUAL IMAGE as the CSS background-image on EVERY .slide element.**
This is NOT optional. Do NOT recreate it with gradients. Do NOT use a solid color instead.

**REQUIRED CSS for EVERY .slide:**
```css
.slide {{
  background-image: {overlay_css}, url('/api/v1/admin/background-templates/{bg_name}') !important;
  background-size: cover, cover !important;
  background-position: center center !important;
  background-repeat: no-repeat !important;
}}
```

- The image URL is: /api/v1/admin/background-templates/{bg_name}
- Apply this to every single .slide element — no exceptions
- CRITICAL: Use `background-size: cover` so the template fills the entire slide without gaps
- Use separate `background-image`, `background-size`, `background-position` properties (NOT the shorthand `background:`)
- Add a subtle semi-transparent overlay on top for text readability
- The overlay should be thin enough that the background image is clearly visible through it
- Do NOT use solid color backgrounds — the actual template image must be visible on every slide
{contrast_instruction}
"""

    # ── Build Claude API message ──
    content_blocks = []

    instructions = f"""You are an expert presentation designer. Create a professional, multi-slide HTML presentation from the website content below.

## CRITICAL: This must be a REAL PRESENTATION with MANY slides
- You MUST create **at least 10-15 slides** (more if the content supports it)
- Each major section, feature, or product from the website = its OWN dedicated slide
- Do NOT cram multiple topics into one slide
- Do NOT create just 1 slide per crawled page — break each page into MULTIPLE slides

## Slide Structure (follow this pattern):
1. **Title Slide** — Company/product name, tagline, hero visual. Big, bold, cinematic.
2. **Overview/About Slide** — What the company/product does. 2-3 key bullet points.
3. **Feature/Product Slides** (one per feature) — Each product, feature, or service gets its OWN slide with:
   - A compelling headline
   - 2-4 bullet points or a short description
   - The relevant screenshot shown as an elegant framed image
4. **Stats/Metrics Slide** — Any numbers, counts, metrics found (e.g., "14+ Active Apps")
5. **Details Slides** — Deeper content: how it works, categories, use cases
6. **Summary/CTA Slide** — Final slide with key takeaway and call to action

## Style Reference
Use this exact design language:
```html
{_REFERENCE_HTML}
```

## Design Rules
- {"Light theme due to template: use DARK text (#0f172a, #1e293b, #334155) for contrast" if template_brightness == "light" and bg_template_b64 else "Dark theme: #0f172a background, light text (#f1f5f9, #e2e8f0, #cbd5e1)"}
- Gradient accents: linear-gradient(135deg, #6366f1, #06b6d4) for highlights
- Card-based layouts with subtle borders
- Professional typography: Inter font family, varied weights
- {"NEVER use light/white text — the background is LIGHT, use dark text for contrast!" if template_brightness == "light" and bg_template_b64 else "NEVER use dark/black text — everything must be light colored"}
- {"Use glassmorphism cards: background rgba(255,255,255,0.7), backdrop-filter blur, borders rgba(0,0,0,0.1)" if template_brightness == "light" and bg_template_b64 else "Use glassmorphism cards: background rgba(30,41,59,0.8), backdrop-filter blur"}
- Each slide: position absolute, inset 0, 100vw x 100vh, overflow hidden
- Padding: 60px top/bottom, 100px left/right (for nav zones)
{bg_template_instruction}

## Website Images — EVERY image MUST appear with its NAME displayed!
Each page may have extracted images with their associated text (person name + role, product name, etc.).
The images are ALREADY MAPPED to the correct person/item — **you MUST use each image with its matching name/role.**

**CRITICAL IMAGE RULES — STRICT COMPLIANCE REQUIRED:**
1. **EVERY provided image MUST appear in the presentation** — do NOT skip any images
2. Each image entry includes: URL, NAME, ROLE/TITLE — you MUST display ALL THREE
3. **NAME must be visible below every image** — this is MANDATORY, not optional
4. For people/team photos, use this EXACT HTML structure for each person:
```html
<div class="person-card">
  <img class="team-photo" src="IMAGE_URL" alt="NAME" style="width:120px;height:120px;border-radius:50%;object-fit:cover;">
  <div class="person-name">PERSON NAME</div>
  <div class="person-role">ROLE/TITLE</div>
</div>
```
5. Wrap all person cards in a grid container:
```html
<div class="team-grid">
  <!-- person-card elements here -->
</div>
```
6. **MAX 6-8 people per slide** — if there are more, create MULTIPLE team slides (e.g., "Our Team (1/3)", "Our Team (2/3)", etc.)
7. **ALL images must be included** — split across as many slides as needed
8. For product/feature images: use rectangular with rounded corners (border-radius: 12px; object-fit: cover;)
9. Use the EXACT image URLs provided — they are absolute URLs from the original website
10. For two-column layouts with screenshots, add class="two-col" to the flex container

## Screenshots — STRICT SIZING (images must NEVER exceed boundaries)
Use these EXACT URLs for page screenshots in <img> tags:
{json.dumps(screenshot_url_map, indent=2)}

**Screenshot display rules:**
- Display screenshots as elegant framed previews inside cards
- Use: border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1)
- **SIZE: max-width: 38%; max-height: 36vh; width: auto; height: auto; object-fit: contain**
- For slides that feature a screenshot, use a TWO-COLUMN flex row layout:
  - Container: display:flex; align-items:center; gap:40px; max-height:65vh; overflow:hidden;
  - Left column: flex:1 1 55%; max-width:55%; — text content (heading, bullets)
  - Right column: flex:0 0 38%; max-width:38%; text-align:center; display:flex; align-items:center; justify-content:center;
  - Image inside right column: max-width:90%; max-height:36vh; object-fit:contain; display:block; margin:0 auto;
- **CRITICAL: The image column MUST NOT exceed 40% of the slide width. The image must be CENTERED within its column, with visible space on all sides. It must NEVER touch or extend past the right edge of the slide.**
- Screenshots are supplementary — they should fit alongside text, not dominate the slide
- When in doubt, make the screenshot SMALLER. A small, well-centered screenshot is far better than a large one that overflows.

## Navigation & Controls
- Full-height side zones (80px wide, class="nav-zone") for prev/next with gradient + arrow on hover
- Keyboard: arrows, space, Home, End
- Touch swipe support
- Progress bar at top
- Slide counter at bottom-right
- Back button top-left linking to "/"
- TOOLBAR (bottom-left, fixed, class="toolbar"): magnifying glass zoom, +/- zoom, zoom %, reset, separator, pen (red 3px), highlighter (yellow 20px semi-transparent), clear drawings, separator, EYE ICON toggle (toggles nav arrow zones visible/hidden). Canvas overlay for drawing. Disable keyboard nav when drawing.
- Wrap each slide content in <div class="zoom-wrapper">

## CRITICAL LAYOUT RULES — Content MUST Fit Screen (NO EXCEPTIONS)
- EVERY slide MUST fit within 100vw x 100vh. NO scrolling, NO overflow. ZERO tolerance.
- **MAX 3 CONTENT CARDS per slide for features/services.** If you have 4+ feature items, SPLIT across 2+ slides. EXCEPTION: team/people grids using class="team-grid" can have 6-8 person-cards per slide.
- Keep content concise: max 3 bullet points per slide, short sentences (max 12 words each)
- Use font-size clamp: h1 clamp(1.3rem,3.2vw,2.5rem), h2 clamp(1rem,2.5vw,1.8rem), p clamp(0.7rem,1.2vw,0.95rem)
- .zoom-wrapper padding: 50px 90px (leaves room for nav zones)
- **TWO-COLUMN SLIDES (text + screenshot):** use class="two-col" on the container: display:flex; align-items:center; gap:40px; max-height:65vh; overflow:hidden;
  - Text column: flex:1 1 55%; max-width:55%; max 3-4 short bullet points
  - Image column: flex:0 0 38%; max-width:38%; text-align:center; display:flex; align-items:center; justify-content:center;
  - Image inside column: max-width:90%; max-height:36vh; object-fit:contain; display:block; margin:0 auto;
  - The image must be CENTERED in its column with visible padding on all sides — it must NEVER touch the right edge of the slide
- **TEAM/PEOPLE SLIDES:** use class="team-grid" wrapper with class="person-card" for each person. Max 6-8 people per slide, split into multiple slides if needed.
- Card heights: max-height 25vh per card. Grid gaps: 16px max. overflow:hidden on every card.
- **EVERY card/box MUST have overflow:hidden** in its inline style
- CTA/final slides: keep it to heading + 2-3 short lines + 1 button. Do NOT put long URLs in visible text.
- NEVER let content exceed the viewport — MORE slides with LESS content is always better than overflowing
- Test mentally: if total content height exceeds ~75vh (leaving 25vh for padding/heading), SPLIT into 2 slides.

## Output Requirements
- Output ONLY raw HTML. Start with <!DOCTYPE html>, end with </html>. No markdown fencing.
- Completely self-contained: all CSS in <style>, all JS in <script>
- Smooth transitions between slides (opacity + subtle transform)
- MINIMUM 10 slides, aim for 12-20 depending on content richness

## Presentation Info
- Title: "{title}"
- Source: {source_url}
- Presentation ID: {presentation_id}
- Pages crawled: {total_pages}

## Website Content
Below are the crawled pages with screenshots and extracted text. Use ALL of this content
to create a comprehensive presentation. Break each page into multiple slides.
"""

    content_blocks.append({"type": "text", "text": instructions})

    # Include background template image for Claude to see
    if bg_template_b64:
        content_blocks.append({"type": "text", "text": "\n--- BACKGROUND TEMPLATE IMAGE (use this style for all slides) ---"})
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": bg_template_b64,
            },
        })

    # Add each page's screenshot + extracted content (JPEG compressed)
    _append_page_content_blocks(
        content_blocks, slides, total_pages, screenshot_url_map,
        media_dir, presentation_id,
    )

    # Final reminder
    bg_reminder = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name = os.path.basename(background_template_path)
        bg_reminder = (
            f" BACKGROUND IMAGE IS MANDATORY: Every .slide MUST have "
            f"background-image: url('/api/v1/admin/background-templates/{bg_name}'); "
            f"background-size: cover; background-position: center; "
            f"— the actual image file, NOT a gradient or solid color."
        )
    content_blocks.append({
        "type": "text",
        "text": (
            "\n\nREMINDER: Create at LEAST 10-15 slides from this content. "
            "Each section/feature = its own slide. Make it look like a premium "
            "pitch deck presentation. Use two-column flex layouts for "
            "screenshot slides (text left, image right). Start output with <!DOCTYPE html>.\n\n"
            "**ABSOLUTE RULES — VIOLATIONS = CRITICAL BUGS:**\n"
            "1. MAX 3 CONTENT CARDS PER SLIDE for features/services. EXCEPTION: team/people grids can have 6-8 person cards per slide using class='team-grid'.\n"
            "2. Screenshot images: max-width:38%; max-height:36vh; object-fit:contain. "
            "The image column must be max-width:38%. Image must be CENTERED in its column.\n"
            "3. Every content card/box MUST have overflow:hidden in its style (but NOT person-card elements).\n"
            "4. All text inside cards must fit — keep card content to heading + 2 short lines max.\n"
            "5. CTA/final slide: heading + 2 lines + button. No long URLs in visible text.\n"
            "6. Content overflowing beyond the viewport is a CRITICAL BUG.\n"
            "7. TWO-COLUMN layouts: add class='two-col' to the flex container. Text column 55%, image column 38%, gap 40px.\n"
            "8. **ALL provided images MUST appear with their NAME visible below the photo.** Missing names = CRITICAL BUG.\n"
            "9. Use class='person-card' for each team member, class='team-grid' for the grid container.\n"
            "10. If there are many team/people images, create MULTIPLE slides to show them ALL."
            + bg_reminder
        ),
    })

    # ── Call Claude API (streaming) ──
    from app.services.extraction.progress import is_cancelled

    logger.info(
        "Calling Claude API for website presentation (model=%s, pages=%d)...",
        settings.CLAUDE_MODEL, total_pages,
    )

    # Check cancellation before starting expensive API call
    if is_cancelled(presentation_id):
        logger.info("Generation cancelled before API call for presentation %d", presentation_id)
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        html_parts = []
        stop_reason = None
        token_usage = None
        with client.messages.stream(
            model=settings.CLAUDE_MODEL,
            max_tokens=64000,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            for text in stream.text_stream:
                html_parts.append(text)
                # Check cancellation periodically during streaming
                if len(html_parts) % 50 == 0 and is_cancelled(presentation_id):
                    logger.info("Generation cancelled during streaming for presentation %d", presentation_id)
                    return None
            final_message = stream.get_final_message()
            stop_reason = final_message.stop_reason
            # Capture token usage
            if hasattr(final_message, "usage") and final_message.usage:
                token_usage = {
                    "input_tokens": final_message.usage.input_tokens,
                    "output_tokens": final_message.usage.output_tokens,
                }
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return None

    html_content = "".join(html_parts)

    # Clean up markdown fencing
    if html_content.strip().startswith("```"):
        lines = html_content.strip().split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    if "<!DOCTYPE" not in html_content.upper() and "<html" not in html_content.lower():
        logger.warning(
            "Generated content may not be valid HTML (%d chars). Saving anyway.",
            len(html_content),
        )

    # ── Post-processing ──
    # Conditional text color based on template brightness
    if template_brightness == "light" and bg_template_b64:
        text_color_rule = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#1e293b !important;}\n'
        )
    else:
        text_color_rule = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#f1f5f9 !important;}\n'
        )

    # Build background image CSS rule if template selected
    bg_image_css = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name_css = os.path.basename(background_template_path)
        if template_brightness == "light":
            overlay = "linear-gradient(rgba(255,255,255,0.15),rgba(255,255,255,0.15))"
        else:
            overlay = "linear-gradient(rgba(15,23,42,0.35),rgba(15,23,42,0.45))"
        bg_image_css = (
            f'/* Force background template image on every slide */\n'
            f'.slide{{\n'
            f"  background-image:{overlay},url('/api/v1/admin/background-templates/{bg_name_css}') !important;\n"
            f'  background-size:cover,cover !important;\n'
            f'  background-position:center center !important;\n'
            f'  background-repeat:no-repeat !important;\n'
            f'}}\n'
        )

    safety_css = (
        '\n<style id="safety-overrides">\n'
        + text_color_rule
        + bg_image_css +
        '.tag,.pill,.badge,.kpi-label,.metric-mini .label,.chart-bar span'
        '{color:inherit !important;}\n'
        '.gradient-text{-webkit-text-fill-color:transparent !important;'
        'background-clip:text !important;}\n'
        '/* === STRICT SLIDE CONTAINMENT — ZERO OVERFLOW === */\n'
        '.slide,.slide-container,[class*="slide"]:not(.slide-counter):not(.slide-nav){\n'
        '  overflow:hidden !important;\n'
        '  max-height:100vh !important;\n'
        '  height:100vh !important;\n'
        '  width:100vw !important;\n'
        '  position:absolute !important;\n'
        '  box-sizing:border-box !important;\n'
        '}\n'
        '.slide *{box-sizing:border-box !important;}\n'
        '/* Zoom wrapper / content wrapper must stay within slide */\n'
        '.zoom-wrapper,.slide-content,.slide>[class*="content"],.slide>[class*="wrapper"],.slide>div{\n'
        '  max-height:100vh !important;\n'
        '  overflow:hidden !important;\n'
        '  box-sizing:border-box !important;\n'
        '}\n'
        '.zoom-wrapper,.slide-content,.slide>[class*="content"],.slide>[class*="wrapper"]{\n'
        '  padding:50px 90px !important;\n'
        '}\n'
        '/* Headings: clamp sizes aggressively */\n'
        '.slide h1{font-size:clamp(1.3rem,3.2vw,2.5rem) !important;line-height:1.1 !important;margin-bottom:0.3em !important;}\n'
        '.slide h2{font-size:clamp(1rem,2.5vw,1.8rem) !important;line-height:1.15 !important;margin-bottom:0.25em !important;}\n'
        '.slide h3{font-size:clamp(0.9rem,2vw,1.3rem) !important;line-height:1.2 !important;margin-bottom:0.2em !important;}\n'
        '.slide p,.slide li{font-size:clamp(0.7rem,1.2vw,0.95rem) !important;line-height:1.3 !important;margin-bottom:0.25em !important;}\n'
        '/* Prevent any element from exceeding viewport */\n'
        '.slide>*,.zoom-wrapper>*{max-width:100% !important;}\n'
        '/* Card/grid containment — strict height limits (not for team-grid) */\n'
        '.slide [style*="display:grid"]:not(.team-grid):not(.people-grid),\n'
        '.slide [style*="display: grid"]:not(.team-grid):not(.people-grid){\n'
        '  grid-template-columns:repeat(auto-fit,minmax(180px,1fr)) !important;\n'
        '  max-height:60vh !important;\n'
        '  overflow:hidden !important;\n'
        '  gap:14px !important;\n'
        '}\n'
        '.slide [style*="display:flex"],.slide [style*="display: flex"]{\n'
        '  max-height:70vh !important;\n'
        '  overflow:hidden !important;\n'
        '  max-width:100% !important;\n'
        '}\n'
        '/* Individual cards — strict height limit + clip content */\n'
        '.slide [class*="card"]:not(.person-card),.slide [class*="Card"]:not(.person-card),'
        '.slide [class*="feature"],.slide [class*="Feature"],'
        '.slide [class*="box"],.slide [class*="Box"],'
        '.slide [class*="service"],.slide [class*="Service"],.slide [class*="benefit"],.slide [class*="Benefit"],'
        '.slide [class*="cta"],.slide [class*="CTA"],.slide [class*="action"],.slide [class*="Action"]{\n'
        '  max-height:25vh !important;\n'
        '  overflow:hidden !important;\n'
        '  padding:clamp(10px,1.5vh,20px) clamp(12px,1.5vw,24px) !important;\n'
        '}\n'
        '/* NOTE: nth-child grid hiding REMOVED — team/people grids need 6-8+ items per slide */\n'
        '/* ── IMAGE CONTAINMENT — SCREENSHOT images (from /api/v1/media/) must NEVER exceed slide ── */\n'
        '.slide img[src*="/api/v1/media/"]{\n'
        '  max-width:38vw !important;\n'
        '  max-height:36vh !important;\n'
        '  width:auto !important;\n'
        '  height:auto !important;\n'
        '  object-fit:contain !important;\n'
        '  border-radius:12px;\n'
        '}\n'
        '/* ── Two-column layouts (text + screenshot): STRICT width constraints ── */\n'
        '/* Only apply to 2-child flex containers (two-column layouts), not team grids */\n'
        '.slide .two-col>*:first-child{\n'
        '  overflow:hidden !important;\n'
        '  min-width:0 !important;\n'
        '  max-width:55% !important;\n'
        '  flex:1 1 55% !important;\n'
        '}\n'
        '.slide .two-col>*:last-child{\n'
        '  max-width:42% !important;\n'
        '  flex:0 0 38% !important;\n'
        '  display:flex !important;\n'
        '  align-items:center !important;\n'
        '  justify-content:center !important;\n'
        '}\n'
        '/* Screenshot images inside two-column layouts */\n'
        '.slide .two-col img[src*="/api/v1/media/"]{\n'
        '  max-height:36vh !important;\n'
        '  max-width:90% !important;\n'
        '  width:auto !important;\n'
        '  height:auto !important;\n'
        '  object-fit:contain !important;\n'
        '  display:block !important;\n'
        '  margin:0 auto !important;\n'
        '}\n'
        '/* External website images: reasonable sizing without overflow */\n'
        '.slide img[src^="http"]:not([src*="/api/v1/"]){\n'
        '  max-width:200px !important;\n'
        '  max-height:200px !important;\n'
        '  object-fit:cover !important;\n'
        '  display:block !important;\n'
        '}\n'
        '/* Team/people photos — circular style, proper sizing */\n'
        '.slide .team-photo,.slide .person-photo,\n'
        '.slide img[style*="border-radius: 50%"],\n'
        '.slide img[style*="border-radius:50%"]{\n'
        '  width:120px !important;\n'
        '  height:120px !important;\n'
        '  max-width:120px !important;\n'
        '  max-height:120px !important;\n'
        '  object-fit:cover !important;\n'
        '  flex-shrink:0 !important;\n'
        '  border-radius:50% !important;\n'
        '}\n'
        '/* Grid/flex of people cards: allow proper flow */\n'
        '.slide .team-grid,.slide .people-grid{\n'
        '  display:grid !important;\n'
        '  grid-template-columns:repeat(auto-fill, minmax(140px,1fr)) !important;\n'
        '  gap:20px !important;\n'
        '  max-height:75vh !important;\n'
        '  overflow:hidden !important;\n'
        '  width:100% !important;\n'
        '  max-width:100% !important;\n'
        '}\n'
        '.slide .team-grid>*,.slide .people-grid>*{\n'
        '  max-width:100% !important;\n'
        '  overflow:hidden !important;\n'
        '  text-align:center !important;\n'
        '}\n'
        '/* Person card within team grid: ensure name is visible */\n'
        '.slide .person-card{\n'
        '  display:flex !important;\n'
        '  flex-direction:column !important;\n'
        '  align-items:center !important;\n'
        '  gap:6px !important;\n'
        '  padding:8px !important;\n'
        '  max-height:none !important;\n'
        '  overflow:visible !important;\n'
        '}\n'
        '.slide .person-card .person-name{\n'
        '  font-weight:600 !important;\n'
        '  font-size:clamp(0.65rem,1vw,0.85rem) !important;\n'
        '  line-height:1.2 !important;\n'
        '  text-align:center !important;\n'
        '}\n'
        '.slide .person-card .person-role{\n'
        '  font-size:clamp(0.55rem,0.8vw,0.7rem) !important;\n'
        '  opacity:0.7 !important;\n'
        '  text-align:center !important;\n'
        '}\n'
        '/* Bullet lists: strict limit */\n'
        '.slide ul,.slide ol{max-height:45vh !important;overflow:hidden !important;}\n'
        '.slide ul>li:nth-child(n+5),.slide ol>li:nth-child(n+5){display:none !important;}\n'
        '/* Tables: constrain */\n'
        '.slide table{max-height:50vh !important;overflow:hidden !important;font-size:clamp(0.65rem,1vw,0.85rem) !important;}\n'
        '/* Nav arrow zones — togglable via eye icon */\n'
        '.nav-zone{transition:opacity 0.3s ease !important;opacity:1 !important;}\n'
        '.nav-zones-hidden .nav-zone{opacity:0 !important;}\n'
        '.nav-zones-hidden .nav-zone:hover{opacity:1 !important;pointer-events:auto !important;}\n'
        '</style>\n'
    )

    autofit_js = r"""
<script>
/* ── Auto-fit: scale down slide content if it overflows ── */
function autoFitSlides(){
  document.querySelectorAll('.slide').forEach(function(slide){
    /* Find the content wrapper inside the slide */
    var w = slide.querySelector('.zoom-wrapper')
         || slide.querySelector('.slide-content')
         || slide.querySelector('[class*="content"]')
         || slide.querySelector('[class*="wrapper"]');
    /* Fallback: first direct child div that isn't a nav zone */
    if(!w){
      var children = slide.children;
      for(var i=0;i<children.length;i++){
        var c=children[i];
        if(c.tagName==='DIV' && !c.classList.contains('nav-zone')
           && !c.classList.contains('nav-prev') && !c.classList.contains('nav-next')
           && c.className.indexOf('nav')===-1 && c.offsetHeight>50){
          w=c;break;
        }
      }
    }
    if(!w)return;

    // Reset previous transforms
    w.style.transform='';
    w.style.transformOrigin='top left';

    // Temporarily allow overflow so we can measure true content height
    var prevOverflow=slide.style.overflow;
    var prevWOverflow=w.style.overflow;
    slide.style.overflow='visible';
    w.style.overflow='visible';

    var sh=window.innerHeight;
    var sw=window.innerWidth;
    var wh=w.scrollHeight;
    var ww=w.scrollWidth;

    // Restore overflow
    slide.style.overflow=prevOverflow||'';
    w.style.overflow=prevWOverflow||'';

    // Scale based on whichever dimension overflows more
    var scaleH = wh > sh*0.90 ? (sh*0.86)/wh : 1;
    var scaleW = ww > sw*0.95 ? (sw*0.90)/ww : 1;
    var scale = Math.min(scaleH, scaleW);

    if(scale < 0.98){
      scale = Math.max(0.30, scale);
      w.style.transform='scale('+scale+')';
      w.style.transformOrigin='top left';
      // Adjust visual width so the slide doesn't have empty space on the right
      w.style.width=(100/scale)+'%';
    }

    // Force clip on slide regardless
    slide.style.overflow='hidden';
  });
}
/* Run multiple passes to catch late-rendering content */
window.addEventListener("load",function(){
  setTimeout(autoFitSlides,200);
  setTimeout(autoFitSlides,600);
  setTimeout(autoFitSlides,1500);
  setTimeout(autoFitSlides,3000); // final pass after lazy images
});
window.addEventListener("resize",function(){setTimeout(autoFitSlides,150);});

/* ── Eye icon: toggle nav arrow visibility ── */
/* Default: arrows always visible.
   Click eye: arrows hidden, appear only on hover.
   Click again: arrows always visible again. */
(function(){
  var alwaysVisible=true; // true = arrows always shown; false = arrows only on hover
  var eyeSvgOpen='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
  var eyeSvgClosed='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';

  function getAllNavZones(){
    // Collect all nav zone elements using multiple strategies
    var zones=[];
    document.querySelectorAll('.nav-zone,.nav-prev,.nav-next,[class*="nav-prev"],[class*="nav-next"]').forEach(function(el){zones.push(el);});
    // Also find left/right fixed zones with arrows
    document.querySelectorAll('[style*="left:0"][style*="height:100"],[style*="right:0"][style*="height:100"],[style*="left: 0"][style*="height: 100"],[style*="right: 0"][style*="height: 100"]').forEach(function(el){
      if(el.querySelector('svg')||el.textContent.trim().match(/^[<>←→‹›❮❯]$/)){
        zones.push(el);
      }
    });
    return zones;
  }

  function applyNavState(){
    var zones=getAllNavZones();
    if(alwaysVisible){
      // Always visible: clear any inline styles, remove body class
      document.body.classList.remove('nav-zones-hidden');
      zones.forEach(function(el){
        el.style.opacity='';
        el.style.pointerEvents='';
      });
    }else{
      // Hover-only: add body class (CSS handles opacity:0 default + :hover opacity:1)
      document.body.classList.add('nav-zones-hidden');
      zones.forEach(function(el){
        el.style.opacity='';
        el.style.pointerEvents='';
      });
    }
  }

  function initEyeToggle(){
    var toolbar=document.querySelector('.toolbar,[class*="toolbar"],[id*="toolbar"]');
    if(!toolbar){
      var allFixed=document.querySelectorAll('[style*="position:fixed"],[style*="position: fixed"]');
      allFixed.forEach(function(el){
        if(el.offsetTop>window.innerHeight*0.7 && el.querySelectorAll('button').length>=2){
          toolbar=el;
        }
      });
    }
    if(!toolbar)return;

    var sep=document.createElement('span');
    sep.style.cssText='width:1px;height:20px;background:rgba(255,255,255,0.2);margin:0 4px;display:inline-block;vertical-align:middle;';

    var btn=document.createElement('button');
    btn.title='Toggle navigation arrows (always visible / hover only)';
    btn.innerHTML=eyeSvgOpen;
    btn.style.cssText='background:rgba(255,255,255,0.1);border:none;color:#e2e8f0;cursor:pointer;padding:6px 8px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;transition:all 0.2s;vertical-align:middle;';
    btn.addEventListener('mouseenter',function(){btn.style.background='rgba(255,255,255,0.2)';});
    btn.addEventListener('mouseleave',function(){
      btn.style.background=alwaysVisible?'rgba(255,255,255,0.1)':'rgba(239,68,68,0.2)';
    });
    btn.addEventListener('click',function(){
      alwaysVisible=!alwaysVisible;
      applyNavState();
      btn.innerHTML=alwaysVisible?eyeSvgOpen:eyeSvgClosed;
      btn.style.background=alwaysVisible?'rgba(255,255,255,0.1)':'rgba(239,68,68,0.2)';
    });

    toolbar.appendChild(sep);
    toolbar.appendChild(btn);

    // Ensure initial state is correct
    applyNavState();
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){setTimeout(initEyeToggle,500);});
  }else{
    setTimeout(initEyeToggle,500);
  }
})();
</script>
"""

    if "</head>" in html_content.lower():
        html_content = html_content.replace("</head>", safety_css + "</head>", 1)

    # PostMessage JS: notify parent window of slide changes (for admin viewer sync)
    postmessage_js = r"""
<script>
/* ── Notify parent window of slide changes (admin viewer iframe sync) ── */
(function(){
  var lastSlide=-1;
  function notifyParent(){
    var idx=-1;
    // Strategy 1: global variables Claude commonly uses
    if(typeof currentSlide!=='undefined') idx=currentSlide;
    else if(typeof currentIndex!=='undefined') idx=currentIndex;
    // Strategy 2: find visible/active slide by class or computed style
    else {
      var slides=document.querySelectorAll('.slide');
      slides.forEach(function(s,i){
        if(s.classList.contains('active')){idx=i;}
      });
      // Fallback: check opacity
      if(idx<0){
        slides.forEach(function(s,i){
          var st=window.getComputedStyle(s);
          if(st.opacity==='1'&&st.display!=='none'&&st.visibility!=='hidden'){idx=i;}
        });
      }
    }
    if(idx!==lastSlide&&idx>=0){
      lastSlide=idx;
      var total=document.querySelectorAll('.slide').length;
      try{window.parent.postMessage({type:'slideChange',slideIndex:idx,totalSlides:total},'*');}catch(e){}
    }
  }
  setInterval(notifyParent,300);
  document.addEventListener('keydown',function(){setTimeout(notifyParent,100);});
  document.addEventListener('click',function(){setTimeout(notifyParent,200);});
  document.addEventListener('touchend',function(){setTimeout(notifyParent,200);});
})();
</script>
"""

    if "</body>" in html_content.lower():
        html_content = html_content.replace("</body>", autofit_js + postmessage_js + "</body>", 1)

    webpage_path = os.path.join(pres_dir, "webpage.html")
    with open(webpage_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(
        "Website webpage generated: %s (%d chars, stop_reason=%s, tokens=%s)",
        webpage_path, len(html_content), stop_reason, token_usage,
    )

    if stop_reason == "max_tokens":
        logger.warning("Response truncated (max_tokens). HTML may be incomplete.")

    return {
        "webpage_path": webpage_path,
        "token_usage": token_usage,
    }