"""Security candles, candle sync bookkeeping, job params

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_candles",
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "candle_syncs",
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("full_refetches", sa.Integer(), nullable=False),
    )
    op.add_column("portfolio_jobs", sa.Column("params", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_jobs", "params")
    op.drop_table("candle_syncs")
    op.drop_table("security_candles")
