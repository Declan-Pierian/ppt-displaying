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
    """Extract readable text lines (with hyperlinks) from a slide's shapes."""
    texts = []
    for shape in shapes:
        shape_type = shape.get("shape_type", "")

        # Text boxes
        if shape_type == "text_box" and shape.get("text_body"):
            for para in shape["text_body"].get("paragraphs", []):
                parts = []
                for run in para.get("runs", []):
                    text = run.get("text", "")
                    hl = run.get("hyperlink")
                    if hl and hl.get("url") and text.strip():
                        parts.append(f'{text.strip()} [LINK: {hl["url"]}]')
                    elif text.strip():
                        parts.append(text.strip())
                para_text = " ".join(parts)
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


def _get_image_refs(
    shapes: list,
    presentation_id: int,
    slide_w_emu: int = 9144000,
    slide_h_emu: int = 6858000,
) -> list[dict]:
    """Get image info (URL, alt text, hyperlink, size hints) for slide shapes."""
    images = []
    for shape in shapes:
        if shape.get("shape_type") == "image":
            img_data = shape.get("image", {})
            path = img_data.get("media_path", "")
            if path:
                filename = path.replace("media/", "", 1)
                url = f"/api/v1/media/{presentation_id}/{filename}"
                # Calculate size as percentage of slide for layout hints
                pos = shape.get("position", {})
                w_emu = pos.get("width_emu", 0)
                h_emu = pos.get("height_emu", 0)
                w_pct = round(w_emu / slide_w_emu * 100) if slide_w_emu else 0
                h_pct = round(h_emu / slide_h_emu * 100) if slide_h_emu else 0
                images.append({
                    "url": url,
                    "alt": img_data.get("alt_text", ""),
                    "hyperlink": shape.get("hyperlink"),
                    "width_pct": w_pct,
                    "height_pct": h_pct,
                })
        elif shape.get("shape_type") == "group" and shape.get("children"):
            images.extend(_get_image_refs(
                shape["children"], presentation_id, slide_w_emu, slide_h_emu,
            ))
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
    slide_w_emu = data.get("slide_width_emu", 9144000)
    slide_h_emu = data.get("slide_height_emu", 6858000)

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
                path = shape.get("image", {}).get("media_path", "")
                if path:
                    all_images.add(path.replace("media/", "", 1))

    image_url_map = {
        img: f"/api/v1/media/{presentation_id}/{img}"
        for img in sorted(all_images)
    }

    # Also include slide screenshot images for complex visual slides
    for slide in slides:
        sn = slide["slide_number"]
        screenshot_key = f"slide_images/slide_{sn}.png"
        screenshot_path = os.path.join(media_dir, "slide_images", f"slide_{sn}.png")
        if os.path.exists(screenshot_path):
            image_url_map[screenshot_key] = f"/api/v1/media/{presentation_id}/{screenshot_key}"

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
3. NAVIGATION: Use full-height side zones (not small circular buttons). The left and right edges of the screen (80px wide, full height) should be clickable navigation areas that show a subtle gradient + arrow icon on hover. Also include keyboard navigation (arrows, space, Home, End) and touch swipe support.
4. DO NOT just display slide images. Extract and recreate all text content as proper HTML elements.
5. IMAGES — CRITICAL RULES:
   a) Each slide lists its images with [img] URLs and size hints (e.g., ~60%w x 45%h means the image occupies 60% of slide width and 45% of slide height). You MUST display EVERY image on its CORRECT slide using <img> tags with the EXACT URLs provided. Do NOT skip, omit, or move images to different slides.
   b) SIZING: Use the percentage hints to size images proportionally. Large images (>50%w) should use max-width:90%; max-height:50vh. Medium images (20-50%w) use max-width:45%; max-height:40vh. Small images (<20%w) use max-width:25%; max-height:20vh. ALWAYS set max-width and max-height to prevent overflow.
   c) LAYOUT: When a slide has multiple images, arrange them in a responsive CSS grid or flexbox layout (e.g., 2-column grid for 2-4 images, 3-column for 5+). All images must be visible without scrolling.
   d) CONTAINMENT: ALL images must stay within the visible viewport. Use object-fit:contain, border-radius:12px, and overflow:hidden on image containers. NEVER let an image exceed the slide boundaries.
   e) Look at the slide screenshot image I provide — try to match the visual layout of where images appear relative to text.
