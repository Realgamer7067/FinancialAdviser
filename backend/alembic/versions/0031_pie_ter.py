"""AMFI expense ratios and their defensible matches

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheme_ter",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nsdl_code", sa.String(), nullable=False),
        sa.Column("mf_id", sa.Integer(), nullable=False),
        sa.Column("amc_name", sa.String(), nullable=False),
        sa.Column("scheme_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("ter_date", sa.Date(), nullable=False),
        sa.Column("regular_ter", sa.Numeric(), nullable=True),
        sa.Column("direct_ter", sa.Numeric(), nullable=True),
        sa.Column("regular_ber", sa.Numeric(), nullable=True),
        sa.Column("direct_ber", sa.Numeric(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("nsdl_code", name="uq_scheme_ter_code"),
    )
    op.create_index("ix_scheme_ter_mf_id", "scheme_ter", ["mf_id"])
    op.create_table(
        "security_ter",
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("nsdl_code", sa.String(), nullable=False),
        sa.Column("scheme_name", sa.String(), nullable=False),
        sa.Column("ter", sa.Numeric(), nullable=False),
        sa.Column("plan_used", sa.String(), nullable=False),
        sa.Column("matched_via", sa.String(), nullable=False),
        sa.Column("ter_date", sa.Date(), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("security_ter")
    op.drop_index("ix_scheme_ter_mf_id", table_name="scheme_ter")
    op.drop_table("scheme_ter")
