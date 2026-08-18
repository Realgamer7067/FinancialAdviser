"""YFinanceMarketDataProvider (Section 5) -- Yahoo Finance market data, no
broker account/KYC/OAuth required. Same free, unofficial, rate-limited source
already used for fundamentals (`fundamentals.py`); swap in a paid provider
before any production use.

Index tickers: NIFTY 50 -> `^NSEI`, India VIX -> `^INDIAVIX`. Equities use the
`<SYMBOL>.NS` convention already defined on `SeedInstrument.yfinance_ticker`.
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from app.providers.base import Candle, InstrumentMeta, MarketDataProvider, MarketStatus, Quote
from app.providers.nifty50_seed import NIFTY50_SEED

IST = timezone(timedelta(hours=5, minutes=30))
_SOURCE = "yfinance"
logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _fast_info_raw(ticker: str) -> dict:
    return yf.Ticker(ticker).fast_info


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _history_raw(ticker: str, start: date, end: date, interval: str):
    return yf.Ticker(ticker).history(start=start, end=end, interval=interval)

_INDEX_TICKERS = {"NIFTY50": "^NSEI", "INDIA_VIX": "^INDIAVIX"}
_INTERVAL_TO_YF = {"1d": "1d", "1w": "1wk", "1mo": "1mo"}


class YFinanceMarketDataProvider(MarketDataProvider):
    def __init__(self):
        self._symbol_to_ticker = {s.symbol: s.yfinance_ticker for s in NIFTY50_SEED}
        self._symbol_to_ticker.update(_INDEX_TICKERS)

    def _ticker(self, symbol: str) -> str:
        return self._symbol_to_ticker.get(symbol, f"{symbol}.NS")

    async def get_quote(self, symbol: str) -> Quote:
        return await asyncio.to_thread(self._fetch_quote, symbol)

    def _fetch_quote(self, symbol: str) -> Quote:
        try:
            info = _fast_info_raw(self._ticker(symbol))
        except Exception as exc:
            logger.warning("yfinance quote fetch failed for %s after retries: %s", symbol, exc)
            raise
        now = datetime.now(timezone.utc)
        price = float(info["last_price"])
        return Quote(
            symbol=symbol,
            price=price,
            open=float(info.get("open") or price),
            high=float(info.get("day_high") or price),
            low=float(info.get("day_low") or price),
            close=price,
            volume=int(info.get("last_volume") or 0),
            source=_SOURCE,
            is_stale=False,
            market_time=now,
            retrieved_at=now,
        )

    async def get_historical_ohlcv(
        self, symbol: str, interval: Literal["1d", "1w", "1mo"], from_date: date, to_date: date
    ) -> list[Candle]:
        return await asyncio.to_thread(self._fetch_history, symbol, interval, from_date, to_date)

    def _fetch_history(
        self, symbol: str, interval: Literal["1d", "1w", "1mo"], from_date: date, to_date: date
    ) -> list[Candle]:
        try:
            hist = _history_raw(
                self._ticker(symbol), from_date, to_date + timedelta(days=1), _INTERVAL_TO_YF[interval]
            )
        except Exception as exc:
            logger.warning("yfinance history fetch failed for %s after retries: %s", symbol, exc)
            raise
        retrieved_at = datetime.now(timezone.utc)
        candles = [
            Candle(
                timestamp=ts.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
                source=_SOURCE,
                retrieved_at=retrieved_at,
            )
            for ts, row in hist.iterrows()
        ]
        # yfinance already returns ascending order; sort defensively so callers
        # relying on `candles[-1]` as latest stay correct regardless.
        candles.sort(key=lambda c: c.timestamp)
        return candles

    async def get_instruments(self) -> list[InstrumentMeta]:
        return [
            InstrumentMeta(
                symbol=s.symbol,
                exchange="NSE",
                name=s.name,
                instrument_key=s.instrument_key,
                isin=s.isin,
                sector=s.sector,
            )
            for s in NIFTY50_SEED
        ]

    async def get_market_indices(self) -> list[Quote]:
        return [await self.get_quote("NIFTY50")]

    async def get_market_status(self, exchange: str = "NSE") -> MarketStatus:
        # Yahoo Finance exposes no exchange-status endpoint -- derive it from
        # NSE's published trading hours (9:15-15:30 IST, Mon-Fri) instead of
        # guessing (Section 43: deterministic computation, not invented data).
        now_ist = datetime.now(IST)
        status: Literal["PRE_OPEN", "OPEN", "CLOSED"] = "CLOSED"
        if now_ist.weekday() < 5 and time(9, 15) <= now_ist.time() <= time(15, 30):
            status = "OPEN"
        return MarketStatus(exchange=exchange, status=status, checked_at=datetime.now(timezone.utc))
