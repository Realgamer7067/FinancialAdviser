"""V3 Phase 02: candle history preservation, adjustment metadata, data manifest

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-14

docs/v3-execution/phase-02.md. Three changes, combined into one migration
since they landed together from three parallel Phase 02 workers:

1. market_candles gains import_batch_id/superseded_at -- a refresh now
   soft-supersedes overlapping rows instead of hard-deleting them, so a
   published report's evidence can still be traced back to the exact candle
   set it was computed from. The old plain UniqueConstraint on
   (instrument_id, interval, timestamp, source) is replaced with a PARTIAL
   unique index that only applies to non-superseded rows -- a superseded row
   and its replacement are allowed to share the same natural key.
2. market_candles gains `adjusted` (split/dividend-adjustment status),
   previously unrecorded. Backfilled TRUE for existing rows (fetched via
   yfinance, whose default is adjusted closes).
3. New data_manifest_entries table: one row per (council_run, instrument),
   recording the natural-identity fields (source/as_of/generated_at) of the
   fundamentals/technicals/kronos/candle data that fed that instrument's
   evidence in that run. Existing council runs get NO manifest rows --
   `get_manifest_entry` returning None is the documented "legacy/unversioned
   report" signal, not backfilled retroactively (V3 Phase 02: "Legacy
   reports with incomplete provenance stay explicitly legacy/unversioned").
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. market_candles: soft-supersession -----------------------------
    op.add_column("market_candles", sa.Column("import_batch_id", sa.Uuid(), nullable=True))
    op.add_column("market_candles", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("uq_market_candles_natural_key", "market_candles", type_="unique")
    op.create_index(
        "uq_market_candles_natural_key_current",
        "market_candles",
        ["instrument_id", "interval", "timestamp", "source"],
        unique=True,
        sqlite_where=sa.text("superseded_at IS NULL"),
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # --- 2. market_candles: adjustment metadata ----------------------------
    op.add_column(
        "market_candles", sa.Column("adjusted", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.alter_column("market_candles", "adjusted", server_default=None)

    # --- 3. data_manifest_entries -------------------------------------------
    op.create_table(
        "data_manifest_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("council_run_id", sa.Uuid(), sa.ForeignKey("council_runs.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("candle_source", sa.String(), nullable=True),
        sa.Column("candle_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fundamentals_source", sa.String(), nullable=True),
        sa.Column("fundamentals_as_of_date", sa.Date(), nullable=True),
        sa.Column("fundamentals_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("technicals_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kronos_model_version", sa.String(), nullable=True),
        sa.Column("kronos_forecast_horizon", sa.String(), nullable=True),
        sa.Column("kronos_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("council_run_id", "instrument_id", name="uq_data_manifest_entry_run_instrument"),
    )
    op.create_index("ix_data_manifest_entries_council_run_id", "data_manifest_entries", ["council_run_id"])
    op.create_index("ix_data_manifest_entries_instrument_id", "data_manifest_entries", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_data_manifest_entries_instrument_id", table_name="data_manifest_entries")
    op.drop_index("ix_data_manifest_entries_council_run_id", table_name="data_manifest_entries")
    op.drop_table("data_manifest_entries")

    op.drop_column("market_candles", "adjusted")

    op.drop_index("uq_market_candles_natural_key_current", table_name="market_candles")
    op.create_unique_constraint(
        "uq_market_candles_natural_key", "market_candles", ["instrument_id", "interval", "timestamp", "source"]
    )
    op.drop_column("market_candles", "superseded_at")
    op.drop_column("market_candles", "import_batch_id")
