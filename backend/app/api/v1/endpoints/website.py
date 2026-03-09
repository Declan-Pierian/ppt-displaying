"""API endpoint for generating presentations from website URLs."""

import os
import socket
import time
import json
import hashlib
import logging
import shutil
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.models.database import get_db, SessionLocal
from app.models.user import User
from app.models.presentation import Presentation
from app.models.upload_log import UploadLog
from app.schemas.presentation import (
    PresentationResponse,
    WebsiteSubmitRequest,
    URLCheckRequest,
    URLCheckResponse,
    BackgroundTemplateResponse,
    RegenerateRequest,
)
from app.services.extraction.progress import (
    init_progress, update_progress, complete_progress, fail_progress,
    cancel_progress, is_cancelled,
)
from app.services.html_template import extract_template_shell, cache_template_from_webpage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# ── Background templates directory ──
# website.py is at backend/app/api/v1/endpoints/website.py  →  5 dirname levels to reach backend/
_BACKEND_DIR = os.path.dirname(  # backend/
    os.path.dirname(  # backend/app/
        os.path.dirname(  # backend/app/api/
            os.path.dirname(  # backend/app/api/v1/
                os.path.dirname(  # backend/app/api/v1/endpoints/
                    os.path.abspath(__file__)
                )
            )
        )
    )
)
_TEMPLATES_DIR = os.path.join(_BACKEND_DIR, "background_templates")


def _normalise_url_for_dedup(url: str) -> str:
    """Normalise URL for duplicate detection: lowercase, strip trailing slash, strip www."""
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{netloc}{path}"


def _validate_url(url: str) -> str:
    """Validate and normalise the URL."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("Invalid URL: no valid domain found")

    return url


def _check_domain_exists(url: str) -> tuple[bool, str]:
    """Check if the domain resolves via DNS. Returns (exists, error_message)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.netloc.split(":")[0]
        socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return True, ""
    except socket.gaierror:
        return False, f"Domain '{parsed.netloc}' does not exist or cannot be resolved"
    except Exception as e:
        return False, f"DNS lookup failed: {str(e)}"


def _check_website_legitimacy(url: str) -> tuple[bool, str]:
    """Check if the URL responds with a valid webpage (HTTP HEAD/GET check)."""
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            verify=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            try:
                resp = client.head(url, timeout=10.0)
            except Exception:
                resp = client.get(url, timeout=15.0)

            if resp.status_code >= 400:
                return False, f"Website returned HTTP {resp.status_code} — it may be down or inaccessible"

            content_type = resp.headers.get("content-type", "").lower()
            if content_type and "text/html" not in content_type and "application/xhtml" not in content_type:
                if resp.request.method == "HEAD":
                    resp = client.get(url, timeout=15.0)
                    content_type = resp.headers.get("content-type", "").lower()
                    if content_type and "text/html" not in content_type and "application/xhtml" not in content_type:
                        return False, f"URL does not appear to be a website (content-type: {content_type})"

            return True, ""

    except httpx.ConnectError:
        return False, "Could not connect to the website — it may be down or blocking requests"
    except httpx.TimeoutException:
        return False, "Website took too long to respond (timeout after 15 seconds)"
    except Exception as e:
        return False, f"Website check failed: {str(e)}"


