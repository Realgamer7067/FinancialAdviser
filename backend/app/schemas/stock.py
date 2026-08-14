from datetime import datetime

from pydantic import BaseModel

from app.schemas.recommendation import RecommendationCard


class FundamentalsOut(BaseModel):
    as_of_date: str
    roe: float | None
    revenue_growth: float | None
    debt_to_equity: float | None
    pe: float | None
    net_margin: float | None
    market_cap: float | None
    source: str


class TechnicalsOut(BaseModel):
    rsi_14: float | None
    trend: str | None
    volatility_30d: float | None
    drawdown_1y: float | None
    macd_hist: float | None
    computed_at: datetime


class KronosOut(BaseModel):
    forecast_horizon: str
    direction: str
    predicted_return: float
    confidence: float
    generated_at: datetime


class NewsOut(BaseModel):
    sentiment_score: float
    confidence: float
    article_count: int
    window_start: datetime
    window_end: datetime


class StockDetail(BaseModel):
    symbol: str
    name: str
    sector: str | None
    latest_price: float | None
    fundamentals: FundamentalsOut | None
    technicals: TechnicalsOut | None
    kronos: KronosOut | None
    news: NewsOut | None
    recommendation: RecommendationCard | None
