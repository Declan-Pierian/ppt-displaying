"""API endpoint for generating presentations from website URLs."""

import os
import socket
import time
import json
import logging
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
)
from app.services.extraction.progress import (
    init_progress, update_progress, complete_progress, fail_progress,
    cancel_progress, is_cancelled,
)

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
):
    """Background task: crawl website, generate slides.json, generate HTML webpage."""
    from app.services.website_crawler import crawl_website
    from app.services.website_html_generator import generate_website_webpage

    db = SessionLocal()
    start_time = time.time()

    try:
        estimated_pages = max_pages if max_pages > 0 else 20
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
        update_progress(presentation_id, current_slide=0, phase="crawling", message="Starting website crawl...")
        result = crawl_website(
            url=url,
            presentation_id=presentation_id,
            media_dir=media_dir,
            max_pages=max_pages,
            progress_callback=on_crawl_progress,
        )

        # Check cancellation after crawl
        if is_cancelled(presentation_id):
            raise RuntimeError("Cancelled by user")

        # Phase 2: Save slides.json
        slides_json_path = os.path.join(pres_dir, "slides.json")
        with open(slides_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)

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

        # Phase 3: Generate HTML webpage
        gen_result = generate_website_webpage(
            presentation_id, slides_json_path, media_dir, pres_dir,
            background_template_path=bg_template_path,
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

    background_tasks.add_task(
        process_website,
        presentation.id,
        url,
        media_dir,
        pres_dir,
        max_pages,
        body.background_template,
    )

    return presentation