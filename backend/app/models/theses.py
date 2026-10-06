"""Theses and evidence-backed assessments (Portfolio Intelligence Engine
Phase 09, plan section 5.4). A thesis is the USER's own confirmed reason for a
holding plus falsifiable conditions; it is versioned (every edit is a new
revision) and never rewritten by evidence. New evidence creates a
ThesisAssessment: a qualitative PROPOSAL (supported / mixed / weakened /
insufficient) that the user reviews. There is no numeric conviction score, and
a thesis never overrides a portfolio suitability decision."""

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Thesis(Base, UUIDPKMixin):
    __tablename__ = "theses"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_thesis_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    symbol: Mapped[str] = mapped_column(String)
    ownership: Mapped[str] = mapped_column(String)  # owned (verified in the snapshot) | considered (user-declared)
    reason: Mapped[str] = mapped_column(String)  # the user's own words
    horizon_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # [{"id": "c1", "text": "...", "kind": "supports" | "invalidates"}]
    conditions: Mapped[list] = mapped_column(JSON)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | closed
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ThesisAssessment(Base, UUIDPKMixin):
    __tablename__ = "thesis_assessments"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    thesis_chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    thesis_version: Mapped[int] = mapped_column(Integer)
    research_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_sessions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String)  # supported | mixed | weakened | insufficient
    prior_assessment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    change_log: Mapped[str] = mapped_column(String)
    per_condition: Mapped[list] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)       # per supported fact: text, sources, lineage, times, independence
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contradictions: Mapped[list] = mapped_column(JSON)
    gaps: Mapped[list] = mapped_column(JSON)
    model_info: Mapped[dict] = mapped_column(JSON)     # whether/which model mapped evidence to conditions; never a score
    policy_version: Mapped[str] = mapped_column(String)
    review_status: Mapped[str] = mapped_column(String, default="pending")  # pending | acknowledged
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ThesisEvent(Base, UUIDPKMixin):
    """A recorded observation about a thesis' holding (e.g. a price move). Events never change a thesis' status."""

    __tablename__ = "thesis_events"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_thesis_events_dedup"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    thesis_chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String)  # price_move
    observed: Mapped[dict] = mapped_column(JSON)
    dedup_key: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
