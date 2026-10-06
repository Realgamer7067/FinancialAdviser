"""Portfolio Intelligence Engine Phase 05: saved risk/scenario analyses

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-01

Additive only: analysis_runs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state_id", sa.Uuid(), sa.ForeignKey("portfolio_states.id"), nullable=False),
        sa.Column("valuation_id", sa.Uuid(), sa.ForeignKey("valuation_snapshots.id"), nullable=False),
        sa.Column("method_version", sa.String(), nullable=False),
        sa.Column("inputs_hash", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "state_id", "valuation_id", "method_version", "inputs_hash", name="uq_analysis_identity"),
    )
    op.create_index("ix_analysis_runs_user_id", "analysis_runs", ["user_id"])
    op.create_index("ix_analysis_runs_state_id", "analysis_runs", ["state_id"])


def downgrade() -> None:
    op.drop_table("analysis_runs")
