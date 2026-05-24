from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base

class KnownApp(Base):
    __tablename__ = "known_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable= False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable= False, index=True)

    aliases: Mapped[list] = mapped_column(JSONB, default=list)

    exe_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    process_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    app_type: Mapped[str] = mapped_column(String(50), default="unknown")
    source: Mapped[str] = mapped_column(String(80), default="scanner")

    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )