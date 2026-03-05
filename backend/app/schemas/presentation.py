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
