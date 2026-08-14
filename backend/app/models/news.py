import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class NewsItem(Base, UUIDPKMixin):
    __tablename__ = "news"

    source: Mapped[str] = mapped_column(String)  # e.g. "economic_times_rss"
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    companies: Mapped[list] = mapped_column(JSON, default=list)  # ["TCS", ...]
    sectors: Mapped[list] = mapped_column(JSON, default=list)


class NewsAnalysis(Base, UUIDPKMixin):
    """Structured FinBERT/rule-based output (Section 7). Never raw prose fed to Qwen."""

    __tablename__ = "news_analysis"

    news_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("news.id"))
    event_type: Mapped[str] = mapped_column(String)  # earnings/guidance/management/macro/regulatory/other
    sentiment: Mapped[float] = mapped_column(Float)  # -1..1
    confidence: Mapped[float] = mapped_column(Float)  # 0..1
    relevance: Mapped[float] = mapped_column(Float)  # 0..1
    importance: Mapped[float] = mapped_column(Float)  # 0..1
    model_name: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
