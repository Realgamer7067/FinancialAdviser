"""Immutable saved analyses bound to a Twin state + valuation (Portfolio
Intelligence Engine Phase 05). One typed table for risk assessments and
scenario runs: re-requesting the same inputs returns the same row, and a saved
run is replayed by id, never recomputed against newer data."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class AnalysisRun(Base, UUIDPKMixin):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "state_id", "valuation_id", "method_version", "inputs_hash", name="uq_analysis_identity"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # "risk" | "scenario"
    state_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("portfolio_states.id"), index=True)
    valuation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("valuation_snapshots.id"))
    method_version: Mapped[str] = mapped_column(String)
    inputs_hash: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
