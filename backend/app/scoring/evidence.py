"""Structured evidence schema fed to the Qwen council (Section 17). Built
entirely from stored deterministic/model outputs -- the council never sees raw
web pages or unstructured blobs."""

from pydantic import BaseModel


class MarketEvidence(BaseModel):
    price: float
    market_cap: float | None
    volume: int


class FundamentalEvidence(BaseModel):
    roe: float | None
    revenue_growth: float | None
    debt_to_equity: float | None
    pe: float | None
    net_margin: float | None
    promoter_pledging: float | None


class TechnicalEvidence(BaseModel):
    rsi_14: float | None
    trend: str | None
    volatility_30d: float | None
    drawdown_1y: float | None
    macd_hist: float | None


class KronosEvidence(BaseModel):
    forecast_horizon: str
    direction: str
    predicted_return: float
    confidence: float


class NewsEvidence(BaseModel):
    sentiment: float
    confidence: float
    article_count: int


class PortfolioEvidence(BaseModel):
    recommended_weight: float | None
    expected_sharpe: float | None


class CandidateEvidence(BaseModel):
    """One instrument's full structured evidence packet (Section 17)."""

    symbol: str
    exchange: str
    market: MarketEvidence
    fundamentals: FundamentalEvidence | None
    technical: TechnicalEvidence | None
    kronos: KronosEvidence | None
    news: NewsEvidence | None
    portfolio: PortfolioEvidence | None
