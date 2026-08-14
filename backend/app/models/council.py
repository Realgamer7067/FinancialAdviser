import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class CouncilRun(Base, UUIDPKMixin):
    """One recommendation-run trace (Section 57 research log)."""

    __tablename__ = "council_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    # Informational back-reference only (no FK constraint) -- the authoritative
    # link is RecommendationJob.result_council_run_id, avoiding a circular FK.
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    market_regime: Mapped[str] = mapped_column(String)
    universe_size: Mapped[int] = mapped_column(Integer)
    candidates_after_screen: Mapped[int] = mapped_column(Integer)
    candidates_after_kronos_news: Mapped[int] = mapped_column(Integer)
    candidates_to_council: Mapped[int] = mapped_column(Integer)
    plan: Mapped[dict] = mapped_column(JSON)  # Qwen planner output
    status: Mapped[str] = mapped_column(String, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateScore(Base, UUIDPKMixin):
    """Deterministic per-candidate score breakdown (Section 18) -- computed in
    Python, never invented by the LLM."""

    __tablename__ = "candidate_scores"

    council_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("council_runs.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))

    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    kronos_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    portfolio_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    final_score: Mapped[float] = mapped_column(Float)
    model_agreement: Mapped[float] = mapped_column(Float)  # 0..1, Section 51
    data_quality: Mapped[float] = mapped_column(Float)  # 0..1, Section 19
    confidence: Mapped[float] = mapped_column(Float)  # 0..1, derived (Section 19)


class CouncilOutput(Base, UUIDPKMixin):
    """One analyst-role's structured output for one candidate (Section 16/42).
    Chain-of-thought is never stored -- only the concise structured result."""

    __tablename__ = "council_outputs"

    council_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("council_runs.id"))
    # Nullable: the "planner" role is run-level, not tied to one instrument.
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(String)  # planner/bull/bear/fundamental/quant/risk/judge
    content: Mapped[dict] = mapped_column(JSON)  # validated pydantic-schema output
    model_name: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
