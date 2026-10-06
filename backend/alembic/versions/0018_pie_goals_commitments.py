"""Portfolio Intelligence Engine Phase 04b: goal/allocation/commitment revisions

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-01

Additive only. Legacy goals, goal_earmarks and recurring_commitments untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uid():
    return sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "goal_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True), _uid(),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("target_amount", sa.Numeric(), nullable=False),
        sa.Column("target_basis", sa.String(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("flexibility", sa.String(), nullable=False),
        sa.Column("inflation_assumption", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_goal_chain_version"),
    )
    op.create_index("ix_goal_revisions_user_id", "goal_revisions", ["user_id"])
    op.create_index("ix_goal_revisions_chain_id", "goal_revisions", ["chain_id"])

    op.create_table(
        "goal_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True), _uid(),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("goal_chain_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), sa.ForeignKey("source_accounts.id"), nullable=False),
        sa.Column("holding_key", sa.String(), nullable=False),
        sa.Column("holding_label", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_allocation_chain_version"),
    )
    op.create_index("ix_goal_allocations_user_id", "goal_allocations", ["user_id"])
    op.create_index("ix_goal_allocations_chain_id", "goal_allocations", ["chain_id"])
    op.create_index("ix_goal_allocations_goal_chain_id", "goal_allocations", ["goal_chain_id"])
    op.create_index("ix_goal_allocations_holding_key", "goal_allocations", ["holding_key"])

    op.create_table(
        "commitment_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True), _uid(),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("goal_chain_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("budget_interpretation", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_commitment_chain_version"),
    )
    op.create_index("ix_commitment_revisions_user_id", "commitment_revisions", ["user_id"])
    op.create_index("ix_commitment_revisions_chain_id", "commitment_revisions", ["chain_id"])

    op.add_column("portfolio_states", sa.Column("goal_revision_ids", sa.JSON(), nullable=True))
    op.add_column("portfolio_states", sa.Column("allocation_revision_ids", sa.JSON(), nullable=True))
    op.add_column("portfolio_states", sa.Column("commitment_revision_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_states", "commitment_revision_ids")
    op.drop_column("portfolio_states", "allocation_revision_ids")
    op.drop_column("portfolio_states", "goal_revision_ids")
    op.drop_table("commitment_revisions")
    op.drop_table("goal_allocations")
    op.drop_table("goal_revisions")
