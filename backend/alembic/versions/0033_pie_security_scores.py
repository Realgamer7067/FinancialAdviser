"""Point-in-time checklist scores

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-02

Additive only. Insert-only table: a score is a dated fact, never updated, so it can be scored against what prices did afterwards.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_scores",
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("as_of_date", sa.Date(), primary_key=True),
        sa.Column("method_version", sa.String(), primary_key=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("coverage", sa.Numeric(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fundamentals_as_of", sa.Date(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index("ix_security_scores_asof", "security_scores", ["as_of_date", "method_version"])


def downgrade() -> None:
    op.drop_index("ix_security_scores_asof", table_name="security_scores")
    op.drop_table("security_scores")
