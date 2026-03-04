from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from app.models.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="admin")
    created_at = Column(DateTime, server_default=func.now())
