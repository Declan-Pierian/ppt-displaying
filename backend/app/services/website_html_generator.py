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

        bg_template_instruction = f"""
## Background Template
The user has selected a specific background template: "{bg_name}"
I've included the template image below. You MUST use this image/style as the background for ALL slides.
- Extract the color scheme, patterns, and design language from this template
- Use the dominant colors as your slide backgrounds (via CSS gradients or solid colors that match)
- The template sets the overall mood — maintain it consistently across every slide
- Serve the background template image via: /api/v1/admin/background-templates/{bg_name}
- You can use it as a CSS background-image on each slide, or recreate its visual style with CSS gradients
- Preferred approach: use the image URL as background-image with overlay on each .slide:
  background: url('/api/v1/admin/background-templates/{bg_name}') center/cover;
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

## Screenshots — IMPORTANT SIZING
Use these EXACT URLs for page screenshots in <img> tags:
{json.dumps(screenshot_url_map, indent=2)}

**Screenshot display rules:**
- Display screenshots as elegant framed previews inside cards
- Use: border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.1)
- **SIZE: max-width: 55%; max-height: 65vh; width: auto; height: auto; object-fit: contain**
- For slides that feature a screenshot prominently, use a TWO-COLUMN layout:
  - Left column (50-55%): text content (heading, bullets, description)
  - Right column (45-50%): the screenshot image, vertically centered
- For the title slide, the screenshot can be larger (up to 60% width) as a hero image
- NEVER make screenshots smaller than 40% of the slide width
- Screenshots should be the visual centerpiece alongside the text, NOT tiny thumbnails

## Navigation & Controls
- Full-height side zones (80px wide) for prev/next with gradient + arrow on hover
- Keyboard: arrows, space, Home, End
- Touch swipe support
- Progress bar at top
- Slide counter at bottom-right
- Back button top-left linking to "/"
- TOOLBAR (bottom-left, fixed): magnifying glass zoom, +/- zoom, zoom %, reset, separator, pen (red 3px), highlighter (yellow 20px semi-transparent), clear drawings. Canvas overlay for drawing. Disable keyboard nav when drawing.
- Wrap each slide content in <div class="zoom-wrapper">

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
    content_blocks.append({
        "type": "text",
        "text": (
            "\n\nREMINDER: Create at LEAST 10-15 slides from this content. "
            "Each section/feature = its own slide. Make it look like a premium "
            "pitch deck presentation. Screenshots should be LARGE and prominent "
            "(max-width 55%, not tiny thumbnails). Use two-column layouts for "
            "screenshot slides. Start output with <!DOCTYPE html>."
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

    safety_css = (
        '\n<style>\n'
        + text_color_rule +
        '.tag,.pill,.badge,.kpi-label,.metric-mini .label,.chart-bar span'
        '{color:inherit !important;}\n'
        '.gradient-text{-webkit-text-fill-color:transparent !important;'
        'background-clip:text !important;}\n'
        '.slide,.slide-container,[class*="slide"]:not(.slide-counter)'
        '{overflow:hidden !important;max-height:100vh !important;}\n'
        '.company-logo{height:52px !important;width:auto !important;'
        'position:fixed !important;}\n'
        '/* Screenshot sizing safety */\n'
        '.slide img:not(.company-logo):not([class*="icon"]):not([class*="logo"])'
        '{min-width:200px;max-width:55%;max-height:65vh;'
        'object-fit:contain;border-radius:12px;}\n'
        '</style>\n'
    )

    autofit_js = (
        '\n<script>\n'
        'function autoFitSlides(){\n'
        '  document.querySelectorAll(".zoom-wrapper").forEach(function(w){\n'
        '    var slide=w.closest(".slide");\n'
        '    if(!slide)return;\n'
        '    w.style.transform="";\n'
        '    w.style.transformOrigin="center top";\n'
        '    var sh=slide.clientHeight;\n'
        '    var wh=w.scrollHeight;\n'
        '    if(wh>sh*0.9){\n'
        '      var scale=Math.max(0.5,(sh*0.85)/wh);\n'
        '      w.style.transform="scale("+scale+")";\n'
        '    }\n'
        '  });\n'
        '}\n'
        'window.addEventListener("load",function(){setTimeout(autoFitSlides,200);});\n'
        '</script>\n'
    )

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

    if "</body>" in html_content.lower():
        html_content = html_content.replace("</body>", autofit_js + "</body>", 1)

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