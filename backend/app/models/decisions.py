"""Published decisions (Portfolio Intelligence Engine Phase 07). A DecisionOutcome
is immutable history (including the 'HOLD' outcome of a review that found
nothing). CurrentDecision is the single pointer per user, only ever moved inside
the fenced publication transaction (app/portfolio_intelligence/decisions/publication.py)."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class DecisionOutcome(Base, UUIDPKMixin):
    __tablename__ = "decision_outcomes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_jobs.id"), nullable=True)
    state_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_states.id"), index=True)
    state_version: Mapped[int] = mapped_column(Integer)
    valuation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("valuation_snapshots.id"))
    policy_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # HOLD | REVIEW | NEEDS_INPUT
    headline: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when this outcome finished after its inputs were already superseded: kept as history, never current.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class CurrentDecision(Base):
    __tablename__ = "current_decisions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    outcome_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("decision_outcomes.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
