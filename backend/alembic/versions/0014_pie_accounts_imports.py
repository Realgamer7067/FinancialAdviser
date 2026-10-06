"""Portfolio Intelligence Engine Phase 01: source accounts and imports

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-30

Additive only. source_accounts, account_coverage_attestations, source_imports,
position_observations. Legacy holdings_snapshots/holding_positions untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("masked_external_id", sa.String(), nullable=True),
        sa.Column("external_fingerprint", sa.String(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "label", name="uq_source_accounts_user_label"),
        sa.UniqueConstraint(
            "user_id", "source_type", "external_fingerprint", name="uq_source_accounts_fingerprint"
        ),
    )
    op.create_index("ix_source_accounts_user_id", "source_accounts", ["user_id"])

    op.create_table(
        "account_coverage_attestations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("missing_account_types", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_coverage_user_version"),
    )
    op.create_index(
        "ix_account_coverage_attestations_user_id", "account_coverage_attestations", ["user_id"]
    )

    op.create_table(
        "source_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("source_accounts.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "legacy_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("holdings_snapshots.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_source_imports_account_key"),
    )
    op.create_index("ix_source_imports_account_id", "source_imports", ["account_id"])

    op.create_table(
        "position_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey("source_imports.id"), nullable=False),
        sa.Column("row_ordinal", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("resolution", sa.String(), nullable=False),
        sa.Column("resolution_note", sa.String(), nullable=True),
        sa.Column("units", sa.Numeric(), nullable=True),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("cost_basis", sa.Numeric(), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("ownership", sa.String(), nullable=False),
        sa.UniqueConstraint("import_id", "row_ordinal", name="uq_position_obs_import_row"),
    )
    op.create_index("ix_position_observations_import_id", "position_observations", ["import_id"])


def downgrade() -> None:
    op.drop_table("position_observations")
    op.drop_table("source_imports")
    op.drop_table("account_coverage_attestations")
    op.drop_table("source_accounts")
