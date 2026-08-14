import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ModelVersion(Base, UUIDPKMixin):
    """Every AI/model output must reference one of these (Section 26)."""

    __tablename__ = "model_versions"

    model_name: Mapped[str] = mapped_column(String)  # Qwen / Kronos / FinBERT / mean_variance
    version: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataSource(Base, UUIDPKMixin):
    """Provider/connection status for the admin/debug page (Section 69) and the
    stale-data gate (Section 65)."""

    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String, unique=True)  # "upstox" / "rss_economic_times" / ...
    kind: Mapped[str] = mapped_column(String)  # market / news / fundamentals / llm
    status: Mapped[str] = mapped_column(String, default="unconfigured")  # ok/degraded/error/unconfigured
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class RecommendationJob(Base, UUIDPKMixin, TimestampMixin):
    """Background job queue row (Section 70) -- the API never blocks on the
    council/pipeline synchronously."""

    __tablename__ = "recommendation_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String, default="queued")  # queued/running/done/failed
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_council_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("council_runs.id"), nullable=True
    )


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
