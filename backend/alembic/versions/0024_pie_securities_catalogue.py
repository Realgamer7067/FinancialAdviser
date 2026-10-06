"""Securities catalogue and corporate actions

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-01

Additive, plus one widening: market_quotes.volume becomes BIGINT because a full-market
snapshot includes instruments whose daily volume can exceed 32 bits. The downgrade does
not narrow it back (narrowing could fail on legitimate data).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("isin_reinvest", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("series", sa.String(), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=True),
        sa.Column("face_value", sa.Numeric(), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("asset_class", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("scheme_code", sa.String(), nullable=True),
        sa.Column("amc", sa.String(), nullable=True),
        sa.Column("plan", sa.String(), nullable=True),
        sa.Column("option", sa.String(), nullable=True),
        sa.Column("nav", sa.Numeric(), nullable=True),
        sa.Column("nav_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_securities_source_key"),
    )
    op.create_index("ix_securities_kind_active", "securities", ["kind", "is_active"])
    for col in ("isin", "symbol", "sector", "asset_class", "scheme_code"):
        op.create_index(f"ix_securities_{col}", "securities", [col])

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ratio_num", sa.Numeric(), nullable=True),
        sa.Column("ratio_den", sa.Numeric(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("price_factor", sa.Numeric(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "ex_date", "subject", name="uq_corporate_actions_event"),
    )
    for col in ("symbol", "isin", "ex_date"):
        op.create_index(f"ix_corporate_actions_{col}", "corporate_actions", [col])

    op.add_column("broker_instruments", sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"), nullable=True))
    op.create_index("ix_broker_instruments_security_id", "broker_instruments", ["security_id"])
    op.add_column("portfolio_jobs", sa.Column("result", sa.JSON(), nullable=True))
    op.alter_column("market_quotes", "volume", type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    op.drop_column("portfolio_jobs", "result")
    op.drop_index("ix_broker_instruments_security_id", table_name="broker_instruments")
    op.drop_column("broker_instruments", "security_id")
    op.drop_table("corporate_actions")
    op.drop_table("securities")
