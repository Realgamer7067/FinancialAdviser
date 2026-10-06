"""Immutable allocation plans

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allocation_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("inputs_hash", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("state_id", sa.Uuid(), sa.ForeignKey("portfolio_states.id"), nullable=True),
        sa.Column("valuation_id", sa.Uuid(), sa.ForeignKey("valuation_snapshots.id"), nullable=True),
        sa.Column("new_money", sa.Numeric(), nullable=False),
        sa.Column("what_if_band", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("prices", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "inputs_hash", name="uq_allocation_plans_inputs"),
    )
    op.create_index("ix_allocation_plans_user_id", "allocation_plans", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_allocation_plans_user_id", table_name="allocation_plans")
    op.drop_table("allocation_plans")
