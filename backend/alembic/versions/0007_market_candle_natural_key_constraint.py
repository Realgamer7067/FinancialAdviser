"""add unique constraint on market_candles natural key, dedupe first

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14

docs/V2-RETHINK.md P0: a refresh always re-pulls the FULL history window and
used to insert it on top of existing rows with no natural-key constraint,
duplicating every overlapping session. app/pipelines/recommendation_pipeline.py
now deletes the overlapping (instrument, interval, source) rows before
inserting, but any database that already accumulated duplicates before this
fix needs those cleaned up before the constraint can be added -- keep the
most-recently-retrieved row per (instrument_id, interval, timestamp, source)
and drop the rest.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM market_candles a
        USING market_candles b
        WHERE a.instrument_id = b.instrument_id
          AND a.interval = b.interval
          AND a.timestamp = b.timestamp
          AND a.source = b.source
          AND (a.retrieved_at, a.id) < (b.retrieved_at, b.id)
        """
    )
    op.create_unique_constraint(
        "uq_market_candles_natural_key", "market_candles", ["instrument_id", "interval", "timestamp", "source"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_market_candles_natural_key", "market_candles", type_="unique")
