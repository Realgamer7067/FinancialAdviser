import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class DataManifestEntry(Base, UUIDPKMixin):
    """Immutable record of which exact data versions fed one instrument's
    evidence within one council run (docs/v3-execution/CONTRACTS.md C3/C1,
    V3 Phase 02: 'introduce immutable manifest entries that reference exact
    data/feature versions; bind report reads to those entries'). Never
    updated after creation -- a new council run gets new entries, this
    table is append-only.

    Identity is by NATURAL fields (source/as_of/generated_at/etc), not by
    foreign-keying to the exact MarketCandle/FundamentalMetrics/etc row --
    those ids aren't available at the point evidence is assembled in the
    pipeline without invasive threading changes (out of scope for this
    module). `entry is None` for a given (council_run_id, instrument_id)
    means the run predates the manifest system -- an old/legacy report with
    no recorded provenance. Callers must treat that as "unversioned, display
    without a manifest-backed freshness claim," never invent a fake entry
    for it after the fact.
    """

    __tablename__ = "data_manifest_entries"
    __table_args__ = (
        # At most one manifest entry per instrument per run -- the pipeline
        # calls record_manifest_entry exactly once per candidate per run
        # (_evaluate_candidate), so this is a real invariant, not just
        # defense-in-depth. Also makes get_manifest_entry's scalar_one_or_none()
        # safe (a second call for the same pair would fail loudly, not
        # silently create an ambiguous duplicate).
        UniqueConstraint("council_run_id", "instrument_id", name="uq_data_manifest_entry_run_instrument"),
    )

    council_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("council_runs.id"), index=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"), index=True)

    candle_source: Mapped[str | None] = mapped_column(String, nullable=True)
    candle_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fundamentals_source: Mapped[str | None] = mapped_column(String, nullable=True)
    fundamentals_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fundamentals_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    technicals_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    kronos_model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    kronos_forecast_horizon: Mapped[str | None] = mapped_column(String, nullable=True)
    kronos_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
