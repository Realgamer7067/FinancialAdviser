"""Typed, immutable holdings snapshots (V3 Phase 03, docs/V3-IMPLEMENTATION-PLAN.md
section 5.2 / 10.1-10.2). A new import or edit creates a NEW HoldingsSnapshot --
existing snapshots and their HoldingPosition rows are never mutated in place,
matching the append-only/soft-supersession convention already established by
MarketCandle (app/models/market.py, V3 Phase 02)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class HoldingsSnapshot(Base, UUIDPKMixin):
    """Immutable, append-only -- a new import/edit creates a NEW snapshot,
    never mutates an old one (V3 section 10.2: 'Published records are
    append-only. Corrections create revisions linked to the prior version.')

    There is no `superseded_at` here: unlike Goal (which is explicitly
    versioned/edited via PUT), a holdings snapshot is simply superseded by
    whichever later snapshot exists for the same user -- "latest" is read via
    ORDER BY created_at DESC LIMIT 1 (see api/financial_inputs.py::latest_holdings),
    same idea as MarketCandle's import_batch_id grouping but without a
    superseded_at flag, since old snapshots are never replaced-in-place, only
    superseded by recency.
    """

    __tablename__ = "holdings_snapshots"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String)  # "manual" | "csv_import"
    import_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HoldingPosition(Base, UUIDPKMixin):
    __tablename__ = "holding_positions"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("holdings_snapshots.id"), index=True
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True
    )
    raw_identifier_text: Mapped[str | None] = mapped_column(String, nullable=True)
    account_label: Mapped[str | None] = mapped_column(String, nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric)
    valuation_date: Mapped[date] = mapped_column(Date)
    valuation_source: Mapped[str] = mapped_column(String)
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    ownership: Mapped[str] = mapped_column(String)
    include_in_planning: Mapped[bool] = mapped_column(Boolean, default=True)
    identification_confidence: Mapped[str] = mapped_column(String)
