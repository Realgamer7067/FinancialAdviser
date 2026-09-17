"""add lease_expires_at and worker_token to recommendation_jobs

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14

docs/V2-RETHINK.md P0: job claiming was a SELECT followed by UPDATE with no
locking and no lease recovery -- two worker processes could grab the same
job, and a job whose worker crashed mid-run stayed "running" forever. Fixed
with an atomic `SELECT ... FOR UPDATE SKIP LOCKED` claim plus a lease
(renewed by progress heartbeats) and a fencing token so a recovered stale
attempt can never overwrite a newer attempt's result (app/worker.py,
app/pipelines/progress.py).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recommendation_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recommendation_jobs", sa.Column("worker_token", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommendation_jobs", "worker_token")
    op.drop_column("recommendation_jobs", "lease_expires_at")
