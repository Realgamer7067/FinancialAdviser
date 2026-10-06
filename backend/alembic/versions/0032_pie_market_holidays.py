"""NSE trading holidays

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_holidays",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_holidays")
