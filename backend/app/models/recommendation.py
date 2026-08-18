import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin

# recommendation values (Section 20/54): STRONG_CANDIDATE, CANDIDATE, WATCHLIST,
# NO_RECOMMENDATION -- never a bare "BUY". Enforced in app/scoring, not here.


class Recommendation(Base, UUIDPKMixin):
    __tablename__ = "recommendations"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    council_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("council_runs.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))

    recommendation: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String)
    # Composite 4-band tier (safer/moderate/risky/riskiest) from a fuller signal
    # set than risk_level's volatility-only band -- None when too few signals
    # were available (Section 8: never guess). See app/scoring/subscores.py::risk_tier.
    risk_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    suggested_horizon: Mapped[str] = mapped_column(String)

    # Raw per-signal breakdown (Section 18), mirrors CandidateScore -- duplicated
    # here so the frontend can chart it without a new join/endpoint.
    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    kronos_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    portfolio_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    strengths: Mapped[list] = mapped_column(JSON)
    risks: Mapped[list] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)  # full structured evidence schema (Section 17)
    rationale: Mapped[str] = mapped_column(String)

    model_agreement: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortfolioRecommendation(Base, UUIDPKMixin):
    __tablename__ = "portfolio_recommendations"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    council_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("council_runs.id"))
    portfolio_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("portfolio_results.id")
    )
    allocations: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
