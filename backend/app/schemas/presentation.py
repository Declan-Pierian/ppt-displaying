from datetime import datetime

from pydantic import BaseModel


class PresentationResponse(BaseModel):
    id: int
    title: str
    original_filename: str
    slide_count: int
    slide_width_emu: int
    slide_height_emu: int
    status: str
    is_active: bool
    error_message: str | None = None
    source_url: str | None = None
    generation_mode: str | None = None
    based_on_id: int | None = None
    similarity_score: float | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class PresentationPublicResponse(BaseModel):
    id: int
    title: str
    slide_count: int
    slide_width_emu: int
    slide_height_emu: int
    source_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class PresentationToggleRequest(BaseModel):
    is_active: bool


class WebsiteSubmitRequest(BaseModel):
    url: str
    max_pages: int = 0  # 0 = crawl all discovered pages (up to safety cap)
    background_template: str | None = None  # e.g. "Pierian_Background_1.jpg"
    force_regenerate: bool = False  # If True, regenerate even if URL was already processed
    crawl_mode: str = "full_site"  # "full_site" or "single_page"


class RegenerateRequest(BaseModel):
    crawl_mode: str = "full_site"  # "full_site" or "single_page"
    max_pages: int = 0
    background_template: str | None = None


class URLCheckRequest(BaseModel):
    url: str


class URLCheckResponse(BaseModel):
    exists: bool
    presentation_id: int | None = None
    title: str | None = None
    status: str | None = None
    created_at: datetime | None = None


class BackgroundTemplateResponse(BaseModel):
    name: str
    filename: str
    url: str


# ── References & Chat Editing schemas ──

class SlideReferenceData(BaseModel):
    slide_number: int
    page_url: str | None = None
    page_title: str | None = None
    content: dict = {}


class ReferencesResponse(BaseModel):
    presentation_id: int
    title: str
    source_url: str | None = None
    source_type: str  # "website" or "pptx"
    slides: list[SlideReferenceData]


class ChatEditRequest(BaseModel):
    prompt: str
    slide_numbers: list[int] | None = None  # None = AI decides


class ChatEditResponse(BaseModel):
    success: bool
    message: str
    version: int
    modified_slides: list[int]
    token_usage: dict | None = None


class UndoResponse(BaseModel):
    success: bool
    version: int
    message: str


class EditHistoryEntry(BaseModel):
    version: int
    timestamp: str
    prompt: str | None = None
    slides_affected: list[int] = []


class EditHistoryResponse(BaseModel):
    versions: list[EditHistoryEntry]
    current_version: int


class UploadLogResponse(BaseModel):
    id: int
    presentation_id: int | None = None
    original_filename: str
    file_size_bytes: int
    status: str
    error_message: str | None = None
    processing_time_ms: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True
