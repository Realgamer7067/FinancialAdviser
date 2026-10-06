"""Angel instrument master, latest quotes and watchlists

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-01

Additive only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_instruments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("trading_symbol", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("series", sa.String(), nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("tick_size", sa.Numeric(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("match_basis", sa.String(), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "exchange", "token", name="uq_broker_instruments_token"),
    )
    op.create_index("ix_broker_instruments_trading_symbol", "broker_instruments", ["trading_symbol"])
    op.create_index("ix_broker_instruments_symbol", "broker_instruments", ["symbol"])
    op.create_index("ix_broker_instruments_instrument_id", "broker_instruments", ["instrument_id"])

    op.create_table(
        "market_quotes",
        sa.Column("broker_instrument_id", sa.Uuid(), sa.ForeignKey("broker_instruments.id"), primary_key=True),
        sa.Column("ltp", sa.Numeric(), nullable=False),
        sa.Column("prev_close", sa.Numeric(), nullable=True),
        sa.Column("open", sa.Numeric(), nullable=True),
        sa.Column("high", sa.Numeric(), nullable=True),
        sa.Column("low", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("percent_change", sa.Numeric(), nullable=True),
        sa.Column("week52_high", sa.Numeric(), nullable=True),
        sa.Column("week52_low", sa.Numeric(), nullable=True),
        sa.Column("exchange_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
    )

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("watchlist_id", sa.Uuid(), sa.ForeignKey("watchlists.id"), nullable=False),
        sa.Column("broker_instrument_id", sa.Uuid(), sa.ForeignKey("broker_instruments.id"), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("why_watching", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("watchlist_id", "broker_instrument_id", name="uq_watchlist_items_unique"),
    )
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])

    op.create_table(
        "watch_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("watchlist_items.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("threshold", sa.Numeric(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("triggered", sa.Boolean(), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watch_alerts_item_id", "watch_alerts", ["item_id"])


def downgrade() -> None:
    op.drop_table("watch_alerts")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("market_quotes")
    op.drop_table("broker_instruments")