def process_website(
    presentation_id: int, url: str, media_dir: str, pres_dir: str,
    max_pages: int, background_template: str | None = None,
    crawl_mode: str = "full_site",
):
    """Background task: crawl website, generate slides.json, generate HTML webpage."""
    from app.services.website_crawler import crawl_website
    from app.services.website_html_generator import generate_website_webpage

    is_single = (crawl_mode == "single_page")
    logger.info(
        "process_website: id=%d, crawl_mode=%s, is_single=%s, max_pages=%d, url=%s",
        presentation_id, crawl_mode, is_single, max_pages, url,
    )

    # DEFENSIVE: force max_pages=1 in single_page mode so the crawler
    # cannot crawl more than 1 page even if max_pages was set differently.
    if is_single:
        max_pages = 1

    db = SessionLocal()
    start_time = time.time()

    try:
        estimated_pages = 1 if is_single else (max_pages if max_pages > 0 else 20)
        init_progress(presentation_id, estimated_pages + 2)

        def on_crawl_progress(current, total, message):
            update_progress(
                presentation_id,
                current_slide=current,
                phase="crawling",
                message=message,
            )

        # Check cancellation
        if is_cancelled(presentation_id):
            raise RuntimeError("Cancelled by user")

        # Phase 1: Crawl website
        crawl_msg = "Capturing this single page..." if is_single else "Starting website crawl..."
        update_progress(presentation_id, current_slide=0, phase="crawling", message=crawl_msg)
        result = crawl_website(
            url=url,
            presentation_id=presentation_id,
            media_dir=media_dir,
            max_pages=max_pages,
            progress_callback=on_crawl_progress,
            single_page=is_single,
        )

        # Check cancellation after crawl
        if is_cancelled(presentation_id):
            raise RuntimeError("Cancelled by user")

        # Phase 2: Save slides.json + store in DB for diffing
        slides_json_path = os.path.join(pres_dir, "slides.json")
        crawled_json_str = json.dumps(result, ensure_ascii=False, sort_keys=True)

        # Hash only the content (strip presentation_id which changes per record)
        hash_data = {k: v for k, v in result.items() if k != "presentation_id"}
        crawl_hash = hashlib.sha256(
            json.dumps(hash_data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

        with open(slides_json_path, "w", encoding="utf-8") as f:
            f.write(crawled_json_str)

        # Store crawled content in DB for future diff detection
        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        if presentation:
            presentation.crawled_content = crawled_json_str
            presentation.crawl_hash = crawl_hash
            db.commit()

        page_count = len(result.get("slides", []))
        update_progress(
            presentation_id,
            current_slide=page_count,
            phase="crawl_done",
            message=f"Crawling complete! {page_count} pages captured. Now generating presentation...",
        )

        # Small delay so frontend can show the crawl_done phase
        time.sleep(1)

        update_progress(
            presentation_id,
            current_slide=page_count,
            phase="generating",
            message="AI is generating your presentation slides...",
        )

        # Resolve background template path
        bg_template_path = None
        if background_template:
            candidate = os.path.join(_TEMPLATES_DIR, background_template)
            if os.path.exists(candidate):
                bg_template_path = candidate

        # Phase 2.5: Check if same URL has existing content with same hash (skip Claude)
        gen_result = None
        norm_url = _normalise_url_for_dedup(url)
        existing_same_url = (
            db.query(Presentation)
            .filter(
                Presentation.source_url.isnot(None),
                Presentation.status == "ready",
                Presentation.id != presentation_id,
                Presentation.crawl_hash.isnot(None),
            )
            .all()
        )
        for ex in existing_same_url:
            if (
                _normalise_url_for_dedup(ex.source_url) == norm_url
                and ex.crawl_hash == crawl_hash
            ):
                # Content unchanged — reuse existing webpage.html
                ex_pres_dir = os.path.join(settings.STORAGE_DIR, "presentations", str(ex.id))
                ex_webpage = os.path.join(ex_pres_dir, "webpage.html")
                if os.path.exists(ex_webpage):
                    new_webpage = os.path.join(pres_dir, "webpage.html")
                    shutil.copy2(ex_webpage, new_webpage)

                    # Apply new background template if selected
                    if bg_template_path:
                        from app.services.website_html_generator import _analyse_template_brightness
                        from app.services.html_template import apply_background_to_template
                        try:
                            html = open(new_webpage, "r", encoding="utf-8").read()
                            brightness = _analyse_template_brightness(bg_template_path)
                            html = apply_background_to_template(html, bg_template_path, brightness)
                            with open(new_webpage, "w", encoding="utf-8") as f:
                                f.write(html)
                        except Exception as e:
                            logger.warning("Failed to apply background to reused webpage: %s", e)

                    gen_result = {
                        "webpage_path": new_webpage,
                        "token_usage": {"input_tokens": 0, "output_tokens": 0},
                        "generation_mode": "reuse",
                    }
                    logger.info(
                        "Content unchanged for URL %s — reused webpage from presentation %d (0 tokens)",
                        url, ex.id,
                    )
                    break

        # Phase 2.7: Similarity-based adaptation search
        similar_pres_id = None
        sim_score = 0.0

        if gen_result is None:
            from app.services.similarity import find_most_similar_presentation

            update_progress(
                presentation_id, current_slide=0, phase="similarity",
                message="Searching for similar presentations...",
            )
            match = find_most_similar_presentation(
                crawled_json_str, db, exclude_id=presentation_id,
            )
            if match:
                similar_pres_id, similar_url, sim_score = match
                logger.info(
                    "Similarity match for presentation %d: #%d (%s) — score %.2f",
                    presentation_id, similar_pres_id, similar_url, sim_score,
                )
                update_progress(
                    presentation_id, current_slide=0, phase="generating",
                    message=f"Found similar presentation (score: {sim_score:.0%}) — adapting...",
                )

        # Phase 3: Generate HTML webpage (only if not reused)
        if gen_result is None:
            gen_result = generate_website_webpage(
                presentation_id, slides_json_path, media_dir, pres_dir,
                background_template_path=bg_template_path,
                similar_presentation_id=similar_pres_id,
                similarity_score=sim_score,
            )

        if not gen_result:
            if is_cancelled(presentation_id):
                raise RuntimeError("Cancelled by user")
            raise RuntimeError("Webpage generation returned None — check Claude API key / logs")

        webpage_path = gen_result["webpage_path"]
        token_usage = gen_result.get("token_usage")

        # Update DB
        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        presentation.status = "ready"
        presentation.slide_count = page_count
        presentation.title = result.get("title") or presentation.title
        presentation.slide_data_path = slides_json_path
        presentation.generation_mode = gen_result.get("generation_mode", "full")
        if gen_result.get("based_on_id"):
            presentation.based_on_id = gen_result["based_on_id"]
            presentation.similarity_score = gen_result["similarity_score"]

        log = db.query(UploadLog).filter(UploadLog.presentation_id == presentation_id).first()
        if log:
            log.status = "success"
            log.processing_time_ms = int((time.time() - start_time) * 1000)

        db.commit()

        # Build completion message with token info
        completion_msg = f"Done! {page_count} pages captured and presented."
        if token_usage:
            input_t = token_usage.get("input_tokens", 0)
            output_t = token_usage.get("output_tokens", 0)
            completion_msg += f" Tokens used: {input_t:,} input + {output_t:,} output = {input_t + output_t:,} total."
        if gen_result.get("based_on_id"):
            sim_pct = gen_result['similarity_score']
            completion_msg += (
                f" Adapted from presentation #{gen_result['based_on_id']}"
                f" (similarity: {sim_pct:.0%})."
            )
            # Estimate savings: from-scratch template path typically outputs
            # ~10-16K tokens of slide HTML. The JSON-patch approach outputs
            # only the text/image replacements (~2-4K tokens).
            if token_usage:
                est_from_scratch_output = 12000  # typical template-path output
                saved = est_from_scratch_output - output_t
                if saved > 0:
                    completion_msg += f" Estimated ~{saved:,} output tokens saved vs from-scratch."

        complete_progress(presentation_id, message=completion_msg, token_usage=token_usage)

    except Exception as e:
        error_str = str(e)
        if "Cancelled by user" in error_str:
            logger.info("Website processing cancelled for presentation %d", presentation_id)
            cancel_progress(presentation_id)
        else:
            logger.error("Website processing failed for presentation %d: %s", presentation_id, e, exc_info=True)
            fail_progress(presentation_id, error=error_str)

        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        if presentation:
            presentation.status = "cancelled" if "Cancelled by user" in error_str else "failed"
            presentation.error_message = error_str

        log = db.query(UploadLog).filter(UploadLog.presentation_id == presentation_id).first()
        if log:
            log.status = "cancelled" if "Cancelled by user" in error_str else "failed"
            log.error_message = error_str
            log.processing_time_ms = int((time.time() - start_time) * 1000)

        db.commit()
    finally:
        db.close()


def process_regeneration(
    presentation_id: int,
    crawl_mode: str = "full_site",
    max_pages: int = 0,
    background_template: str | None = None,
):
    """Background task: re-crawl the website, diff against stored content,
    and regenerate only if the content has changed.  Preserves chat-edit CSS
    by extracting the template from the CURRENT webpage before regeneration.
    """
    from app.services.website_crawler import crawl_website
    from app.services.website_html_generator import generate_website_webpage, _analyse_template_brightness
    from app.services.html_template import apply_background_to_template
    from datetime import datetime, timezone

    is_single = (crawl_mode == "single_page")
    db = SessionLocal()
    start_time = time.time()

    try:
        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        if not presentation or not presentation.source_url:
            fail_progress(presentation_id, error="Presentation not found or has no source URL")
            return

        url = presentation.source_url
        pres_dir = os.path.join(settings.STORAGE_DIR, "presentations", str(presentation_id))
        media_dir = presentation.media_dir or os.path.join(pres_dir, "media")
        os.makedirs(media_dir, exist_ok=True)

        if is_single:
            max_pages = 1

        estimated_pages = 1 if is_single else (max_pages if max_pages > 0 else 20)
        init_progress(presentation_id, estimated_pages + 2)

        # ── Phase 1: Re-crawl ──
        crawl_msg = "Re-crawling this single page..." if is_single else "Re-crawling website for changes..."
        update_progress(presentation_id, current_slide=0, phase="crawling", message=crawl_msg)

        def on_crawl_progress(current, total, message):
            update_progress(presentation_id, current_slide=current, phase="crawling", message=message)

        result = crawl_website(
            url=url,
            presentation_id=presentation_id,
            media_dir=media_dir,
            max_pages=max_pages,
            progress_callback=on_crawl_progress,
            single_page=is_single,
        )

        if is_cancelled(presentation_id):
            raise RuntimeError("Cancelled by user")

        # ── Phase 2: Compute hash and compare ──
        crawled_json_str = json.dumps(result, ensure_ascii=False, sort_keys=True)

        # Hash only the content (strip presentation_id which changes per record)
        hash_data = {k: v for k, v in result.items() if k != "presentation_id"}
        new_hash = hashlib.sha256(
            json.dumps(hash_data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        old_hash = presentation.crawl_hash

        page_count = len(result.get("slides", []))
        update_progress(
            presentation_id,
            current_slide=page_count,
            phase="crawl_done",
            message=f"Re-crawl complete! {page_count} pages captured. Comparing content...",
        )
        time.sleep(0.5)

        if new_hash == old_hash:
            # Content unchanged — check if background template changed
            bg_template_path = None
            if background_template:
                candidate = os.path.join(_TEMPLATES_DIR, background_template)
                if os.path.exists(candidate):
                    bg_template_path = candidate

            current_webpage = os.path.join(pres_dir, "webpage.html")
            if bg_template_path and os.path.exists(current_webpage):
                # Apply new background to existing webpage (0 AI tokens)
                update_progress(
                    presentation_id, current_slide=page_count,
                    phase="generating",
                    message="No content changes. Updating background template...",
                )
                try:
                    html = open(current_webpage, "r", encoding="utf-8").read()
                    brightness = _analyse_template_brightness(bg_template_path)
                    html = apply_background_to_template(html, bg_template_path, brightness)
                    with open(current_webpage, "w", encoding="utf-8") as f:
                        f.write(html)
                    presentation.status = "ready"
                    presentation.generation_mode = "bg_update"
                    db.commit()
                    complete_progress(
                        presentation_id,
                        message=f"Background updated! Content unchanged ({page_count} pages). 0 AI tokens used.",
                        token_usage={"input_tokens": 0, "output_tokens": 0},
                    )
                    return
                except Exception as e:
                    logger.warning("Failed to update background: %s", e)
                    # Fall through to normal "no changes" path

            # No content change and no background change
            presentation.status = "ready"
            db.commit()
            complete_progress(
                presentation_id,
                message=f"No changes detected in website content. Presentation unchanged ({page_count} pages).",
                token_usage={"input_tokens": 0, "output_tokens": 0},
            )
            return

        # ── Phase 3: Content changed — save new slides.json ──
        slides_json_path = os.path.join(pres_dir, "slides.json")
        with open(slides_json_path, "w", encoding="utf-8") as f:
            f.write(crawled_json_str)

        # Update crawled content in DB
        presentation.crawled_content = crawled_json_str
        presentation.crawl_hash = new_hash
        db.commit()

        # ── Phase 4: Backup current webpage.html ──
        current_webpage = os.path.join(pres_dir, "webpage.html")
        if os.path.exists(current_webpage):
            # Determine version number from existing backups
            version = 1
            while os.path.exists(os.path.join(pres_dir, f"webpage_v{version}.html")):
                version += 1
            backup_path = os.path.join(pres_dir, f"webpage_v{version}.html")
            shutil.copy2(current_webpage, backup_path)
            logger.info("Backed up webpage.html → %s", backup_path)

            # Extract template from current webpage (preserves chat-edit CSS)
            try:
                current_html = open(current_webpage, "r", encoding="utf-8").read()
                shell = extract_template_shell(current_html)
                if shell:
                    cache_template_from_webpage(current_webpage)
                    logger.info("Extracted template from current webpage (preserves chat edits)")
            except Exception as e:
                logger.warning("Failed to extract template from current webpage: %s", e)

        # ── Phase 5: Regenerate with template path ──
        update_progress(
            presentation_id,
            current_slide=page_count,
            phase="generating",
            message="Content changed! AI is regenerating slides...",
        )

        # Resolve background template
        bg_template_path = None
        if background_template:
            candidate = os.path.join(_TEMPLATES_DIR, background_template)
            if os.path.exists(candidate):
                bg_template_path = candidate

        gen_result = generate_website_webpage(
            presentation_id, slides_json_path, media_dir, pres_dir,
            background_template_path=bg_template_path,
        )

        if not gen_result:
            if is_cancelled(presentation_id):
                raise RuntimeError("Cancelled by user")
            raise RuntimeError("Webpage regeneration returned None")

        # Inject regeneration comment into the HTML
        webpage_path = gen_result["webpage_path"]
        try:
            html = open(webpage_path, "r", encoding="utf-8").read()
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            regen_comment = f"<!-- Regenerated: {timestamp} | Version: {version + 1 if os.path.exists(os.path.join(pres_dir, 'webpage_v1.html')) else 1} -->"
            html = html.replace("<!DOCTYPE", regen_comment + "\n<!DOCTYPE", 1)
            if "<!DOCTYPE" not in html:
                html = regen_comment + "\n" + html
            with open(webpage_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            logger.warning("Failed to inject regeneration comment: %s", e)

        # ── Phase 6: Append to edit_history.json ──
        try:
            history_path = os.path.join(pres_dir, "edit_history.json")
            history = []
            if os.path.exists(history_path):
                with open(history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)

            history.append({
                "version": len(history) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prompt": "[Auto-regeneration] Website content changed — slides regenerated",
                "slides_affected": list(range(1, page_count + 1)),
                "generation_mode": gen_result.get("generation_mode", "template"),
            })
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.warning("Failed to update edit_history.json: %s", e)

        # ── Phase 7: Update DB ──
        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        presentation.status = "ready"
        presentation.slide_count = page_count
        presentation.title = result.get("title") or presentation.title
        presentation.slide_data_path = slides_json_path
        presentation.generation_mode = gen_result.get("generation_mode", "diff_patch")
        db.commit()

        # Completion message
        token_usage = gen_result.get("token_usage")
        completion_msg = f"Regeneration complete! {page_count} pages refreshed."
        if token_usage:
            input_t = token_usage.get("input_tokens", 0)
            output_t = token_usage.get("output_tokens", 0)
            completion_msg += f" Tokens: {input_t:,} in + {output_t:,} out = {input_t + output_t:,} total."

        complete_progress(presentation_id, message=completion_msg, token_usage=token_usage)

    except Exception as e:
        error_str = str(e)
        if "Cancelled by user" in error_str:
            logger.info("Regeneration cancelled for presentation %d", presentation_id)
            cancel_progress(presentation_id)
        else:
            logger.error("Regeneration failed for presentation %d: %s", presentation_id, e, exc_info=True)
            fail_progress(presentation_id, error=error_str)

        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        if presentation:
            presentation.status = "ready"  # Restore to ready on failure (don't leave stuck in processing)
            presentation.error_message = error_str if "Cancelled" not in error_str else None
        db.commit()
    finally:
        db.close()


# ── Endpoints ──

@router.post("/check-url", response_model=URLCheckResponse)
async def check_url_exists(
    body: URLCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Check if a URL has already been processed into a presentation."""
    try:
        url = _validate_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    norm = _normalise_url_for_dedup(url)

    presentations = (
        db.query(Presentation)
        .filter(Presentation.source_url.isnot(None))
        .all()
    )

    for pres in presentations:
        if _normalise_url_for_dedup(pres.source_url) == norm and pres.status == "ready":
            return URLCheckResponse(
                exists=True,
                presentation_id=pres.id,
                title=pres.title,
                status=pres.status,
                created_at=pres.created_at,
            )

    return URLCheckResponse(exists=False)


@router.post("/cancel/{presentation_id}")
async def cancel_generation(
    presentation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Cancel an in-progress presentation generation."""
    presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    if presentation.status != "processing":
        raise HTTPException(status_code=400, detail="Presentation is not currently processing")

    cancel_progress(presentation_id)
    presentation.status = "cancelled"
    presentation.error_message = "Cancelled by user"
    db.commit()

    return {"detail": "Generation cancelled", "presentation_id": presentation_id}


@router.post("/regenerate/{presentation_id}")
async def regenerate_presentation(
    presentation_id: int,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Re-crawl the source URL and regenerate if content has changed."""
    presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    if not presentation.source_url:
        raise HTTPException(status_code=400, detail="Presentation has no source URL (not a website presentation)")

    if presentation.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Presentation is currently '{presentation.status}' — can only regenerate when 'ready'",
        )

    # Set to processing
    presentation.status = "processing"
    db.commit()

    logger.info(
        "Regeneration requested: presentation_id=%d, url=%s, crawl_mode=%s",
        presentation_id, presentation.source_url, body.crawl_mode,
    )

    background_tasks.add_task(
        process_regeneration,
        presentation_id,
        body.crawl_mode,
        body.max_pages,
        body.background_template,
    )

    return {
        "detail": "Regeneration started",
        "presentation_id": presentation_id,
        "source_url": presentation.source_url,
    }


@router.get("/background-templates", response_model=list[BackgroundTemplateResponse])
async def list_background_templates(user: User = Depends(get_admin_user)):
    """List available background template images."""
    templates = []
    if os.path.isdir(_TEMPLATES_DIR):
        for fname in sorted(os.listdir(_TEMPLATES_DIR)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                name = os.path.splitext(fname)[0].replace("_", " ")
                templates.append(BackgroundTemplateResponse(
                    name=name,
                    filename=fname,
                    url=f"/api/v1/admin/background-templates/{fname}",
                ))
    return templates


@router.get("/background-templates/{filename}")
async def serve_background_template(filename: str):
    """Serve a background template image."""
    filepath = os.path.join(_TEMPLATES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(
        filepath,
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.post("/submit-url", response_model=PresentationResponse, status_code=202)
async def submit_website_url(
    body: WebsiteSubmitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Submit a website URL to generate a presentation from its pages."""
    try:
        url = _validate_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Domain validation (DNS check) ──
    domain_ok, domain_err = _check_domain_exists(url)
    if not domain_ok:
        raise HTTPException(status_code=422, detail=domain_err)

    # ── Website legitimacy check (HTTP check) ──
    site_ok, site_err = _check_website_legitimacy(url)
    if not site_ok:
        raise HTTPException(status_code=422, detail=site_err)

    # ── Duplicate URL check (if not force_regenerate) ──
    if not body.force_regenerate:
        norm = _normalise_url_for_dedup(url)
        existing = (
            db.query(Presentation)
            .filter(Presentation.source_url.isnot(None), Presentation.status == "ready")
            .all()
        )
        for pres in existing:
            if _normalise_url_for_dedup(pres.source_url) == norm:
                return pres

    max_pages = body.max_pages
    if max_pages < 0:
        raise HTTPException(status_code=400, detail="max_pages cannot be negative")
    if max_pages > 0:
        max_pages = min(max_pages, settings.MAX_CRAWL_PAGES)

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    presentation = Presentation(
        title=domain,
        original_filename=f"{domain} (website)",
        file_path="",
        slide_data_path="",
        media_dir="",
        slide_count=0,
        status="processing",
        source_url=url,
        uploaded_by=user.id,
    )
    db.add(presentation)
    db.flush()

    pres_dir = os.path.join(settings.STORAGE_DIR, "presentations", str(presentation.id))
    media_dir = os.path.join(pres_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    presentation.media_dir = media_dir

    log = UploadLog(
        presentation_id=presentation.id,
        original_filename=f"{domain} (website)",
        file_size_bytes=0,
        status="processing",
        uploaded_by=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()
    db.refresh(presentation)

    logger.info(
        "Submitting website job: presentation_id=%d, url=%s, crawl_mode=%s, max_pages=%d",
        presentation.id, url, body.crawl_mode, max_pages,
    )

    background_tasks.add_task(
        process_website,
        presentation.id,
        url,
        media_dir,
        pres_dir,
        max_pages,
        body.background_template,
        body.crawl_mode,
    )

    return presentation