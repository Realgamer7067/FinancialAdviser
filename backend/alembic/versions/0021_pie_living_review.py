"""Portfolio Intelligence Engine Phase 08: events, inbox, scheduler markers, retry backoff

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("affected", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_portfolio_events_dedup"),
    )
    op.create_index("ix_portfolio_events_user_id", "portfolio_events", ["user_id"])

    op.create_table(
        "inbox_issues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("measure", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snooze_until", sa.Date(), nullable=True),
        sa.Column("dismissed_reason", sa.String(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_measure", sa.Numeric(), nullable=True),
        sa.Column("dismissed_severity", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome_id", sa.Uuid(), nullable=True),
        sa.Column("state_version_seen", sa.Integer(), nullable=True),
        sa.Column("reopen_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_inbox_user_fingerprint"),
    )
    op.create_index("ix_inbox_issues_user_id", "inbox_issues", ["user_id"])

    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.UniqueConstraint("kind", "run_date", name="uq_scheduler_kind_date"),
    )
    op.add_column("portfolio_jobs", sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolio_jobs", "not_before")
    op.drop_table("scheduler_runs")
    op.drop_table("inbox_issues")
    op.drop_table("portfolio_events")
