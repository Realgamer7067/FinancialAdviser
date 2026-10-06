"""Portfolio Intelligence Engine Phase 07: published decisions

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-01

Additive only: decision_outcomes, current_decisions, portfolio_jobs.result_outcome_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("portfolio_jobs.id"), nullable=True),
        sa.Column("state_id", sa.Uuid(), sa.ForeignKey("portfolio_states.id"), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("valuation_id", sa.Uuid(), sa.ForeignKey("valuation_snapshots.id"), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("headline", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_decision_outcomes_user_id", "decision_outcomes", ["user_id"])
    op.create_index("ix_decision_outcomes_state_id", "decision_outcomes", ["state_id"])
    op.create_table(
        "current_decisions",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("outcome_id", sa.Uuid(), sa.ForeignKey("decision_outcomes.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("portfolio_jobs", sa.Column("result_outcome_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_jobs", "result_outcome_id")
    op.drop_table("current_decisions")
    op.drop_table("decision_outcomes")
