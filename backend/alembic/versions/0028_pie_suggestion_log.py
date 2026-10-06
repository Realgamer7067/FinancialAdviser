"""Suggestion log (immutable observation records)

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suggestion_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("context", sa.String(), nullable=False),
        sa.Column("trigger_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("method_version", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("signal_input_marker", sa.String(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "fingerprint", "trigger_date", name="uq_suggestion_log_trigger"),
    )
    op.create_index("ix_suggestion_log_user_id", "suggestion_log", ["user_id"])
    op.create_index("ix_suggestion_log_security_id", "suggestion_log", ["security_id"])


def downgrade() -> None:
    op.drop_index("ix_suggestion_log_security_id", table_name="suggestion_log")
    op.drop_index("ix_suggestion_log_user_id", table_name="suggestion_log")
    op.drop_table("suggestion_log")
