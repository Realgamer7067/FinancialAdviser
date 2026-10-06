"""Research session/branch models (V3 Phase 07, docs/V3-IMPLEMENTATION-PLAN.md
section 9.2 "Research state machine" and section 9.3 "Tool contracts").

`ResearchSession` is the top-level bounded/budgeted/checkpointed research
attempt for one question (V3 9.2: created -> resolving -> retrieving ->
calculating -> synthesizing -> verifying -> ready_to_publish -> published,
plus terminal-but-not-happy-path cancelled/failed). `ResearchBranch` is one
of the (deterministic, for a standard question) independent evidence
branches -- financials_valuation / events_governance / peers_downside (V3
9.2: "Standard independent branches cover financials/valuation,
events/governance, and peers/downside... they retrieve different evidence").

State-machine transition enforcement and branch execution live in
`app/services/research_workflow.py`, not here -- this module is data only,
matching this codebase's convention (see `app/models/manifest.py`,
`app/models/holdings.py`).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class ResearchSession(Base, UUIDPKMixin):
    __tablename__ = "research_sessions"

    # None for a public/shared research session not tied to one user's
    # private data (V3 9.2 does not require every research session to be
    # user-scoped -- e.g. a pre-computed company research session shareable
    # across users).
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    question: Mapped[str] = mapped_column(String)
    instrument_ids: Mapped[list] = mapped_column(JSON)  # list of Instrument.id strings
    mode: Mapped[str] = mapped_column(String)  # "standard" | "deep"
    cutoff_policy: Mapped[dict] = mapped_column(JSON)  # {"cutoff_date": ..., "accept_sources_published_before": ...}
    state: Mapped[str] = mapped_column(String)  # see _VALID_TRANSITIONS in research_workflow.py
    # For follow-ups (V3 9.6) -- deeper revision/reuse logic is a parallel
    # worker's scope, this field is the only linkage this module owns.
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("research_sessions.id"), nullable=True
    )
    budget_envelope: Mapped[dict] = mapped_column(JSON)  # {"max_searches", "max_fetches", "max_tokens", "deadline_seconds", ...}
    budget_consumed: Mapped[dict] = mapped_column(JSON, default=dict)  # same keys, running totals
    named_gaps: Mapped[list] = mapped_column(JSON, default=list)  # filled when a branch ends "partial"/"unavailable"
    # Persisted by the research API/thesis refresh so a later GET can restore them (previously they existed
    # only in the synchronous POST response). Null = never recorded (older sessions).
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contradictions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    budget_exhausted_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchBranch(Base, UUIDPKMixin):
    __tablename__ = "research_branches"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_sessions.id"), index=True)
    branch_type: Mapped[str] = mapped_column(String)  # "financials_valuation" | "events_governance" | "peers_downside"
    status: Mapped[str] = mapped_column(String)  # "pending" | "running" | "complete" | "partial" | "unavailable" | "failed" | "cancelled"
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)  # Fact.id strings this branch produced
    gap_reason: Mapped[str | None] = mapped_column(String, nullable=True)  # populated when status is partial/unavailable/failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
