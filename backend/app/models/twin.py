"""Portfolio Twin (Portfolio Intelligence Engine Phase 03, plan sections 4,
12.2). A PortfolioState is an immutable, versioned answer to "what did the
system know about holdings and user-bound facts at this time"; it references
immutable position observations. A ValuationSnapshot is a separate immutable
pricing of that state. Quote/price refreshes create valuations, never states."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class PortfolioState(Base, UUIDPKMixin):
    __tablename__ = "portfolio_states"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_portfolio_states_user_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)  # monotonic per user
    economic_hash: Mapped[str] = mapped_column(String)
    normalization_version: Mapped[str] = mapped_column(String)
    coverage_attestation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("account_coverage_attestations.id"), nullable=True
    )
    # Bound user-fact revisions (Phase 04a); null/empty = none supplied at build time.
    profile_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("financial_profile_revisions.id"), nullable=True
    )
    liability_revision_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    preference_revision_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    goal_revision_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allocation_revision_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    commitment_revision_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{account_id, label, source_type, import_id|null, status, position_count}]
    # frozen at build time, including accounts that had no import.
    account_inputs: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortfolioPosition(Base, UUIDPKMixin):
    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("state_id", "observation_id", name="uq_portfolio_positions_state_obs"),)

    state_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_states.id"), index=True)
    observation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("position_observations.id"))
    source_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("source_accounts.id"))
    import_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("source_imports.id"))


class ValuationSnapshot(Base, UUIDPKMixin):
    __tablename__ = "valuation_snapshots"
    __table_args__ = (
        UniqueConstraint("state_id", "observation_set_hash", "price_policy_version", name="uq_valuation_identity"),
    )

    state_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_states.id"), index=True)
    observation_set_hash: Mapped[str] = mapped_column(String)
    price_policy_version: Mapped[str] = mapped_column(String)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    known_total: Mapped[Decimal] = mapped_column(Numeric)
    unknown_value_count: Mapped[int] = mapped_column(Integer)
    # {identity_resolved_share, fresh_share, earliest_as_of, latest_as_of, ...}
    coverage: Mapped[dict] = mapped_column(JSON)
    # [{observation_id, value|null, source, as_of, retrieved_at, quality}]
    selections: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
