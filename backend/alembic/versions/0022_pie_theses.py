"""Portfolio Intelligence Engine Phase 09: theses, assessments, thesis events, persisted research verification

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("research_sessions", sa.Column("verification", sa.JSON(), nullable=True))
    op.add_column("research_sessions", sa.Column("contradictions", sa.JSON(), nullable=True))

    op.create_table(
        "theses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("ownership", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("horizon_date", sa.Date(), nullable=True),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "version", name="uq_thesis_chain_version"),
    )
    op.create_index("ix_theses_user_id", "theses", ["user_id"])
    op.create_index("ix_theses_chain_id", "theses", ["chain_id"])

    op.create_table(
        "thesis_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thesis_chain_id", sa.Uuid(), nullable=False),
        sa.Column("thesis_version", sa.Integer(), nullable=False),
        sa.Column("research_session_id", sa.Uuid(), sa.ForeignKey("research_sessions.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("prior_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("change_log", sa.String(), nullable=False),
        sa.Column("per_condition", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("contradictions", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("model_info", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("review_status", sa.String(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_thesis_assessments_user_id", "thesis_assessments", ["user_id"])
    op.create_index("ix_thesis_assessments_chain", "thesis_assessments", ["thesis_chain_id"])

    op.create_table(
        "thesis_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thesis_chain_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("observed", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_thesis_events_dedup"),
    )
    op.create_index("ix_thesis_events_user_id", "thesis_events", ["user_id"])
    op.create_index("ix_thesis_events_chain", "thesis_events", ["thesis_chain_id"])


def downgrade() -> None:
    op.drop_table("thesis_events")
    op.drop_table("thesis_assessments")
    op.drop_table("theses")
    op.drop_column("research_sessions", "contradictions")
    op.drop_column("research_sessions", "verification")
