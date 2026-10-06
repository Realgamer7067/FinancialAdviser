"""Source accounts and immutable per-account imports (Portfolio Intelligence
Engine Phase 01, docs/PORTFOLIO-INTELLIGENCE-ENGINE-PLAN.md sections 4, 12.3).

Every holding source (manual entry, CSV, later Angel One) is a named
SourceAccount. A confirmed import is an immutable SourceImport with
PositionObservation rows; the account's current holdings are its latest
import, so re-importing account A never touches account B. Legacy
HoldingsSnapshot tables are left as-is and only adopted on explicit request.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class SourceAccount(Base, UUIDPKMixin):
    __tablename__ = "source_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "label", name="uq_source_accounts_user_label"),
        UniqueConstraint(
            "user_id", "source_type", "external_fingerprint", name="uq_source_accounts_fingerprint"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String)  # "manual" | "csv" | "angel_one"
    label: Mapped[str] = mapped_column(String)
    masked_external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)  # keyed HMAC, broker accounts only
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountCoverageAttestation(Base, UUIDPKMixin):
    """Append-only user declaration of whether all their accounts are
    represented. A broker sync can never change it."""

    __tablename__ = "account_coverage_attestations"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_coverage_user_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # "complete" | "partial" | "unknown"
    missing_account_types: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceImport(Base, UUIDPKMixin):
    """Immutable. Only complete, confirmed imports are stored (previews are
    stateless), so the account's latest row is its current holdings."""

    __tablename__ = "source_imports"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_source_imports_account_key"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_accounts.id"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="complete")
    row_count: Mapped[int] = mapped_column(Integer)
    # Set when the import was adopted from a legacy HoldingsSnapshot; unique so
    # a legacy snapshot can be adopted at most once.
    legacy_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("holdings_snapshots.id"), nullable=True, unique=True
    )
    # Broker imports: {"computed_value","provider_total","abs_diff","rel_diff"...}
    reconciliation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PositionObservation(Base, UUIDPKMixin):
    __tablename__ = "position_observations"
    __table_args__ = (UniqueConstraint("import_id", "row_ordinal", name="uq_position_obs_import_row"),)

    import_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_imports.id"), index=True
    )
    row_ordinal: Mapped[int] = mapped_column(Integer)
    asset_type: Mapped[str] = mapped_column(String)
    raw_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True
    )
    # "resolved" | "ambiguous" | "unresolved" | "not_applicable"
    resolution: Mapped[str] = mapped_column(String)
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # null = unknown, never 0
    valuation_date: Mapped[date] = mapped_column(Date)
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # only if given
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    ownership: Mapped[str] = mapped_column(String, default="sole")
    # Provider-reported fields kept verbatim (exchange, token, T1, avg price, LTP...).
    source_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
