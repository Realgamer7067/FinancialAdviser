"""Living-review records (Portfolio Intelligence Engine Phase 08): typed change
events, the deduplicated inbox, and once-a-day scheduler markers."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class PortfolioEvent(Base, UUIDPKMixin):
    """Something that may invalidate derived artifacts. Duplicates coalesce on dedup_key."""

    __tablename__ = "portfolio_events"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_portfolio_events_dedup"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # state_built | valuation_published | import_published | sync_failed | auth_expired | scheduled_close
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String)
    affected: Mapped[dict] = mapped_column(JSON)  # entity ids touched
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InboxIssue(Base, UUIDPKMixin):
    """One row per issue FINGERPRINT (not per quote or per review). Lifecycle:
    open -> snoozed | dismissed | resolved; a dismissed issue only re-opens on a
    material change (escalated severity or a clearly larger measure)."""

    __tablename__ = "inbox_issues"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_inbox_user_fingerprint"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)  # urgent | review | information
    title: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(String)
    measure: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open | snoozed | dismissed | resolved
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snooze_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_measure: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    dismissed_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outcome_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    state_version_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SchedulerRun(Base, UUIDPKMixin):
    """Marker that a scheduled run already happened for a day; the unique key makes
    the API process and a worker agree without talking to each other."""

    __tablename__ = "scheduler_runs"
    __table_args__ = (UniqueConstraint("kind", "run_date", name="uq_scheduler_kind_date"),)

    kind: Mapped[str] = mapped_column(String)
    run_date: Mapped[date] = mapped_column(Date)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict] = mapped_column(JSON)
