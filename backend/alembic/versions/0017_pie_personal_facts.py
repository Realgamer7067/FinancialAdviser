"""Portfolio Intelligence Engine Phase 04a: profile, liabilities, preferences

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-30

Additive only. Revision tables plus nullable binding columns on portfolio_states.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_profile_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_profile_user_version"),
    )
    op.create_index("ix_financial_profile_revisions_user_id", "financial_profile_revisions", ["user_id"])

    op.create_table(
        "liability_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("outstanding_amount", sa.Numeric(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(), nullable=True),
        sa.Column("rate_type", sa.String(), nullable=False),
        sa.Column("annual_rate", sa.Numeric(), nullable=True),
        sa.Column("next_reset_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_liability_chain_version"),
    )
    op.create_index("ix_liability_revisions_user_id", "liability_revisions", ["user_id"])
    op.create_index("ix_liability_revisions_chain_id", "liability_revisions", ["chain_id"])

    op.create_table(
        "preference_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_preference_chain_version"),
    )
    op.create_index("ix_preference_revisions_user_id", "preference_revisions", ["user_id"])
    op.create_index("ix_preference_revisions_chain_id", "preference_revisions", ["chain_id"])

    op.add_column("portfolio_states", sa.Column("profile_revision_id", sa.Uuid(), sa.ForeignKey("financial_profile_revisions.id"), nullable=True))
    op.add_column("portfolio_states", sa.Column("liability_revision_ids", sa.JSON(), nullable=True))
    op.add_column("portfolio_states", sa.Column("preference_revision_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_states", "preference_revision_ids")
    op.drop_column("portfolio_states", "liability_revision_ids")
    op.drop_column("portfolio_states", "profile_revision_id")
    op.drop_table("preference_revisions")
    op.drop_table("liability_revisions")
    op.drop_table("financial_profile_revisions")
