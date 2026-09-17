"""add unallocated_cash to portfolio_results

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14

docs/V2-RETHINK.md P0 finding: the equal-weight/single-symbol/FinRL fallback
paths could allocate more than the configured concentration cap by silently
renormalizing capped weights back up to sum to 1. Fixed at the source
(app/models_iface/portfolio_mvo.py, portfolio_finrl.py) by never renormalizing
past the cap and instead reporting the shortfall as unallocated_cash. Existing
rows predate the fix and get a conservative default of 0.0 (their persisted
allocations may in fact have been over-cap; this column only guarantees
future rows are correct, it does not retroactively correct old ones).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolio_results", sa.Column("unallocated_cash", sa.Float(), nullable=False, server_default="0.0")
    )
    op.alter_column("portfolio_results", "unallocated_cash", server_default=None)


def downgrade() -> None:
    op.drop_column("portfolio_results", "unallocated_cash")
