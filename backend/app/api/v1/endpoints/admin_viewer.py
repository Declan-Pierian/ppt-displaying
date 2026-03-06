"""Admin viewer API endpoints: references, chat editing, undo, edit history."""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.core.security import decode_access_token
from app.models.database import get_db
from app.models.user import User
from app.models.presentation import Presentation
from app.schemas.presentation import (
    ReferencesResponse,
    SlideReferenceData,
    ChatEditRequest,
    ChatEditResponse,
    UndoResponse,
    EditHistoryResponse,
)
from app.services.presentation_editor import (
    apply_chat_edit,
    undo_edit,
    get_edit_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-viewer"])


def _get_presentation(db: Session, presentation_id: int) -> Presentation:
    """Get presentation by ID (admin — no is_active check)."""
    pres = db.query(Presentation).filter(Presentation.id == presentation_id).first()
    if not pres:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return pres


def _pres_dir(presentation_id: int) -> str:
    return os.path.join(settings.STORAGE_DIR, "presentations", str(presentation_id))


# ── References ───────────────────────────────────────────────────────────────

@router.get(
    "/presentations/{presentation_id}/references",
    response_model=ReferencesResponse,
)
def get_references(
    presentation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Return source references for each slide from slides.json."""
    pres = _get_presentation(db, presentation_id)

    # Determine source type
    source_type = "website" if pres.source_url else "pptx"

    # Load slides.json
    if not pres.slide_data_path or not os.path.exists(pres.slide_data_path):
        return ReferencesResponse(
            presentation_id=pres.id,
            title=pres.title,
            source_url=pres.source_url,
            source_type=source_type,
            slides=[],
        )

    with open(pres.slide_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    slides_ref: list[SlideReferenceData] = []
    for slide in data.get("slides", []):
        slide_num = slide.get("slide_number") or slide.get("page_number", 0)
        slides_ref.append(
            SlideReferenceData(
                slide_number=slide_num,
                page_url=slide.get("page_url"),
                page_title=slide.get("page_title"),
                content=slide.get("content", {}),
            )
        )

    return ReferencesResponse(
        presentation_id=pres.id,
        title=pres.title,
        source_url=pres.source_url,
        source_type=source_type,
        slides=slides_ref,
    )


# ── Admin webpage (no is_active check) ──────────────────────────────────────
# Accepts auth via query param ?token=... because iframes can't send headers.

def _verify_admin_token(token: str, db: Session) -> User:
    """Verify a JWT token string and return the admin user, or raise 401."""
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username: str = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/presentations/{presentation_id}/admin-webpage")
def admin_serve_webpage(
    presentation_id: int,
    token: str = Query(..., description="JWT token for iframe authentication"),
    db: Session = Depends(get_db),
):
    """Serve webpage.html for admins (bypasses is_active check).

    Uses a query-param token because iframes cannot send Authorization headers.
    """
    _verify_admin_token(token, db)
    pres = _get_presentation(db, presentation_id)

    if pres.status != "ready":
        raise HTTPException(status_code=400, detail=f"Presentation status is '{pres.status}', not ready")

    pres_dir = _pres_dir(presentation_id)
    webpage_path = os.path.join(pres_dir, "webpage.html")

    if not os.path.exists(webpage_path):
        raise HTTPException(status_code=404, detail="Webpage not yet generated")

    with open(webpage_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    return HTMLResponse(content=html_content)


# ── Chat editing ─────────────────────────────────────────────────────────────

@router.post(
    "/presentations/{presentation_id}/chat-edit",
    response_model=ChatEditResponse,
)
def chat_edit_presentation(
    presentation_id: int,
    body: ChatEditRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Process an AI edit prompt and modify the presentation HTML."""
    pres = _get_presentation(db, presentation_id)

    if pres.status != "ready":
        raise HTTPException(status_code=400, detail="Can only edit presentations with status 'ready'")

    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Edit prompt cannot be empty")

    pres_dir = _pres_dir(presentation_id)
    result = apply_chat_edit(
        pres_dir=pres_dir,
        prompt=body.prompt.strip(),
        slide_numbers=body.slide_numbers,
        presentation_id=presentation_id,
    )

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["message"])

    return ChatEditResponse(**result)


# ── Undo ─────────────────────────────────────────────────────────────────────

@router.post(
    "/presentations/{presentation_id}/undo",
    response_model=UndoResponse,
)
def undo_presentation_edit(
    presentation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Revert the last edit to the presentation."""
    _get_presentation(db, presentation_id)

    pres_dir = _pres_dir(presentation_id)
    result = undo_edit(pres_dir)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return UndoResponse(**result)


# ── Edit history ─────────────────────────────────────────────────────────────

@router.get(
    "/presentations/{presentation_id}/edit-history",
    response_model=EditHistoryResponse,
)
def get_presentation_edit_history(
    presentation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    """Return the edit history for a presentation."""
    _get_presentation(db, presentation_id)

    pres_dir = _pres_dir(presentation_id)
    history = get_edit_history(pres_dir)

    return EditHistoryResponse(**history)
