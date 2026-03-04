import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "PPT Viewer"
    DEBUG: bool = False

    # Storage
    STORAGE_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")

    # Database
    DATABASE_URL: str = "sqlite:///./ppt_viewer.db"

    # JWT
    SECRET_KEY: str = "change-this-to-a-secure-random-string-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 100

    # Claude API (for HTML webpage generation)
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
