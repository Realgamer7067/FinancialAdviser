"""add kronos_predictions sample-distribution fields, make confidence nullable

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14

Kronos now draws multiple independent samples per forecast instead of one
(docs/V2-RETHINK.md section 2a) and derives predicted_return/direction from
that distribution instead of a single collapsed point. confidence becomes
nullable: it is only populated once a calibration table exists for the
forecast's (model_version, horizon, direction_agreement bucket) -- previously
it was a hardcoded 0.5 constant, never actually unknown. New columns are
NOT NULL with no default for predicted_return_p10/p90/direction_agreement/
sample_count since every row from this point forward is produced by the new
KronosModel, which always populates them; existing rows predate this
migration and are backfilled with a sentinel that also flags them as
pre-migration (agreement=1.0, sample_count=1, p10=p90=predicted_return).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("kronos_predictions", sa.Column("predicted_return_p10", sa.Float(), nullable=True))
    op.add_column("kronos_predictions", sa.Column("predicted_return_p90", sa.Float(), nullable=True))
    op.add_column("kronos_predictions", sa.Column("direction_agreement", sa.Float(), nullable=True))
    op.add_column("kronos_predictions", sa.Column("sample_count", sa.Integer(), nullable=True))

    kronos_predictions = sa.table(
        "kronos_predictions",
        sa.column("predicted_return", sa.Float()),
        sa.column("predicted_return_p10", sa.Float()),
        sa.column("predicted_return_p90", sa.Float()),
        sa.column("direction_agreement", sa.Float()),
        sa.column("sample_count", sa.Integer()),
    )
    op.execute(
        kronos_predictions.update()
        .values(
            predicted_return_p10=kronos_predictions.c.predicted_return,
            predicted_return_p90=kronos_predictions.c.predicted_return,
            direction_agreement=sa.literal(1.0),
            sample_count=sa.literal(1),
        )
        .where(kronos_predictions.c.sample_count.is_(None))
    )

    op.alter_column("kronos_predictions", "predicted_return_p10", nullable=False)
    op.alter_column("kronos_predictions", "predicted_return_p90", nullable=False)
    op.alter_column("kronos_predictions", "direction_agreement", nullable=False)
    op.alter_column("kronos_predictions", "sample_count", nullable=False)

    # confidence was a hardcoded 0.5 constant; it's now genuinely unknown
    # until a calibration table exists, so existing rows' 0.5 no longer means
    # anything and must not be read as if it were calibrated.
    #
    # ORDER BUG (found 2026-09-16, first real run of this migration against
    # actual pre-existing Postgres data via a restored dump -- every prior
    # verification only ran `Base.metadata.create_all` on SQLite, which never
    # exercises migrations at all): the column was still NOT NULL when the
    # UPDATE ran, so it violated its own not-null constraint on any row with
    # a real (non-NULL) confidence value. Relax the column FIRST.
    op.alter_column("kronos_predictions", "confidence", nullable=True)
    op.execute("UPDATE kronos_predictions SET confidence = NULL")


def downgrade() -> None:
    op.alter_column("kronos_predictions", "confidence", nullable=False)
    op.execute("UPDATE kronos_predictions SET confidence = 0.5 WHERE confidence IS NULL")
    op.drop_column("kronos_predictions", "sample_count")
    op.drop_column("kronos_predictions", "direction_agreement")
    op.drop_column("kronos_predictions", "predicted_return_p90")
    op.drop_column("kronos_predictions", "predicted_return_p10")
