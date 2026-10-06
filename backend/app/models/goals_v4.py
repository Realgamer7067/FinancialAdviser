"""Goal, allocation-claim and commitment revision chains (Portfolio
Intelligence Engine Phase 04b). Goals and commitments are identified by a
stable `chain_id`; every edit is a new immutable revision. A GoalAllocation is
a claim of rupees on a holding identified by an ACCOUNT-SPECIFIC economic key
(not a row id), so claims survive goal edits and re-imports and are re-checked,
never silently dropped. Legacy goals/goal_earmarks/recurring_commitments are
untouched."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class GoalRevision(Base, UUIDPKMixin):
    __tablename__ = "goal_revisions"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_goal_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String)
    target_amount: Mapped[Decimal] = mapped_column(Numeric)
    target_basis: Mapped[str] = mapped_column(String)  # today_money | future_money
    target_date: Mapped[date] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer)  # lower = higher priority
    flexibility: Mapped[str] = mapped_column(String)  # fixed | flexible
    inflation_assumption: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # fraction
    status: Mapped[str] = mapped_column(String, default="active")  # active | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalAllocation(Base, UUIDPKMixin):
    """One revision of a claim. status: active | needs_review | released.
    needs_review is sticky: the system never auto-restores it, only the user."""

    __tablename__ = "goal_allocations"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_allocation_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    goal_chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    source_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("source_accounts.id"))
    holding_key: Mapped[str] = mapped_column(String, index=True)
    holding_label: Mapped[str] = mapped_column(String)  # display only
    amount: Mapped[Decimal] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommitmentRevision(Base, UUIDPKMixin):
    __tablename__ = "commitment_revisions"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_commitment_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    goal_chain_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    description: Mapped[str] = mapped_column(String)
    amount: Mapped[Decimal] = mapped_column(Numeric)
    frequency: Mapped[str] = mapped_column(String)  # monthly | quarterly | annual
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String)  # active | paused | ended
    source: Mapped[str] = mapped_column(String)  # existing_user_reported | proposed
    budget_interpretation: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
