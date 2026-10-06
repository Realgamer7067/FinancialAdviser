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
    # docs/V2-RETHINK.md P1: the council previously saw only the 6 fields
    # above even though richer fundamentals were already fetched and stored
    # (FundamentalMetrics/FundamentalSnapshot) -- reuse what's already there
    # before considering any new data source.
    ebitda_margin: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    pb: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    institutional_ownership: float | None = None
    insider_holding_pct: float | None = None


class TechnicalEvidence(BaseModel):
    rsi_14: float | None
    trend: str | None
    volatility_30d: float | None
    drawdown_1y: float | None
    macd_hist: float | None
    beta: float | None


class KronosEvidence(BaseModel):
    forecast_horizon: str
    direction: str
    predicted_return: float
    predicted_return_p10: float
    predicted_return_p90: float
    direction_agreement: float
    sample_count: int
    confidence: float | None


class NewsArticleEvidence(BaseModel):
    """One real article the council can actually inspect, not just a folded-in
    number (docs/V2-RETHINK.md P1/section 4: "cannot inspect an article").
    Sourced from data already fetched and stored (NewsItem/NewsAnalysis) --
    no new retrieval needed."""

    headline: str
    url: str
    event_type: str
    sentiment: float
    published_at: str


class NewsEvidence(BaseModel):
    sentiment: float
    confidence: float
    article_count: int
    recent_articles: list[NewsArticleEvidence] = []


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
