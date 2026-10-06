"""V3 Phase 03 (holdings/goals/commitments/catalogue) and Phase 04
(Gemini scheduler) tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-14

docs/v3-execution/phase-03.md, phase-04.md. Eight new tables from five
parallel workers, combined into one migration:

Phase 03 -- typed financial inputs:
- holdings_snapshots / holding_positions (immutable, append-only; a new
  import creates a new snapshot, never mutates an old one)
- goals / goal_earmarks (soft-supersession on edit, same pattern as
  market_candles from Phase 02; earmark sum-per-holding enforced at the
  application layer, not a DB constraint, since it requires a cross-row
  aggregate check)
- recurring_commitments (budget_interpretation is DB-nullable but
  API-required -- enforced by the endpoint, not the schema, matching this
  codebase's existing convention of keeping "must be explicit" business
  rules in application code, not overloading NOT NULL for it)

Money columns use NUMERIC (Decimal), never FLOAT, per V3 section 10.1's
explicit requirement -- a deliberate departure from this codebase's existing
Float-for-money columns elsewhere, which predate this contract.

Phase 04 -- five-project Gemini scheduler:
- model_projects / model_call_reservations (quota identity + atomic
  reservation lifecycle; credential_ref is a secret-reference NAME only)

Phase 03 -- product catalogue:
- product_catalog_entries (every seeded row is_synthetic=True; no real
  reviewed product data exists yet, see docs/v3-execution/STATE.md)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- holdings ------------------------------------------------------
    op.create_table(
        "holdings_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("import_hash", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "holding_positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("holdings_snapshots.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("raw_identifier_text", sa.String(), nullable=True),
        sa.Column("account_label", sa.String(), nullable=True),
        sa.Column("units", sa.Numeric(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("valuation_source", sa.String(), nullable=False),
        sa.Column("cost_basis", sa.Numeric(), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lock_reason", sa.String(), nullable=True),
        sa.Column("ownership", sa.String(), nullable=False),
        sa.Column("include_in_planning", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("identification_confidence", sa.String(), nullable=False),
    )
    op.create_index("ix_holding_positions_snapshot_id", "holding_positions", ["snapshot_id"])

    # --- goals -----------------------------------------------------------
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("target_amount", sa.Numeric(), nullable=False),
        sa.Column("target_basis", sa.String(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("flexibility", sa.String(), nullable=False),
        sa.Column("inflation_assumption", sa.Numeric(), nullable=True),
        sa.Column("inflation_assumption_version", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "goal_earmarks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("holding_position_id", sa.Uuid(), sa.ForeignKey("holding_positions.id"), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_goal_earmarks_goal_id", "goal_earmarks", ["goal_id"])
    op.create_index("ix_goal_earmarks_holding_position_id", "goal_earmarks", ["holding_position_id"])

    # --- commitments -------------------------------------------------------
    op.create_table(
        "recurring_commitments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("contribution_timing", sa.String(), nullable=False),
        sa.Column("step_up_rule", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id"), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("budget_interpretation", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- product catalogue ---------------------------------------------
    op.create_table(
        "product_catalog_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_ids", sa.JSON(), nullable=False),
        sa.Column("parent_exposure_id", sa.String(), nullable=True),
        sa.Column("product_type", sa.String(), nullable=False),
        sa.Column("issuer_or_amc", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("support_level", sa.String(), nullable=False),
        sa.Column("exposure_vector", sa.JSON(), nullable=False),
        sa.Column("exposure_as_of", sa.Date(), nullable=False),
        sa.Column("valuation_method", sa.String(), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=True),
        sa.Column("eligible_contribution_methods", sa.JSON(), nullable=False),
        sa.Column("minimum_initial", sa.Numeric(), nullable=True),
        sa.Column("minimum_additional", sa.Numeric(), nullable=True),
        sa.Column("increment", sa.Numeric(), nullable=True),
        sa.Column("quantity_granularity", sa.String(), nullable=False),
        sa.Column("settlement_delay_days", sa.Integer(), nullable=True),
        sa.Column("maturity_or_lock_rule", sa.String(), nullable=True),
        sa.Column("fee_assumptions", sa.JSON(), nullable=True),
        sa.Column("eligibility_predicates", sa.JSON(), nullable=True),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("source_freshness", sa.Date(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Gemini scheduler ------------------------------------------------
    op.create_table(
        "model_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alias", sa.String(), nullable=False, unique=True),
        sa.Column("cloud_project_id", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("supported_model_ids", sa.JSON(), nullable=False),
        sa.Column("daily_spend_cap_usd", sa.Float(), nullable=False),
        sa.Column("credential_ref", sa.String(), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "model_call_reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("artifact_key", sa.String(), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("model_projects.id"), nullable=False),
        sa.Column("task_attempt_id", sa.String(), nullable=False, unique=True),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("actual_input_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_output_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_call_reservations_artifact_key", "model_call_reservations", ["artifact_key"])


def downgrade() -> None:
    op.drop_index("ix_model_call_reservations_artifact_key", table_name="model_call_reservations")
    op.drop_table("model_call_reservations")
    op.drop_table("model_projects")

    op.drop_table("product_catalog_entries")

    op.drop_table("recurring_commitments")

    op.drop_index("ix_goal_earmarks_holding_position_id", table_name="goal_earmarks")
    op.drop_index("ix_goal_earmarks_goal_id", table_name="goal_earmarks")
    op.drop_table("goal_earmarks")
    op.drop_table("goals")

    op.drop_index("ix_holding_positions_snapshot_id", table_name="holding_positions")
    op.drop_table("holding_positions")
    op.drop_table("holdings_snapshots")
