"""Ledger outcomes: total return (live-v2), price return and dividend flags

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-01

Additive only. No live outcome exists yet (the first is expected about 2026-11-02), so no data needs converting.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ledger_outcomes", sa.Column("fwd_price_return", sa.Numeric(), nullable=True))
    op.add_column("ledger_outcomes", sa.Column("dividend_flags", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ledger_outcomes", "dividend_flags")
    op.drop_column("ledger_outcomes", "fwd_price_return")
