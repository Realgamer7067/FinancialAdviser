from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RecommendationCard(BaseModel):
    id: UUID
    symbol: str
    name: str
    recommendation: str
    confidence: float
    score: float
    risk_level: str
    risk_tier: str | None
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
