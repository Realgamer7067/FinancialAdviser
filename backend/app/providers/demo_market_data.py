"""Fallback MarketDataProvider used in DEMO_MODE or when Upstox auth has expired
(Section 65: cached/sample data, never presented as live -- every Quote/Candle
here is flagged `is_stale=True` / `source="demo_seed"`)."""

import random
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from app.providers.base import Candle, InstrumentMeta, MarketDataProvider, MarketStatus, Quote
from app.providers.nifty50_seed import NIFTY50_SEED

# Deterministic per-symbol seed so demo runs are reproducible, not randomly
# different every request.
_BASE_PRICES = {s.symbol: 500 + (hash(s.symbol) % 3000) for s in NIFTY50_SEED}
_BASE_PRICES["NIFTY50"] = 22000
_BASE_PRICES["INDIA_VIX"] = 14


class DemoMarketDataProvider(MarketDataProvider):
    async def get_quote(self, symbol: str) -> Quote:
        base = _BASE_PRICES[symbol]
        now = datetime.now(timezone.utc)
        return Quote(
            symbol=symbol,
            price=base,
            open=base * 0.995,
            high=base * 1.01,
            low=base * 0.985,
            close=base,
            volume=500_000,
            source="demo_seed",
            is_stale=True,
            market_time=now,
            retrieved_at=now,
        )

    async def get_historical_ohlcv(
        self, symbol: str, interval: Literal["1d", "1w", "1mo"], from_date: date, to_date: date
    ) -> list[Candle]:
        base = _BASE_PRICES[symbol]
        rng = random.Random(hash(symbol))
        days = (to_date - from_date).days
        step = {"1d": 1, "1w": 7, "1mo": 30}[interval]
        retrieved_at = datetime.now(timezone.utc)
        candles = []
        price = base
        for i in range(0, max(days, step), step):
            drift = rng.uniform(-0.02, 0.02)
            price = max(price * (1 + drift), 1.0)
            ts = datetime.combine(from_date + timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc)
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price * 0.99,
                    high=price * 1.02,
                    low=price * 0.97,
                    close=price,
                    volume=rng.randint(100_000, 900_000),
                    source="demo_seed",
                    retrieved_at=retrieved_at,
                )
            )
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
        now = datetime.now(timezone.utc)
        return [
            Quote(
                symbol="NIFTY50",
                price=22000,
                open=21900,
                high=22100,
                low=21850,
                close=22000,
                volume=0,
                source="demo_seed",
                is_stale=True,
                market_time=now,
                retrieved_at=now,
            )
        ]

    async def get_market_status(self, exchange: str = "NSE") -> MarketStatus:
        return MarketStatus(exchange=exchange, status="UNKNOWN", checked_at=datetime.now(timezone.utc))
