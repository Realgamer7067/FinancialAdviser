"""Goals with earmarking (V3 Phase 03, docs/V3-IMPLEMENTATION-PLAN.md section
5.3 / 10.1-10.2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Date, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Goal(Base, UUIDPKMixin):
    """Soft-supersession, same pattern as MarketCandle (app/models/market.py,
    V3 Phase 02): an edit does not mutate the row -- it inserts a new Goal row
    with `version = old.version + 1` and stamps `superseded_at` on the old
    row. `priority`: lower integer = higher priority (1 is the highest
    priority goal)."""

    __tablename__ = "goals"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(String)
    target_amount: Mapped[Decimal] = mapped_column(Numeric)
    target_basis: Mapped[str] = mapped_column(String)  # "today_money" | "future_money"
    target_date: Mapped[date] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer)  # lower = higher priority
    flexibility: Mapped[str] = mapped_column(String)  # "fixed" | "flexible"
    inflation_assumption: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    inflation_assumption_version: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalEarmark(Base, UUIDPKMixin):
    """Claims a specific rupee amount of a specific holding/reserve toward
    one goal. INVARIANT (V3 section 5.3, hard requirement): 'Earmarking
    cannot allocate the same rupee to several goals. The sum of goal claims
    on each holding/reserve must not exceed its available amount.' Enforced
    in app/api/financial_inputs.py at write time via a real summing query,
    not a denormalized running total on this table."""

    __tablename__ = "goal_earmarks"

    goal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("goals.id"), index=True)
    holding_position_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("holding_positions.id"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
