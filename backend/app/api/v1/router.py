from fastapi import APIRouter

from app.api.v1.endpoints import auth, upload, presentations, logs, progress, website

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(upload.router)
api_router.include_router(presentations.router)
api_router.include_router(logs.router)
api_router.include_router(progress.router)
api_router.include_router(website.router)
