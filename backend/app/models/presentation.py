from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from app.models.database import Base


class Presentation(Base):
    __tablename__ = "presentations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    slide_data_path = Column(String(500), nullable=False)
    media_dir = Column(String(500), nullable=False)
    slide_count = Column(Integer, nullable=False, default=0)
    slide_width_emu = Column(BigInteger, nullable=False, default=12192000)
    slide_height_emu = Column(BigInteger, nullable=False, default=6858000)
    status = Column(String(20), nullable=False, default="processing")
    error_message = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
