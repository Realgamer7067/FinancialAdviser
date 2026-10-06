"""Portfolio Intelligence Engine Phase 03: Portfolio Twin state and valuation

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-30

Additive only: portfolio_states, portfolio_positions, valuation_snapshots.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("economic_hash", sa.String(), nullable=False),
        sa.Column("normalization_version", sa.String(), nullable=False),
        sa.Column("coverage_attestation_id", sa.Uuid(), sa.ForeignKey("account_coverage_attestations.id"), nullable=True),
        sa.Column("account_inputs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_portfolio_states_user_version"),
    )
    op.create_index("ix_portfolio_states_user_id", "portfolio_states", ["user_id"])

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_id", sa.Uuid(), sa.ForeignKey("portfolio_states.id"), nullable=False),
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("position_observations.id"), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), sa.ForeignKey("source_accounts.id"), nullable=False),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey("source_imports.id"), nullable=False),
        sa.UniqueConstraint("state_id", "observation_id", name="uq_portfolio_positions_state_obs"),
    )
    op.create_index("ix_portfolio_positions_state_id", "portfolio_positions", ["state_id"])

    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_id", sa.Uuid(), sa.ForeignKey("portfolio_states.id"), nullable=False),
        sa.Column("observation_set_hash", sa.String(), nullable=False),
        sa.Column("price_policy_version", sa.String(), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_total", sa.Numeric(), nullable=False),
        sa.Column("unknown_value_count", sa.Integer(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("state_id", "observation_set_hash", "price_policy_version", name="uq_valuation_identity"),
    )
    op.create_index("ix_valuation_snapshots_state_id", "valuation_snapshots", ["state_id"])


def downgrade() -> None:
    op.drop_table("valuation_snapshots")
    op.drop_table("portfolio_positions")
    op.drop_table("portfolio_states")
