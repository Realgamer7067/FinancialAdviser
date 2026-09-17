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
    beta: float | None
    # Latest-snapshot reference values (Phase 0B #2) -- TechnicalFeatures stores
    # one row per pipeline run, not a historical series, so these render as
    # reference callouts next to the price chart; the actual moving overlay
    # lines are computed client-side from the OHLC history endpoint below.
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_12: float | None
    ema_26: float | None
    bb_upper: float | None
    bb_lower: float | None
    computed_at: datetime


class KronosOut(BaseModel):
    forecast_horizon: str
    direction: str
    predicted_return: float
    predicted_return_p10: float
    predicted_return_p90: float
    direction_agreement: float
    sample_count: int
    confidence: float | None
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
    # Every other section here (fundamentals.as_of_date, technicals.computed_at,
    # kronos.generated_at, recommendation.generated_at) already carries its own
    # vintage stamp -- price was the one exception, with no way to tell how
    # stale it is relative to those. Each section can legitimately be a
    # different age (a report combines independently-fetched latest data with
    # a recommendation frozen at an earlier run, docs/V2-RETHINK.md P1) --
    # surfacing every vintage explicitly is the fix, not pretending they're
    # one snapshot.
    price_as_of: datetime | None
    # V3 Phase 02 (docs/v3-execution/CONTRACTS.md C1/C3): true when a
    # recommendation exists but predates the data-manifest system (no
    # recorded provenance for the evidence it used) -- fundamentals/
    # technicals/kronos below then fall back to "most recent" the same way
    # they always did, and the caller must not claim they're pinned to what
    # the recommendation actually saw. False whenever no recommendation
    # exists at all, or a manifest entry was found and evidence is pinned to it.
    evidence_is_legacy: bool
    fundamentals: FundamentalsOut | None
    technicals: TechnicalsOut | None
    kronos: KronosOut | None  # always the "30d" horizon -- what scoring uses
    # Up to 3 rows (7d/30d/90d, Phase 0B #4) -- only stocks that reached the
    # council loop get all 3; others may have just the 30d entry, or none.
    kronos_horizons: list[KronosOut] = []
    news: NewsOut | None
    recommendation: RecommendationCard | None


class NewsArticleOut(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    sentiment: float
    event_type: str
    confidence: float


class NewsArticlesOut(BaseModel):
    symbol: str
    articles: list[NewsArticleOut]


class PriceHistoryPoint(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceHistoryOut(BaseModel):
    symbol: str
    interval: str
    points: list[PriceHistoryPoint]
