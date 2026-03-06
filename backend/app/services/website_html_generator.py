"""Generate a beautiful multi-slide HTML presentation from crawled website content.

The key insight: each crawled PAGE should produce MULTIPLE presentation slides.
A homepage with 5 sections becomes 5+ slides, not 1 slide.
This creates a proper pitch-deck style presentation.
"""

import os
import json
import base64
import logging
import re
from pathlib import Path

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

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

    Returns a dict with 'webpage_path' and 'token_usage', or None on failure.
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

    # ── Background template handling ──
    bg_template_instruction = ""
    bg_template_b64 = None
    template_brightness = "dark"  # default
    if background_template_path and os.path.exists(background_template_path):
        with open(background_template_path, "rb") as f:
            bg_template_b64 = base64.b64encode(f.read()).decode("utf-8")
        bg_name = os.path.basename(background_template_path)
        template_brightness = _analyse_template_brightness(background_template_path)
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
  background: {overlay_css}, url('/api/v1/admin/background-templates/{bg_name}') center/cover no-repeat !important;
  background-size: cover !important;
}}
```

- The image URL is: /api/v1/admin/background-templates/{bg_name}
- Apply this to every single .slide element — no exceptions
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
- **MAX 3 CARDS/ITEMS per slide in any grid or flex layout.** If you have 4+ items, SPLIT them across 2+ slides.
- Keep content concise: max 3 bullet points per slide, short sentences (max 12 words each)
- Use font-size clamp: h1 clamp(1.3rem,3.2vw,2.5rem), h2 clamp(1rem,2.5vw,1.8rem), p clamp(0.7rem,1.2vw,0.95rem)
- .zoom-wrapper padding: 50px 90px (leaves room for nav zones + logo)
- **TWO-COLUMN SLIDES (text + screenshot):** use display:flex; align-items:center; gap:40px; max-height:65vh; overflow:hidden;
  - Text column: flex:1 1 55%; max-width:55%; max 3-4 short bullet points
  - Image column: flex:0 0 38%; max-width:38%; text-align:center; display:flex; align-items:center; justify-content:center;
  - Image inside column: max-width:90%; max-height:36vh; object-fit:contain; display:block; margin:0 auto;
  - The image must be CENTERED in its column with visible padding on all sides — it must NEVER touch the right edge of the slide
- Card heights: max-height 25vh per card. Grid gaps: 16px max. overflow:hidden on every card.
- **EVERY card/box MUST have overflow:hidden** in its inline style
- CTA/final slides: keep it to heading + 2-3 short lines + 1 button. Do NOT put long URLs in visible text.
- NEVER let content exceed the viewport — MORE slides with LESS content is always better than overflowing
- Test mentally: if total content height exceeds ~75vh (leaving 25vh for padding/heading), SPLIT into 2 slides.

## Company Logo
<img src="/api/v1/pierian-logo" alt="Pierian" class="company-logo" style="position:fixed;top:16px;right:20px;z-index:95;height:52px;width:auto;object-fit:contain;pointer-events:none;border-radius:6px;" />

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

    # Add each page's screenshot + extracted content
    for idx, slide in enumerate(slides):
        slide_num = slide.get("slide_number") or slide.get("page_number", idx + 1)
        page_url = slide.get("page_url", "")
        page_title = slide.get("page_title", f"Page {slide_num}")
        content = slide.get("content", {})

        # Page screenshot as base64 image for Claude to see
        screenshot_path_rel = slide.get("screenshot_path", "")
        if screenshot_path_rel:
            filename = screenshot_path_rel.replace("media/", "", 1)
            screenshot_abs = os.path.join(media_dir, filename)
            if not os.path.exists(screenshot_abs):
                screenshot_abs = os.path.join(os.path.dirname(media_dir), screenshot_path_rel)

            if os.path.exists(screenshot_abs):
                with open(screenshot_abs, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    },
                })

        # Screenshot URL for Claude to use in the HTML
        screenshot_url = screenshot_url_map.get(f"page_{slide_num}", "")

        # Build detailed content description
        page_info = f"\n{'='*60}\nPAGE {slide_num} of {total_pages}: {page_title}\n{'='*60}"
        page_info += f"\nURL: {page_url}"
        if screenshot_url:
            page_info += f"\nScreenshot <img> URL: {screenshot_url}"

        if content.get("meta_description"):
            page_info += f"\nDescription: {content['meta_description']}"

        if content.get("sections"):
            page_info += f"\n\nSECTIONS ({len(content['sections'])} found — consider making each a separate slide):"
            for section in content["sections"]:
                page_info += f"\n  [{section['level'].upper()}] {section['heading']}"
                for text in section.get("content", []):
                    page_info += f"\n    • {text}"

        if content.get("cards"):
            page_info += f"\n\nCARDS/FEATURES ({len(content['cards'])} found):"
            for card in content["cards"]:
                page_info += f"\n  ▸ {card}"

        if content.get("list_items"):
            page_info += f"\n\nLIST ITEMS:"
            for item in content["list_items"]:
                page_info += f"\n  - {item}"

        if content.get("key_paragraphs"):
            page_info += "\n\nKEY CONTENT:"
            for para in content["key_paragraphs"]:
                page_info += f"\n  {para}"

        if content.get("nav_items"):
            page_info += f"\n\nNavigation: {', '.join(content['nav_items'][:10])}"

        content_blocks.append({"type": "text", "text": page_info})

    # Final reminder
    bg_reminder = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name = os.path.basename(background_template_path)
        bg_reminder = (
            f" BACKGROUND IMAGE IS MANDATORY: Every .slide MUST have "
            f"background: url('/api/v1/admin/background-templates/{bg_name}') center/cover; "
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
            "1. MAX 3 CARDS PER SLIDE. 4+ items = split across multiple slides.\n"
            "2. Screenshot images: max-width:38%; max-height:36vh; object-fit:contain. "
            "The image column must be max-width:38%. Image must be CENTERED in its column.\n"
            "3. Every card/box MUST have overflow:hidden in its style.\n"
            "4. All text inside cards must fit — keep card content to heading + 2 short lines max.\n"
            "5. CTA/final slide: heading + 2 lines + button. No long URLs in visible text.\n"
            "6. Content overflowing beyond the viewport is a CRITICAL BUG.\n"
            "7. TWO-COLUMN: text column 55%, image column 38%, gap 40px. "
            "Image NEVER touches right edge of slide — keep 5%+ right padding."
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
    has_logo = "pierian-logo" in html_content
    logo_snippet = (
        '\n<!-- Pierian company logo -->\n'
        '<img src="/api/v1/pierian-logo" alt="Pierian" '
        'class="company-logo" '
        'style="position:fixed;top:16px;right:20px;z-index:95;'
        'height:52px;width:auto;object-fit:contain;pointer-events:none;'
        'border-radius:6px;" />\n'
    )

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
            f'  background:{overlay},'
            f"url('/api/v1/admin/background-templates/{bg_name_css}') center center/cover no-repeat !important;\n"
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
        '/* Card/grid containment — strict height limits */\n'
        '.slide [style*="display:grid"],.slide [style*="display: grid"]{\n'
        '  grid-template-columns:repeat(auto-fit,minmax(180px,1fr)) !important;\n'
        '  max-height:60vh !important;\n'
        '  overflow:hidden !important;\n'
        '  gap:14px !important;\n'
        '}\n'
        '.slide [style*="display:flex"],.slide [style*="display: flex"]{\n'
        '  flex-wrap:nowrap !important;\n'
        '  max-height:65vh !important;\n'
        '  overflow:hidden !important;\n'
        '  max-width:100% !important;\n'
        '  align-items:center !important;\n'
        '}\n'
        '/* Individual cards — strict height limit + clip content */\n'
        '.slide [class*="card"],.slide [class*="Card"],.slide [class*="feature"],.slide [class*="Feature"],'
        '.slide [class*="item"],.slide [class*="Item"],.slide [class*="box"],.slide [class*="Box"],'
        '.slide [class*="service"],.slide [class*="Service"],.slide [class*="benefit"],.slide [class*="Benefit"],'
        '.slide [class*="cta"],.slide [class*="CTA"],.slide [class*="action"],.slide [class*="Action"]{\n'
        '  max-height:25vh !important;\n'
        '  overflow:hidden !important;\n'
        '  padding:clamp(10px,1.5vh,20px) clamp(12px,1.5vw,24px) !important;\n'
        '}\n'
        '/* Nth-child safety: hide 4th+ cards in grid containers */\n'
        '.slide [style*="display:grid"]>*:nth-child(n+4),'
        '.slide [style*="display: grid"]>*:nth-child(n+4){\n'
        '  display:none !important;\n'
        '}\n'
        '/* ── IMAGE CONTAINMENT — screenshots must NEVER exceed slide ── */\n'
        '.slide img:not(.company-logo):not([class*="icon"]):not([class*="logo"]):not([width="1"]){\n'
        '  max-width:38vw !important;\n'
        '  max-height:36vh !important;\n'
        '  width:auto !important;\n'
        '  height:auto !important;\n'
        '  object-fit:contain !important;\n'
        '  border-radius:12px;\n'
        '}\n'
        '/* ── Two-column layouts: STRICT width constraints on both columns ── */\n'
        '.slide [style*="display:flex"]>*,.slide [style*="display: flex"]>*{\n'
        '  overflow:hidden !important;\n'
        '  min-width:0 !important;\n'
        '  max-width:55% !important;\n'
        '  flex-shrink:1 !important;\n'
        '}\n'
        '/* Image column (typically the 2nd child): cap at 42% so it stays well within the slide */\n'
        '.slide [style*="display:flex"]>*:last-child,.slide [style*="display: flex"]>*:last-child{\n'
        '  max-width:42% !important;\n'
        '  display:flex !important;\n'
        '  align-items:center !important;\n'
        '  justify-content:center !important;\n'
        '}\n'
        '/* Images inside flex layouts: constrain relative to their parent AND viewport */\n'
        '.slide [style*="display:flex"] img,.slide [style*="display: flex"] img{\n'
        '  max-height:36vh !important;\n'
        '  max-width:90% !important;\n'
        '  width:auto !important;\n'
        '  height:auto !important;\n'
        '  object-fit:contain !important;\n'
        '  display:block !important;\n'
        '  margin:0 auto !important;\n'
        '}\n'
        '.company-logo{height:52px !important;width:auto !important;'
        'position:fixed !important;}\n'
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

    if not has_logo and "<body" in html_content.lower():
        html_content = re.sub(
            r'(<body[^>]*>)',
            r'\1' + logo_snippet,
            html_content,
            count=1,
            flags=re.IGNORECASE,
        )

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