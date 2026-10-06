"""add insider_holding_pct, stop conflating it with promoter_holding

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-14

docs/V2-RETHINK.md P1: yfinance's `heldPercentInsiders` was being written
straight into `promoter_holding` -- generic global "insider ownership" and
NSE's regulated "promoter holding %" disclosure are different metrics from
different disclosure regimes. app/providers/fundamentals.py now stores the
yfinance figure under its own honestly-named column and leaves
promoter_holding NULL until a real NSE shareholding-pattern source is wired
in. Existing rows' promoter_holding values came from the same mislabeled
mapping -- move them to insider_holding_pct (what they actually are) and null
out promoter_holding rather than leave a column that looks authoritative but
isn't.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fundamental_metrics", sa.Column("insider_holding_pct", sa.Float(), nullable=True))
    # demo_seed rows are synthetic test data, not a real mislabeled fetch --
    # only real yfinance-sourced rows carry the actual bug being repaired.
    op.execute(
        "UPDATE fundamental_metrics SET insider_holding_pct = promoter_holding "
        "WHERE source = 'yfinance_nifty50_seed'"
    )
    op.execute("UPDATE fundamental_metrics SET promoter_holding = NULL WHERE source = 'yfinance_nifty50_seed'")


def downgrade() -> None:
    op.execute(
        "UPDATE fundamental_metrics SET promoter_holding = insider_holding_pct "
        "WHERE promoter_holding IS NULL AND source = 'yfinance_nifty50_seed'"
    )
    op.drop_column("fundamental_metrics", "insider_holding_pct")
