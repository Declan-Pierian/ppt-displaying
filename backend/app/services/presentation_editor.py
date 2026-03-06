"""AI-powered presentation editor.

Parses webpage.html to extract individual slides, sends targeted slides to
Claude API for modification based on user prompts, and splices the results
back into the full document.  Maintains versioned backups for undo support.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone

import anthropic
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

# ── HTML slide parsing ──────────────────────────────────────────────────────

def parse_slides_from_html(html_content: str) -> list[dict]:
    """Extract individual slide <div> elements from the presentation HTML.

    Returns a list of dicts: [{index, html, outer_html}] for each slide.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all divs whose class list contains "slide" (but not utility classes)
    skip_classes = {"slide-counter", "slide-nav", "slide-number", "slide-progress"}
    slides = []
    for div in soup.find_all("div"):
        classes = div.get("class", [])
        if not classes:
            continue
        class_set = set(classes)
        if "slide" in class_set and not class_set & skip_classes:
            slides.append(div)

    result = []
    for i, slide_tag in enumerate(slides):
        result.append({
            "index": i,
            "html": str(slide_tag),
            "tag": slide_tag,
        })

    return result


def replace_slide_in_html(html_content: str, slide_index: int, new_slide_html: str) -> str:
    """Replace a specific slide div in the full HTML document.

    Uses BeautifulSoup to find the Nth slide div and replace it.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    skip_classes = {"slide-counter", "slide-nav", "slide-number", "slide-progress"}
    slides = []
    for div in soup.find_all("div"):
        classes = div.get("class", [])
        if not classes:
            continue
        class_set = set(classes)
        if "slide" in class_set and not class_set & skip_classes:
            slides.append(div)

    if slide_index < 0 or slide_index >= len(slides):
        raise ValueError(f"Slide index {slide_index} out of range (0-{len(slides) - 1})")

    # Parse the new slide HTML
    new_soup = BeautifulSoup(new_slide_html, "html.parser")
    new_slide_tag = new_soup.find("div")
    if not new_slide_tag:
        raise ValueError("New slide HTML does not contain a <div> element")

    # Replace in the original soup
    slides[slide_index].replace_with(new_slide_tag)

    return str(soup)


def _extract_style_context(html_content: str) -> str:
    """Extract CSS <style> blocks from the HTML for context."""
    soup = BeautifulSoup(html_content, "html.parser")
    styles = []
    for tag in soup.find_all("style"):
        text = tag.get_text(strip=True)
        if text:
            # Truncate if very long — just the first 3000 chars of CSS
            styles.append(text[:3000])
    return "\n".join(styles)[:4000]


def _clean_claude_response(raw: str) -> str:
    """Clean Claude's response: strip markdown fencing and whitespace."""
    text = raw.strip()

    # Handle markdown fencing with optional language tag: ```html, ```HTML, ```css, etc.
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening fence (may have language tag like ```html)
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Sometimes Claude wraps in multiple fences
    if text.startswith("```"):
        return _clean_claude_response(text)

    return text


def _get_slide_text_preview(slide_html: str, max_len: int = 150) -> str:
    """Extract a brief text preview from slide HTML."""
    soup = BeautifulSoup(slide_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:max_len]


# ── Version management ──────────────────────────────────────────────────────

def _history_path(pres_dir: str) -> str:
    return os.path.join(pres_dir, "edit_history.json")


def _load_history(pres_dir: str) -> dict:
    path = _history_path(pres_dir)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"versions": [], "current_version": 0}


