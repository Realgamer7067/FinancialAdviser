from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CouncilRoleOutput(BaseModel):
    """One analyst role's structured output for one candidate (Phase 0B #1) --
    council_outputs was always fully computed/persisted, just never read by
    any API endpoint before this."""

    role: str  # bull/bear/fundamental/quant/risk/judge
    content: dict
    model_name: str
    model_version: str
    prompt_version: str
    created_at: datetime


class RecommendationCard(BaseModel):
    id: UUID
    symbol: str
    name: str
    recommendation: str
    confidence: float
    confidence_band: str | None
    score: float
    risk_level: str
    risk_tier: str | None
    risk_tier_score: float | None
    risk_tier_breakdown: dict | None
    suggested_horizon: str
    strengths: list[str]
    risks: list[str]
    rationale: str
    evidence: dict
    fundamental_score: float | None
    technical_score: float | None
    kronos_score: float | None
    news_score: float | None
    portfolio_score: float | None
    risk_score: float | None
    model_agreement: float
    data_quality: float
    generated_at: datetime
    council_outputs: list[CouncilRoleOutput] = []


class CouncilRunSummary(BaseModel):
    id: UUID
    status: str
    market_regime: str
    universe_size: int
    candidates_after_screen: int
    candidates_after_kronos_news: int
    candidates_to_council: int
    plan: dict
    started_at: datetime
    completed_at: datetime | None
    recommendations: list[RecommendationCard]
