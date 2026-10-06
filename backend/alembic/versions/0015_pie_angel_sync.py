"""Portfolio Intelligence Engine Phase 02: broker sync fields and typed jobs

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-30

Additive only: sync/reconciliation metadata on the Phase 01 tables and the
typed portfolio_jobs table (separate from recommendation_jobs).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_accounts", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("source_accounts", sa.Column("last_error", sa.String(), nullable=True))
    op.add_column("source_imports", sa.Column("reconciliation", sa.JSON(), nullable=True))
    op.add_column("source_imports", sa.Column("provider_summary", sa.JSON(), nullable=True))
    op.add_column("position_observations", sa.Column("source_meta", sa.JSON(), nullable=True))

    op.create_table(
        "portfolio_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("source_accounts.id"), nullable=True),
        sa.Column("request_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_token", sa.String(), nullable=True),
        sa.Column("result_import_id", sa.Uuid(), sa.ForeignKey("source_imports.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kind", "account_id", "request_key", name="uq_portfolio_jobs_request"),
    )
    op.create_index("ix_portfolio_jobs_status_created", "portfolio_jobs", ["kind", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("portfolio_jobs")
    op.drop_column("position_observations", "source_meta")
    op.drop_column("source_imports", "provider_summary")
    op.drop_column("source_imports", "reconciliation")
    op.drop_column("source_accounts", "last_error")
    op.drop_column("source_accounts", "last_sync_at")
