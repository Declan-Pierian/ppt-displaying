from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_admin_user
from app.models.database import get_db
from app.models.user import User
from app.models.upload_log import UploadLog
from app.schemas.presentation import UploadLogResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs", response_model=list[UploadLogResponse])
def get_upload_logs(
    status: str | None = Query(None, description="Filter by status: success, failed, processing"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    query = db.query(UploadLog).order_by(UploadLog.created_at.desc())
    if status:
        query = query.filter(UploadLog.status == status)
    return query.offset(offset).limit(limit).all()
