"""Typed background jobs for the Portfolio Intelligence Engine. Separate from
RecommendationJob (whose worker path always runs the legacy Nifty pipeline).
Same lease + worker_token fencing pattern: every terminal write and the
publication of the job's result are only applied if the token still matches."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class PortfolioJob(Base, UUIDPKMixin):
    __tablename__ = "portfolio_jobs"
    __table_args__ = (UniqueConstraint("kind", "account_id", "request_key", name="uq_portfolio_jobs_request"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String)  # account_sync | review | catalogue_refresh | market_snapshot | candle_backfill | signals_compute | kronos_forecast | ledger_study | ter_refresh | fundamentals_refresh
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_accounts.id"), nullable=True
    )
    request_key: Mapped[str] = mapped_column(String)
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String, default="queued")
    # Typed provider outcome: AUTH_EXPIRED | RATE_LIMITED | PARTIAL_DATA | UNAVAILABLE | IDENTITY_CONFLICT | INTERNAL
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String, nullable=True)
    # Backoff for bounded retries: a queued job is not claimable before this time.
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_import_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_imports.id"), nullable=True
    )
    # Plain id (no FK: decision_outcomes already references this table).
    result_outcome_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # job input (e.g. which securities), never secrets
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # small outcome summary (catalogue_refresh); never payloads
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
