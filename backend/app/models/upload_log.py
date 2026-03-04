from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from app.models.database import Base


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    presentation_id = Column(Integer, ForeignKey("presentations.id"), nullable=True)
    original_filename = Column(String(255), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
