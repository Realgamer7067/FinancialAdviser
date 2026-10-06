"""Point-in-time security signals and model forecasts

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NUM = ("sma200_ratio", "mom_12_1", "mom_6_1", "mom_12_1_rank", "vol_60", "vol_252", "vol_252_rank", "vol_ratio", "drawdown_current",
        "max_dd_1y", "week52_pos", "liquidity_value")


def upgrade() -> None:
    cols = [
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("as_of_date", sa.Date(), primary_key=True),
        sa.Column("method_version", sa.String(), primary_key=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history_len", sa.Integer(), nullable=False),
        sa.Column("input_marker", sa.String(), nullable=False),
        sa.Column("quality", sa.String(), nullable=False),
        sa.Column("universe", sa.String(), nullable=False),
        sa.Column("rank_universe_size", sa.Integer(), nullable=True),
        sa.Column("trend_state", sa.String(), nullable=True),
        sa.Column("circuit_days_20", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
    ] + [sa.Column(n, sa.Numeric(), nullable=True) for n in _NUM]
    op.create_table("security_signals", *cols)
    op.create_index("ix_security_signals_security_asof", "security_signals", ["security_id", "as_of_date"])
    op.create_table(
        "security_forecasts",
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("as_of_date", sa.Date(), primary_key=True),
        sa.Column("model_version", sa.String(), primary_key=True),
        sa.Column("horizon", sa.String(), primary_key=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_marker", sa.String(), nullable=False),
        sa.Column("bars_used", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("predicted_return", sa.Numeric(), nullable=False),
        sa.Column("p10", sa.Numeric(), nullable=False),
        sa.Column("p90", sa.Numeric(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("direction_agreement", sa.Numeric(), nullable=False),
        sa.Column("calibrated_confidence", sa.Numeric(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("security_forecasts")
    op.drop_index("ix_security_signals_security_asof", table_name="security_signals")
    op.drop_table("security_signals")
