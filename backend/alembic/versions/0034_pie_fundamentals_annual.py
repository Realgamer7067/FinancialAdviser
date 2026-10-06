"""Annual statement figures and an NSE cross-check on fundamental_metrics

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-02

Additive only: nullable columns, so every existing row stays valid (a missing figure stays UNKNOWN, never zero).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FLOATS = ["total_assets", "total_assets_prior", "annual_net_income", "annual_operating_cash_flow", "annual_capex", "annual_free_cash_flow", "nse_eps_ttm"]


def upgrade() -> None:
    for c in FLOATS:
        op.add_column("fundamental_metrics", sa.Column(c, sa.Float(), nullable=True))
    op.add_column("fundamental_metrics", sa.Column("annual_period_end", sa.Date(), nullable=True))
    op.add_column("fundamental_metrics", sa.Column("nse_period_end", sa.Date(), nullable=True))
    op.add_column("fundamental_metrics", sa.Column("nse_quarters", sa.Integer(), nullable=True))


def downgrade() -> None:
    for c in ["nse_quarters", "nse_period_end", "annual_period_end", *FLOATS]:
        op.drop_column("fundamental_metrics", c)
