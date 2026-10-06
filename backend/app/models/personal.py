"""User-confirmed personal facts (Portfolio Intelligence Engine Phase 04a).
Every edit is a NEW immutable revision; nothing is inferred from holdings or
broker balances. Missing answers stay null/unknown."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class FinancialProfileRevision(Base, UUIDPKMixin):
    __tablename__ = "financial_profile_revisions"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_profile_user_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    facts: Mapped[dict] = mapped_column(JSON)  # validated FinancialFacts; nulls = unknown
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LiabilityRevision(Base, UUIDPKMixin):
    """Dated, POSITIVE outstanding balance; separate from assets. `chain_id` is
    the stable identity of one liability across its revisions."""

    __tablename__ = "liability_revisions"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_liability_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric)
    as_of: Mapped[date] = mapped_column(Date)
    monthly_payment: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    rate_type: Mapped[str] = mapped_column(String)  # fixed | floating | unknown
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # fraction, 0.09 = 9%
    next_reset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PreferenceRevision(Base, UUIDPKMixin):
    """Explicit, confirmed restriction (never inferred from chat)."""

    __tablename__ = "preference_revisions"
    __table_args__ = (UniqueConstraint("chain_id", "version", name="uq_preference_chain_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    chain_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)  # exclude_sector | exclude_asset_type | exclude_isin
    value: Mapped[str] = mapped_column(String)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | revoked
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
