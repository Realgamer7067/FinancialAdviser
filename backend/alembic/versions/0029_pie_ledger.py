"""Scoring ledger: studies, outcomes, plan origin

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-01

Additive, plus one data step: every allocation plan that exists at this revision was produced by verification runs
(curl/UI checks during development), not by the owner acting on it, so they are marked origin='verification' and are
never scored. New plans are 'owner' (or 'what_if' when a what-if band was used).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("allocation_plans", sa.Column("origin", sa.String(), nullable=False, server_default="owner"))
    op.execute("UPDATE allocation_plans SET origin = 'verification'")
    op.alter_column("allocation_plans", "origin", server_default=None)
    op.create_table(
        "ledger_studies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_version", sa.String(), nullable=False),
        sa.Column("registry_hash", sa.String(), nullable=False),
        sa.Column("data_marker", sa.String(), nullable=False),
        sa.Column("evidence", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("study_version", "data_marker", name="uq_ledger_studies_version_data"),
    )
    op.create_table(
        "ledger_outcomes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_sessions", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Numeric(), nullable=True),
        sa.Column("exit_price", sa.Numeric(), nullable=True),
        sa.Column("fwd_return", sa.Numeric(), nullable=True),
        sa.Column("fwd_vol", sa.Numeric(), nullable=True),
        sa.Column("universe_return", sa.Numeric(), nullable=True),
        sa.Column("etf_return", sa.Numeric(), nullable=True),
        sa.Column("feature", sa.Numeric(), nullable=True),
        sa.Column("direction", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("input_marker", sa.String(), nullable=True),
        sa.Column("full_refetches", sa.Integer(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("claim_id", "subject_key", "horizon_sessions", "version", name="uq_ledger_outcome"),
    )
    op.create_index("ix_ledger_outcomes_claim_id", "ledger_outcomes", ["claim_id"])
    op.create_index("ix_ledger_outcomes_security_id", "ledger_outcomes", ["security_id"])
    op.create_index("ix_ledger_outcomes_as_of_date", "ledger_outcomes", ["as_of_date"])


def downgrade() -> None:
    op.drop_table("ledger_outcomes")
    op.drop_table("ledger_studies")
    op.drop_column("allocation_plans", "origin")