6. If a slide has a background image, use it as that slide's CSS background (background-image with cover).
7. Structure content intelligently: use cards, grids, metric displays, feature lists, tags. When a slide has BOTH text and images, use a two-column layout (text on one side, images on the other) or place images below the text. Match the visual arrangement shown in the slide screenshot.
8. Make it visually stunning with gradients, subtle animations, and professional spacing. CRITICAL: ALL text must use LIGHT colors (#f1f5f9, #e2e8f0, #cbd5e1, #94a3b8 for muted) — NEVER use dark/black text colors like #000, #1a1a1a, #333, etc. The background is dark (#0f172a), so dark text will be invisible.
9. The HTML must be completely self-contained (all CSS in <style>, all JS in <script>).
10. Include a back button (top-left, linking to "/") so users can return to the presentation list.
11. Adapt layouts to content: title slides get centered hero treatment, content-heavy slides get multi-column layouts, list slides get feature-list styling.
12. TOOLBAR (bottom-left): Include a floating toolbar at the BOTTOM-LEFT of the screen (position: fixed; bottom: 16px; left: 16px) with these controls:
    - Magnifying glass button (first) — when active, clicking on the slide zooms into that area (2x zoom with transform-origin set to click position). Clicking again zooms out. The cursor should change to zoom-in/zoom-out.
    - Zoom In (+), Zoom Out (-), zoom percentage label, Reset zoom button
    - A separator
    - Pen tool button (red ink, 3px, for drawing/annotating on the slide)
    - Highlighter button (yellow, 20px, semi-transparent, for highlighting)
    - Clear drawings button
    Use a canvas overlay for drawing. When pen/highlight is active, keyboard navigation should be disabled. Drawings clear when navigating to a new slide.
13. Wrap each slide's content inside a <div class="zoom-wrapper"> so zoom scales the content. The zoom-wrapper should have transform-origin: center center and transition on transform.
14. Include a progress bar at top and slide counter at bottom-right.
15. HYPERLINKS: Text marked with [LINK: url] must be rendered as clickable <a> tags with href set to the URL, target="_blank", and styled with underline + accent color. Images marked with (wrap in <a href="...">) must be wrapped in anchor tags linking to that URL.
16. VIEWPORT SAFETY: Each slide MUST fit within 100vw x 100vh with NO scrolling within a single slide. Add overflow:hidden on each slide container. All content (text + images) must fit within the visible area with proper padding (at least 60px top/bottom, 100px left/right for navigation zones). If content is too much, reduce font sizes or image sizes — NEVER allow overflow.
18. VISUAL FIDELITY: You are provided both a screenshot of each slide AND the extracted text/images. Use the SCREENSHOT as your primary reference for layout decisions — replicate the visual arrangement (where text sits relative to images, content grouping, etc.). The extracted text ensures accuracy of the words; the screenshot shows the layout.

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
        image_refs = _get_image_refs(
            slide.get("shapes", []), presentation_id, slide_w_emu, slide_h_emu,
        )

        # Detect slides with complex visual content that can't be fully
        # extracted — provide slide screenshot as a displayable fallback image
        shapes = slide.get("shapes", [])
        autoshape_count = sum(
            1 for s in shapes if s.get("shape_type") in ("auto_shape", "group")
        )
        text_only_count = sum(
            1 for s in shapes if s.get("shape_type") == "text_box"
        )
        has_bg_image = slide.get("background", {}).get("type") == "image"
        # Complex visual = many autoshapes (flowcharts/diagrams) with no images,
        # OR slide has background image but very few shapes (content is in SmartArt/layers)
        has_complex_visuals = (
            (autoshape_count >= 3 and not image_refs)
            or (has_bg_image and len(shapes) <= 3 and not image_refs)
        )

        slide_info = f"\n--- Slide {slide_num} of {total} ---"

        bg = slide.get("background", {})
        if bg.get("type") == "image" and bg.get("image_path"):
            filename = bg["image_path"].replace("media/", "", 1)
            slide_info += f"\nBackground image: /api/v1/media/{presentation_id}/{filename}"

        if texts:
            slide_info += "\nText content:\n" + "\n".join(f"  - {t}" for t in texts)
        if image_refs:
            n = len(image_refs)
            slide_info += f"\nImages on this slide ({n} image{'s' if n > 1 else ''} — MUST ALL be displayed on THIS slide):"
            for img in image_refs:
                line = f"\n  [img] {img['url']}  size: ~{img['width_pct']}%w x {img['height_pct']}%h of slide"
                if img.get("alt"):
                    line += f'  alt="{img["alt"]}"'
                if img.get("hyperlink"):
                    line += f'  (wrap in <a href="{img["hyperlink"]}">)'
                slide_info += line
            if n > 1:
                slide_info += f"\n  LAYOUT HINT: This slide has {n} images. Arrange them in a grid or side-by-side layout so all are visible without scrolling."

        # Provide slide screenshot as displayable image for complex visual slides
        if has_complex_visuals:
            screenshot_url = f"/api/v1/media/{presentation_id}/slide_images/slide_{slide_num}.png"
            slide_info += (
                f"\n  COMPLEX VISUAL CONTENT: This slide contains a diagram/flowchart/visual "
                f"made of PowerPoint shapes that cannot be fully extracted as text. "
                f"Display the slide screenshot as an <img> on this slide: "
                f"\n  [img] {screenshot_url}  size: ~80%w x 70%h of slide  alt=\"Slide {slide_num} diagram\""
                f"\n  Place it prominently so the visual content is visible. "
                f"Use the extracted text above as labels/annotations around or below the image."
            )

        if not texts and not image_refs and not has_complex_visuals:
            slide_info += "\n  (Visual/decorative slide — no extractable text)"

        content_blocks.append({"type": "text", "text": slide_info})

    # ── Call Claude API ──
    logger.info(
        "Calling Claude API for webpage generation (model=%s, slides=%d)...",
        settings.CLAUDE_MODEL, total,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Use streaming to avoid timeout on large presentations
        html_parts = []
        stop_reason = None
        with client.messages.stream(
            model=settings.CLAUDE_MODEL,
            max_tokens=32768,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            for text in stream.text_stream:
                html_parts.append(text)
            final_message = stream.get_final_message()
            stop_reason = final_message.stop_reason
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return None

    html_content = "".join(html_parts)

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

    # ── Post-processing: inject safety CSS + auto-fit JS ──
    import re

    safety_css = (
        '\n<style>\n'
        '/* Safety: ensure all text is readable on dark background */\n'
        'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
        '{color:#f1f5f9 !important;}\n'
        '.tag,.pill,.badge,.kpi-label,.metric-mini .label,.chart-bar span'
        '{color:inherit !important;}\n'
        '.gradient-text{-webkit-text-fill-color:transparent !important;'
        'background-clip:text !important;}\n'
        '/* Safety: constrain slide content within viewport */\n'
        '.slide,.slide-container,[class*="slide"]:not(.slide-counter)'
        '{overflow:hidden !important;max-height:100vh !important;}\n'
        '</style>\n'
    )

    # JS to auto-fit overflowing slide content by scaling down
    autofit_js = (
        '\n<script>\n'
        '/* Auto-fit: scale down slide content that overflows viewport */\n'
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

    # Inject safety CSS before </head>
    if "</head>" in html_content.lower():
        html_content = html_content.replace(
            "</head>", safety_css + "</head>", 1
        )

    # PostMessage JS: notify parent window of slide changes (for admin viewer sync)
    postmessage_js = r"""
<script>
/* ── Notify parent window of slide changes (admin viewer iframe sync) ── */
(function(){
  var lastSlide=-1;
  function notifyParent(){
    var idx=-1;
    if(typeof currentSlide!=='undefined') idx=currentSlide;
    else if(typeof currentIndex!=='undefined') idx=currentIndex;
    else {
      var slides=document.querySelectorAll('.slide');
      slides.forEach(function(s,i){
        if(s.classList.contains('active')){idx=i;}
      });
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

    # Inject auto-fit JS + postMessage JS before </body>
    if "</body>" in html_content.lower():
        html_content = html_content.replace(
            "</body>", autofit_js + postmessage_js + "</body>", 1
        )

    # Save the webpage
    webpage_path = os.path.join(pres_dir, "webpage.html")
    with open(webpage_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(
        "Webpage generated successfully: %s (%d chars, stop_reason=%s)",
        webpage_path,
        len(html_content),
        stop_reason,
    )

    if stop_reason == "max_tokens":
        logger.warning(
            "Response was truncated (max_tokens reached). "
            "The HTML may be incomplete. Consider increasing max_tokens."
        )

    return webpage_path