def _save_history(pres_dir: str, history: dict):
    path = _history_path(pres_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _backup_current(pres_dir: str, version: int):
    """Copy current webpage.html → webpage_v{version}.html."""
    src = os.path.join(pres_dir, "webpage.html")
    dst = os.path.join(pres_dir, f"webpage_v{version}.html")
    if os.path.exists(src):
        shutil.copy2(src, dst)


# ── Claude edit API ─────────────────────────────────────────────────────────

EDIT_SYSTEM_PROMPT = """\
You are a powerful HTML presentation editor. An admin user wants to modify a presentation slide. \
You will receive the slide's current HTML and the user's edit request.

Your job is to fulfill the user's request, even if it is brief or vague. \
Interpret the intent behind the request and make smart, appropriate changes. \
Users are non-technical — they may say things like "make it look better", "fix the layout", \
"add more info about X", or "change the color". Use your judgment.

CRITICAL RULES:
1. Output ONLY the complete modified <div class="slide ..."> element — nothing else.
2. NO markdown fencing, NO explanations, NO comments. Raw HTML only.
3. Your output MUST start with <div and end with </div>.
4. Preserve all existing CSS classes, IDs, and data attributes unless the change requires modifying them.
5. Keep all images, links, and elements the user didn't mention.
6. Maintain the same theme, dark backgrounds, fonts, and overall presentation style.

COMMON EDITS AND HOW TO HANDLE THEM:
- "change title/heading to X" → Update the heading text, keep all styling.
- "change color" or "make it blue/red/etc" → Update the relevant color/background-color in inline styles.
- "add a point/bullet about X" → Add an <li> or paragraph with that content in the appropriate section.
- "remove X" → Remove that element while keeping the rest intact.
- "make it bigger/smaller" → Adjust font-size or padding.
- "make it look better" or "improve" → Improve spacing, alignment, visual hierarchy. Add subtle design polish.
- "change background" → Update the slide's background-color or background-image style.
- "add an image" → Add a placeholder <img> with a descriptive alt text and a placeholder src.
- "swap sections" or "rearrange" → Reorder the elements as requested.
- "change font" → Update font-family in inline styles.
- If the user says something that doesn't make sense for the slide, make the closest reasonable interpretation."""


ANALYSIS_SYSTEM_PROMPT = """\
You analyze presentation edit requests to determine which slides need to be modified. \
You receive a summary of all slides and the user's request.

Respond with ONLY a JSON array of 1-based slide numbers. Examples:
- [1] — only slide 1
- [2, 5] — slides 2 and 5
- [1, 2, 3, 4, 5] — all five slides

Rules:
- If the user mentions specific slide numbers, use those.
- If the user says "all slides" or the change applies globally (like "change all headings"), include all slides.
- If the user's request is vague (like "change the title"), pick the most likely slide (usually slide 1).
- If the user mentions content that only appears on one slide, pick that slide.
- When in doubt, pick fewer slides rather than all of them."""


def apply_chat_edit(
    pres_dir: str,
    prompt: str,
    slide_numbers: list[int] | None,
    presentation_id: int,
) -> dict:
    """Apply an AI edit to the presentation HTML.

    1. Read current webpage.html
    2. Create version backup
    3. Parse out target slide(s)
    4. Send slide HTML + prompt to Claude API
    5. Replace slide(s) in full HTML
    6. Save updated webpage.html
    7. Update edit_history.json

    Returns dict with success, version, modified_slides, message, token_usage.
    """
    edit_model = settings.CLAUDE_EDIT_MODEL or settings.CLAUDE_MODEL
    api_key = settings.CLAUDE_API_KEY
    if not api_key:
        return {"success": False, "message": "CLAUDE_API_KEY not configured", "version": 0, "modified_slides": [], "token_usage": None}

    webpage_path = os.path.join(pres_dir, "webpage.html")
    if not os.path.exists(webpage_path):
        return {"success": False, "message": "No webpage.html found", "version": 0, "modified_slides": [], "token_usage": None}

    with open(webpage_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    slides = parse_slides_from_html(html_content)
    if not slides:
        return {"success": False, "message": "Could not parse any slides from the HTML", "version": 0, "modified_slides": [], "token_usage": None}

    total_slides = len(slides)

    # Extract CSS context for Claude (so it knows available styles)
    css_context = _extract_style_context(html_content)

    # Determine which slides to edit
    if slide_numbers:
        # Convert 1-based to 0-based indices
        target_indices = [n - 1 for n in slide_numbers if 1 <= n <= total_slides]
        if not target_indices:
            return {"success": False, "message": f"Invalid slide numbers. Presentation has {total_slides} slides.", "version": 0, "modified_slides": [], "token_usage": None}
    else:
        # AI decides — send all slide titles/summaries for context, let Claude pick
        target_indices = None  # Will handle below

    # Load history & create backup
    history = _load_history(pres_dir)
    current_version = history["current_version"]
    _backup_current(pres_dir, current_version)

    new_version = current_version + 1
    modified_indices = []
    total_token_usage = {"input_tokens": 0, "output_tokens": 0}

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # If no specific slides selected, let AI decide which ones to edit
        if target_indices is None:
            target_indices = _detect_target_slides(
                client, edit_model, slides, total_slides, prompt, total_token_usage
            )

        # Edit each target slide
        for idx in target_indices:
            slide_html = slides[idx]["html"]

            # Build context: include neighboring slide summaries for consistency
            context_parts = []
            if idx > 0:
                prev_text = _get_slide_text_preview(slides[idx - 1]["html"])
                context_parts.append(f"Previous slide (slide {idx}): {prev_text}")
            if idx < total_slides - 1:
                next_text = _get_slide_text_preview(slides[idx + 1]["html"])
                context_parts.append(f"Next slide (slide {idx + 2}): {next_text}")

            neighbor_context = ""
            if context_parts:
                neighbor_context = "\n\nNeighboring slides for context:\n" + "\n".join(context_parts)

            css_section = ""
            if css_context:
                css_section = f"\n\nPresentation CSS (for reference — use matching classes/styles):\n{css_context}\n"

            user_msg = (
                f"Slide {idx + 1} of {total_slides}.{neighbor_context}{css_section}\n\n"
                f"Current slide HTML:\n{slide_html}\n\n"
                f"Edit request: {prompt}"
            )

            new_html = _call_claude_for_edit(client, edit_model, user_msg, total_token_usage)

            if new_html:
                html_content = replace_slide_in_html(html_content, idx, new_html)
                # Re-parse after each replacement since positions change
                slides = parse_slides_from_html(html_content)
                modified_indices.append(idx)
            else:
                logger.warning("Claude returned invalid HTML for slide %d, skipping", idx + 1)

        if not modified_indices:
            return {
                "success": False,
                "message": "AI could not produce valid edits. Try rephrasing your request with more detail.",
                "version": current_version,
                "modified_slides": [],
                "token_usage": total_token_usage if any(total_token_usage.values()) else None,
            }

        # Save updated HTML
        with open(webpage_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Update history
        history["versions"].append({
            "version": new_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "slides_affected": [i + 1 for i in modified_indices],
        })
        history["current_version"] = new_version
        _save_history(pres_dir, history)

        modified_slide_numbers = [i + 1 for i in modified_indices]
        msg = f"Edited slide{'s' if len(modified_slide_numbers) > 1 else ''} {', '.join(map(str, modified_slide_numbers))} successfully."

        logger.info(
            "Chat edit applied: presentation_id=%d, version=%d, slides=%s, tokens=%s",
            presentation_id, new_version, modified_slide_numbers, total_token_usage,
        )

        return {
            "success": True,
            "message": msg,
            "version": new_version,
            "modified_slides": modified_slide_numbers,
            "token_usage": total_token_usage,
        }

    except Exception as e:
        logger.error("Chat edit failed: %s", e, exc_info=True)
        return {
            "success": False,
            "message": f"Edit failed: {str(e)}",
            "version": current_version,
            "modified_slides": [],
            "token_usage": total_token_usage if any(total_token_usage.values()) else None,
        }


def _detect_target_slides(
    client: anthropic.Anthropic,
    model: str,
    slides: list[dict],
    total_slides: int,
    prompt: str,
    token_usage: dict,
) -> list[int]:
    """Use Claude to determine which slides should be edited based on the prompt."""
    slide_summaries = []
    for s in slides:
        text = _get_slide_text_preview(s["html"], 200)
        slide_summaries.append(f"Slide {s['index'] + 1}: {text}")

    analysis_msg = (
        f"The presentation has {total_slides} slides:\n\n"
        + "\n".join(slide_summaries) + "\n\n"
        f"User's edit request: {prompt}\n\n"
        f"Which slides should be modified? Output ONLY a JSON array like [1, 3]."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": analysis_msg}],
        )

        if hasattr(resp, "usage") and resp.usage:
            token_usage["input_tokens"] += resp.usage.input_tokens
            token_usage["output_tokens"] += resp.usage.output_tokens

        analysis_text = resp.content[0].text.strip()
        logger.info("Slide detection response: %s", analysis_text)

        # Try to extract JSON array — be flexible about format
        # Handle: [1, 3], [1,3], "slides [1, 3]", etc.
        match = re.search(r'\[[\d,\s]+\]', analysis_text)
        if match:
            detected = json.loads(match.group())
            indices = [n - 1 for n in detected if isinstance(n, int) and 1 <= n <= total_slides]
            if indices:
                return indices

        # Fallback: try to extract bare numbers like "1, 3" or "Slide 1"
        numbers = [int(x) for x in re.findall(r'\d+', analysis_text)]
        indices = [n - 1 for n in numbers if 1 <= n <= total_slides]
        if indices:
            return indices

    except Exception as e:
        logger.warning("Slide detection failed: %s, defaulting to slide 1", e)

    # Final fallback: edit slide 1 instead of all slides
    return [0]


def _call_claude_for_edit(
    client: anthropic.Anthropic,
    model: str,
    user_msg: str,
    token_usage: dict,
    attempt: int = 1,
) -> str | None:
    """Call Claude API for a slide edit. Retries once if response is invalid."""
    max_attempts = 2

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=EDIT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    if hasattr(response, "usage") and response.usage:
        token_usage["input_tokens"] += response.usage.input_tokens
        token_usage["output_tokens"] += response.usage.output_tokens

    raw = response.content[0].text
    new_html = _clean_claude_response(raw)

    # Validate: must start with <div
    if new_html.strip().startswith("<div"):
        return new_html

    # Invalid response — retry once with a corrective prompt
    if attempt < max_attempts:
        logger.warning("Claude response didn't start with <div (attempt %d), retrying", attempt)
        retry_msg = (
            user_msg + "\n\n"
            "IMPORTANT: Your previous response was invalid. "
            "You MUST output ONLY the raw HTML starting with <div class=\"slide and ending with </div>. "
            "No markdown, no explanation, no fencing. Just the HTML."
        )
        return _call_claude_for_edit(client, model, retry_msg, token_usage, attempt + 1)

    # Last resort: try to wrap it
    logger.warning("Claude response still invalid after retry, attempting to wrap")
    if "<" in new_html:
        # Has some HTML in it, wrap in slide div
        return f'<div class="slide">{new_html}</div>'

    return None


def undo_edit(pres_dir: str) -> dict:
    """Revert webpage.html to the previous version."""
    history = _load_history(pres_dir)
    current = history["current_version"]

    if current <= 0:
        return {"success": False, "version": 0, "message": "Nothing to undo — already at the original version."}

    previous = current - 1
    backup_path = os.path.join(pres_dir, f"webpage_v{previous}.html")
    webpage_path = os.path.join(pres_dir, "webpage.html")

    if not os.path.exists(backup_path):
        return {"success": False, "version": current, "message": f"Backup file for version {previous} not found."}

    # Backup current before undoing (so redo could work later)
    _backup_current(pres_dir, current)

    # Restore previous version
    shutil.copy2(backup_path, webpage_path)

    history["current_version"] = previous
    _save_history(pres_dir, history)

    logger.info("Undo: reverted from version %d to %d", current, previous)

    return {
        "success": True,
        "version": previous,
        "message": f"Reverted to version {previous}.",
    }


def get_edit_history(pres_dir: str) -> dict:
    """Return the edit history for a presentation."""
    history = _load_history(pres_dir)
    return {
        "versions": history.get("versions", []),
        "current_version": history.get("current_version", 0),
    }
