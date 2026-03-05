import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.models.database import get_db
from app.models.user import User
from app.models.presentation import Presentation
from app.schemas.presentation import (
    PresentationResponse,
    PresentationPublicResponse,
    PresentationToggleRequest,
)

router = APIRouter(tags=["presentations"])


# --- Admin endpoints ---

@router.get("/admin/presentations", response_model=list[PresentationResponse])
def list_all_presentations(
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    return db.query(Presentation).order_by(Presentation.created_at.desc()).all()


@router.patch("/admin/presentations/{presentation_id}", response_model=PresentationResponse)
def toggle_presentation(
    presentation_id: int,
    body: PresentationToggleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    pres = db.query(Presentation).filter(Presentation.id == presentation_id).first()
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")
    pres.is_active = body.is_active
    db.commit()
    db.refresh(pres)
    return pres


@router.delete("/admin/presentations/{presentation_id}")
def delete_presentation(
    presentation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    import shutil
    import logging
    logger = logging.getLogger(__name__)

    pres = db.query(Presentation).filter(Presentation.id == presentation_id).first()
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")

    # Delete files from disk
    pres_dir = os.path.join(
        settings.STORAGE_DIR, "presentations", str(presentation_id)
    )
    upload_dir = os.path.join(
        settings.STORAGE_DIR, "uploads", str(presentation_id)
    )

    for dir_path in [pres_dir, upload_dir]:
        if os.path.exists(dir_path):
            try:
                shutil.rmtree(dir_path)
                logger.info("Deleted directory: %s", dir_path)
            except Exception as e:
                logger.error("Failed to delete %s: %s", dir_path, e)

    # Delete from database
    db.delete(pres)
    db.commit()
    return {"detail": "Presentation deleted"}


# --- Public endpoints ---

@router.get("/presentations", response_model=list[PresentationPublicResponse])
def list_active_presentations(db: Session = Depends(get_db)):
    return (
        db.query(Presentation)
        .filter(Presentation.is_active == True, Presentation.status == "ready")
        .order_by(Presentation.created_at.desc())
        .all()
    )


@router.get("/presentations/{presentation_id}", response_model=PresentationPublicResponse)
def get_presentation(presentation_id: int, db: Session = Depends(get_db)):
    pres = (
        db.query(Presentation)
        .filter(
            Presentation.id == presentation_id,
            Presentation.is_active == True,
            Presentation.status == "ready",
        )
        .first()
    )
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return pres


@router.get("/presentations/{presentation_id}/slides")
def get_slides(presentation_id: int, db: Session = Depends(get_db)):
    pres = (
        db.query(Presentation)
        .filter(
            Presentation.id == presentation_id,
            Presentation.is_active == True,
            Presentation.status == "ready",
        )
        .first()
    )
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")

    if not os.path.exists(pres.slide_data_path):
        raise HTTPException(status_code=404, detail="Slide data not found")

    with open(pres.slide_data_path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/presentations/{presentation_id}/slides/{slide_index}")
def get_single_slide(presentation_id: int, slide_index: int, db: Session = Depends(get_db)):
    pres = (
        db.query(Presentation)
        .filter(
            Presentation.id == presentation_id,
            Presentation.is_active == True,
            Presentation.status == "ready",
        )
        .first()
    )
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")

    with open(pres.slide_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if slide_index < 0 or slide_index >= len(data["slides"]):
        raise HTTPException(status_code=404, detail="Slide not found")

    return data["slides"][slide_index]


@router.get("/presentations/{presentation_id}/webpage")
def serve_webpage(presentation_id: int, db: Session = Depends(get_db)):
    """Serve the AI-generated HTML webpage for a presentation."""
    pres = (
        db.query(Presentation)
        .filter(
            Presentation.id == presentation_id,
            Presentation.is_active == True,
            Presentation.status == "ready",
        )
        .first()
    )
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")

    pres_dir = os.path.join(
        settings.STORAGE_DIR, "presentations", str(presentation_id)
    )
    webpage_path = os.path.join(pres_dir, "webpage.html")

    if not os.path.exists(webpage_path):
        raise HTTPException(
            status_code=404,
            detail="Webpage not yet generated for this presentation",
        )

    with open(webpage_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    return HTMLResponse(content=html_content)


@router.get("/pierian-logo")
def serve_pierian_logo():
    """Serve the Pierian company logo."""
    # Navigate from backend/app/api/v1/endpoints/ up to backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    logo_path = os.path.join(backend_dir, "pierian_image", "New_Pierian_Logo.jpg")
    if not os.path.exists(logo_path):
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(
        logo_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/media/{presentation_id}/{filename:path}")
def serve_media(presentation_id: int, filename: str, db: Session = Depends(get_db)):
    media_path = os.path.join(
        settings.STORAGE_DIR, "presentations", str(presentation_id), "media", filename
    )
    if not os.path.exists(media_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    return FileResponse(
        media_path,
        headers={"Cache-Control": "public, max-age=86400"},
    )
