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

EDIT_SYSTEM_PROMPT = """You are an expert HTML/CSS presentation editor. You receive the HTML of a specific slide from a presentation and a user's edit request.

Rules:
1. Output ONLY the modified <div class="slide ..."> element. Nothing else.
2. Preserve ALL existing CSS classes, IDs, data attributes, and inline styles unless the user explicitly asks to change them.
3. Only change what the user specifically requested. Do not add, remove, or rearrange other content.
4. Keep the same overall structure and styling (dark theme, fonts, colors).
5. Keep all images, links, and interactive elements that the user didn't mention.
6. Output raw HTML only. No markdown fencing, no explanation, no comments.
7. The output must start with <div and end with </div>."""


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

        if target_indices is not None:
            # Edit specific slides
            for idx in target_indices:
                slide_html = slides[idx]["html"]

                user_msg = (
                    f"This is slide {idx + 1} of {total_slides} in the presentation.\n\n"
                    f"Current slide HTML:\n```html\n{slide_html}\n```\n\n"
                    f"User's edit request: \"{prompt}\"\n\n"
                    f"Output the modified slide HTML:"
                )

                response = client.messages.create(
                    model=settings.CLAUDE_MODEL,
                    max_tokens=8000,
                    system=EDIT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )

                new_html = response.content[0].text.strip()

                # Clean markdown fencing if present
                if new_html.startswith("```"):
                    lines = new_html.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    new_html = "\n".join(lines)

                # Ensure it starts with a div
                if not new_html.strip().startswith("<div"):
                    logger.warning("Claude response doesn't start with <div>, wrapping it")
                    new_html = f'<div class="slide">{new_html}</div>'

                html_content = replace_slide_in_html(html_content, idx, new_html)
                # Re-parse after each replacement since positions change
                slides = parse_slides_from_html(html_content)
                modified_indices.append(idx)

                if hasattr(response, "usage") and response.usage:
                    total_token_usage["input_tokens"] += response.usage.input_tokens
                    total_token_usage["output_tokens"] += response.usage.output_tokens

        else:
            # No specific slides: send slide summaries + prompt, let Claude decide
            slide_summaries = []
            for s in slides:
                # Extract a brief text preview from each slide
                soup = BeautifulSoup(s["html"], "html.parser")
                text = soup.get_text(separator=" ", strip=True)[:200]
                slide_summaries.append(f"Slide {s['index'] + 1}: {text}")

            analysis_msg = (
                f"The presentation has {total_slides} slides:\n\n"
                + "\n".join(slide_summaries) + "\n\n"
                f"User's edit request: \"{prompt}\"\n\n"
                f"Which slide numbers should be modified? Reply with ONLY a JSON array of "
                f"1-based slide numbers, e.g. [1, 3, 5]. No explanation."
            )

            analysis_resp = client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=200,
                system="You determine which slides need editing. Output only a JSON array of slide numbers.",
                messages=[{"role": "user", "content": analysis_msg}],
            )

            if hasattr(analysis_resp, "usage") and analysis_resp.usage:
                total_token_usage["input_tokens"] += analysis_resp.usage.input_tokens
                total_token_usage["output_tokens"] += analysis_resp.usage.output_tokens

            # Parse the slide numbers from response
            analysis_text = analysis_resp.content[0].text.strip()
            match = re.search(r'\[[\d,\s]+\]', analysis_text)
            if match:
                detected_numbers = json.loads(match.group())
                target_indices = [n - 1 for n in detected_numbers if 1 <= n <= total_slides]
            else:
                # Fallback: apply to all slides
                target_indices = list(range(total_slides))

            # Now edit the detected slides
            for idx in target_indices:
                slide_html = slides[idx]["html"]
                user_msg = (
                    f"This is slide {idx + 1} of {total_slides} in the presentation.\n\n"
                    f"Current slide HTML:\n```html\n{slide_html}\n```\n\n"
                    f"User's edit request: \"{prompt}\"\n\n"
                    f"Output the modified slide HTML:"
                )

                response = client.messages.create(
                    model=settings.CLAUDE_MODEL,
                    max_tokens=8000,
                    system=EDIT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )

                new_html = response.content[0].text.strip()
                if new_html.startswith("```"):
                    lines = new_html.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    new_html = "\n".join(lines)

                if not new_html.strip().startswith("<div"):
                    new_html = f'<div class="slide">{new_html}</div>'

                html_content = replace_slide_in_html(html_content, idx, new_html)
                slides = parse_slides_from_html(html_content)
                modified_indices.append(idx)

                if hasattr(response, "usage") and response.usage:
                    total_token_usage["input_tokens"] += response.usage.input_tokens
                    total_token_usage["output_tokens"] += response.usage.output_tokens

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
