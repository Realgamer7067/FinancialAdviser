"""V3 Phase 07 research workflow tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-14

docs/v3-execution/phase-07.md. Three new tables, ordered for their FK
dependencies: research_sessions and research_branches first (research_branches
depends on research_sessions; research_sessions self-references for
parent_session_id), then research_reports (depends on research_sessions via
session_id, self-references for parent_report_id).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("instrument_ids", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("cutoff_policy", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("parent_session_id", sa.Uuid(), sa.ForeignKey("research_sessions.id"), nullable=True),
        sa.Column("budget_envelope", sa.JSON(), nullable=False),
        sa.Column("budget_consumed", sa.JSON(), nullable=False),
        sa.Column("named_gaps", sa.JSON(), nullable=False),
        sa.Column("budget_exhausted_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "research_branches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("research_sessions.id"), nullable=False),
        sa.Column("branch_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fact_ids", sa.JSON(), nullable=False),
        sa.Column("gap_reason", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_branches_session_id", "research_branches", ["session_id"])

    op.create_table(
        "research_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("research_sessions.id"), nullable=False),
        sa.Column("parent_report_id", sa.Uuid(), sa.ForeignKey("research_reports.id"), nullable=True),
        sa.Column("revision_kind", sa.String(), nullable=True),
        sa.Column("artifact_key", sa.String(), nullable=False),
        sa.Column("manifest_snapshot", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("changed_source_ids", sa.JSON(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_reports_session_id", "research_reports", ["session_id"])
    op.create_index("ix_research_reports_artifact_key", "research_reports", ["artifact_key"])


def downgrade() -> None:
    op.drop_index("ix_research_reports_artifact_key", table_name="research_reports")
    op.drop_index("ix_research_reports_session_id", table_name="research_reports")
    op.drop_table("research_reports")

    op.drop_index("ix_research_branches_session_id", table_name="research_branches")
    op.drop_table("research_branches")

    op.drop_table("research_sessions")
