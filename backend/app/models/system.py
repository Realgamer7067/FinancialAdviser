import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Uuid
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

    name: Mapped[str] = mapped_column(String, unique=True)  # "yfinance" / "rss_economic_times" / ...
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
    # Written by app/pipelines/progress.py::JobProgressTracker through its OWN
    # session (not the pipeline's) so the poller -- a separate connection --
    # sees updates mid-run instead of only after the pipeline's single final
    # commit. Left untouched on failure so a failed job still shows the stage
    # it died on.
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    progress_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    stage_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {current_symbol, index, total}
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lease/fencing (docs/V2-RETHINK.md P0): a claim is only valid while
    # lease_expires_at is in the future. worker_token identifies which
    # specific claim/attempt is holding the job -- a stale attempt that
    # eventually wakes up must not overwrite a newer attempt's result, so
    # every completion/failure/progress write checks its token still matches
    # before writing.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String, nullable=True)
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
