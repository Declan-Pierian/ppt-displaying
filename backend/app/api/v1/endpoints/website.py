"""API endpoint for generating presentations from website URLs."""

import os
import time
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.models.database import get_db, SessionLocal
from app.models.user import User
from app.models.presentation import Presentation
from app.models.upload_log import UploadLog
from app.schemas.presentation import PresentationResponse, WebsiteSubmitRequest
from app.services.extraction.progress import init_progress, update_progress, complete_progress, fail_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _validate_url(url: str) -> str:
    """Validate and normalise the URL."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("Invalid URL: no valid domain found")

    return url


def process_website(presentation_id: int, url: str, media_dir: str, pres_dir: str, max_pages: int):
    """Background task: crawl website, generate slides.json, generate HTML webpage."""
    from app.services.website_crawler import crawl_website
    from app.services.website_html_generator import generate_website_webpage

    db = SessionLocal()
    start_time = time.time()

    try:
        # Estimate total steps for progress (use 20 as estimate if crawling all)
        estimated_pages = max_pages if max_pages > 0 else 20
        init_progress(presentation_id, estimated_pages + 2)

        # Progress callback for the crawler
        def on_crawl_progress(current, total, message):
            update_progress(
                presentation_id,
                current_slide=current,
                phase="crawling",
                message=message,
            )

        # Phase 1: Crawl website
        update_progress(presentation_id, current_slide=0, phase="crawling", message="Starting website crawl...")
        result = crawl_website(
            url=url,
            presentation_id=presentation_id,
            media_dir=media_dir,
            max_pages=max_pages,
            progress_callback=on_crawl_progress,
        )

        # Phase 2: Save slides.json
        slides_json_path = os.path.join(pres_dir, "slides.json")
        with open(slides_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)

        page_count = len(result.get("slides", []))
        update_progress(
            presentation_id,
            current_slide=page_count,
            phase="webpage",
            message="Generating presentation with AI...",
        )

        # Phase 3: Generate HTML webpage
        webpage_path = generate_website_webpage(
            presentation_id, slides_json_path, media_dir, pres_dir
        )

        if not webpage_path:
            raise RuntimeError("Webpage generation returned None — check Claude API key / logs")

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
        complete_progress(presentation_id, message=f"Done! {page_count} pages captured and presented.")

    except Exception as e:
        logger.error("Website processing failed for presentation %d: %s", presentation_id, e, exc_info=True)
        fail_progress(presentation_id, error=str(e))

        presentation = db.query(Presentation).filter(Presentation.id == presentation_id).first()
        if presentation:
            presentation.status = "failed"
            presentation.error_message = str(e)

        log = db.query(UploadLog).filter(UploadLog.presentation_id == presentation_id).first()
        if log:
            log.status = "failed"
            log.error_message = str(e)
            log.processing_time_ms = int((time.time() - start_time) * 1000)

        db.commit()
    finally:
        db.close()


@router.post("/submit-url", response_model=PresentationResponse, status_code=202)
async def submit_website_url(
    body: WebsiteSubmitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Submit a website URL to generate a presentation from its pages."""
    # Validate URL
    try:
        url = _validate_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 0 = crawl all pages; positive = cap to configured max
    max_pages = body.max_pages
    if max_pages < 0:
        raise HTTPException(status_code=400, detail="max_pages cannot be negative")
    if max_pages > 0:
        max_pages = min(max_pages, settings.MAX_CRAWL_PAGES)

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    # Create presentation record
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

    # Create directories
    pres_dir = os.path.join(settings.STORAGE_DIR, "presentations", str(presentation.id))
    media_dir = os.path.join(pres_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    presentation.media_dir = media_dir

    # Upload log
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

    # Kick off background processing
    background_tasks.add_task(
        process_website,
        presentation.id,
        url,
        media_dir,
        pres_dir,
        max_pages,
    )

    return presentation
