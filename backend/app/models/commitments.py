"""Recurring contribution instructions (V3 Phase 03, docs/V3-IMPLEMENTATION-PLAN.md
section 5.3/10.1, "Contribution instruction" row)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class RecurringCommitment(Base, UUIDPKMixin):
    __tablename__ = "recurring_commitments"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True
    )
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric)
    frequency: Mapped[str] = mapped_column(String)  # "monthly" | "quarterly" | "annual"
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contribution_timing: Mapped[str] = mapped_column(String)  # "start_of_period" | "end_of_period"
    step_up_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String)  # "active" | "paused" | "ended"
    goal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("goals.id"), nullable=True)
    source: Mapped[str] = mapped_column(String)  # "existing_user_reported" | "proposed"
    # V3 section 7.1: MUST be explicit, never assumed/defaulted -- see
    # api/financial_inputs.py's create-commitment validation, which rejects a
    # missing value with 422 rather than silently defaulting it.
    budget_interpretation: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
