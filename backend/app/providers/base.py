"""Provider interfaces (Section 5/6). Every external data source sits behind one
of these -- swapping Upstox for another broker, or the RSS feed for a paid news
API, is an adapter, not a rewrite of the pipeline."""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    retrieved_at: datetime


class Quote(BaseModel):
    symbol: str
    price: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    is_stale: bool
    market_time: datetime
    retrieved_at: datetime


class InstrumentMeta(BaseModel):
    symbol: str
    exchange: str
    name: str
    instrument_key: str
    isin: str | None = None
    sector: str | None = None
    lot_size: int = 1


class MarketStatus(BaseModel):
    exchange: str
    status: Literal["PRE_OPEN", "OPEN", "CLOSED", "UNKNOWN"]
    checked_at: datetime


class MarketDataProvider(ABC):
    """Section 5. Live/historical Indian market data."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    async def get_historical_ohlcv(
        self, symbol: str, interval: Literal["1d", "1w", "1mo"], from_date: date, to_date: date
    ) -> list[Candle]: ...

    @abstractmethod
    async def get_instruments(self) -> list[InstrumentMeta]: ...

    @abstractmethod
    async def get_market_indices(self) -> list[Quote]: ...

    @abstractmethod
    async def get_market_status(self, exchange: str = "NSE") -> MarketStatus: ...


class FundamentalSnapshot(BaseModel):
    symbol: str
    as_of_date: date
    # UNKNOWN values are None, never guessed (Section 8).
    revenue: float | None = None
    revenue_growth: float | None = None
    ebitda: float | None = None
    ebitda_margin: float | None = None
    ebit: float | None = None
    pat: float | None = None
    eps: float | None = None
    eps_growth: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    total_debt: float | None = None
    debt_to_equity: float | None = None
    interest_coverage: float | None = None
    roe: float | None = None
    roce: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    pb: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    promoter_holding: float | None = None
    promoter_pledging: float | None = None
    institutional_ownership: float | None = None
    market_cap: float | None = None
    source: str = "unknown"
    retrieved_at: datetime


class FundamentalDataProvider(ABC):
    """Section 8. Deterministic fundamentals -- never LLM-estimated."""

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None: ...

    @abstractmethod
    async def get_universe(self) -> list[str]: ...


class RawNewsItem(BaseModel):
    source: str
    title: str
    url: str
    published_at: datetime
    retrieved_at: datetime
    summary: str | None = None


class NewsProvider(ABC):
    """Section 7. Legitimate syndicated feeds only -- never scraped HTML as the
    primary production source."""

    @abstractmethod
    async def fetch_latest(self, since: datetime | None = None) -> list[RawNewsItem]: ...
