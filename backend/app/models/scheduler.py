"""Phase 04 -- five-project Gemini scheduler (V3 build plan section 12).

Two tables:

- ``ModelProject``: one Google Cloud project's quota identity (section 12.1).
  ``credential_ref`` is a NAME/alias for a server-side secret (e.g. an env var
  name), never the secret value itself -- this module never touches actual
  credentials.
- ``ModelCallReservation``: one reserved-then-reconciled model call. Append-
  only lifecycle: ``reserved`` -> (dispatched, tracked implicitly, no extra
  status) -> exactly one of ``committed`` / ``released`` / ``expired`` /
  ``unknown_billing``.

No Postgres-specific column types are used (matches this codebase's existing
convention -- see ``backend/tests/conftest.py``'s docstring) so the schema
works unchanged against the in-memory SQLite test DB and against Postgres.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ModelProject(Base, UUIDPKMixin, TimestampMixin):
    """One Google Cloud project's quota identity (V3 section 12.1: "record a
    nonsecret project alias, actual Cloud project ID, owner, permitted
    environment, supported model IDs, billing tier, observed quota
    dimensions, daily spend cap and credential reference"). Credential
    reference is a NAME/alias for a server-side secret, never the secret
    itself -- never store an actual API key in this table."""

    __tablename__ = "model_projects"

    alias: Mapped[str] = mapped_column(String, unique=True)  # nonsecret, e.g. "team-member-1-dev"
    cloud_project_id: Mapped[str] = mapped_column(String)  # real GCP project id, still not a secret
    owner: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)  # e.g. "dev", "shared"
    supported_model_ids: Mapped[list] = mapped_column(JSON)  # e.g. ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    daily_spend_cap_usd: Mapped[float] = mapped_column(Float)
    credential_ref: Mapped[str] = mapped_column(String)  # name of a server-side secret/env var, NOT the secret value
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)  # flip False on repeated 401/403/5xx
    # base.py's TimestampMixin only defines created_at (server_default=now());
    # no existing model in this codebase has an updated_at column to copy, so
    # this mirrors that same DateTime(timezone=True)/func.now() convention
    # with onupdate added.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelCallReservation(Base, UUIDPKMixin):
    """One reserved-then-reconciled model call. Append-only lifecycle:
    reserved -> (dispatched) -> (reconciled: committed/released/expired/
    unknown_billing)."""

    __tablename__ = "model_call_reservations"

    artifact_key: Mapped[str] = mapped_column(String, index=True)  # task dedup key
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("model_projects.id"))
    task_attempt_id: Mapped[str] = mapped_column(String, unique=True)  # caller-supplied idempotency key
    estimated_input_tokens: Mapped[int] = mapped_column(Integer)
    estimated_output_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)  # reserved|committed|released|expired|unknown_billing
    actual_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
