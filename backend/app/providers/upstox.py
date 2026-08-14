"""Upstox MarketDataProvider implementation (Section 5).

Endpoints below were confirmed against Upstox's public developer docs at
build time (https://upstox.com/developer/api-documentation/):
  - OAuth dialog:        GET  /v2/login/authorization/dialog
  - OAuth token exchange: POST /v2/login/authorization/token
  - Historical candle v3: GET  /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
  - OHLC quote v3:        GET  /v3/market-quote/ohlc
  - Market status:        GET  /v2/market/status/{exchange}

Known Upstox limitation: access tokens expire daily at 3:30 AM IST regardless of
issue time -- there is no silent refresh. `UpstoxAuthState` tracks expiry so the
caller can degrade to cached data instead of silently serving stale data as live
(Section 65).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx

from app.core.config import settings
from app.providers.base import Candle, InstrumentMeta, MarketDataProvider, MarketStatus, Quote
from app.providers.nifty50_seed import NIFTY50_SEED

UPSTOX_BASE = "https://api.upstox.com"
IST = timezone(timedelta(hours=5, minutes=30))

_INTERVAL_TO_UPSTOX_UNIT = {"1d": ("days", "1"), "1w": ("weeks", "1"), "1mo": ("months", "1")}


@dataclass(frozen=True)
class _IndexSeed:
    symbol: str
    instrument_key: str


# Index instrument_keys, not equities -- used for market-regime detection
# (Section 33), not part of the recommendable Nifty50 stock universe.
_INDEX_SEEDS: dict[str, _IndexSeed] = {
    "NIFTY50": _IndexSeed("NIFTY50", "NSE_INDEX|Nifty 50"),
    "INDIA_VIX": _IndexSeed("INDIA_VIX", "NSE_INDEX|India VIX"),
}


class UpstoxAuthRequired(Exception):
    """Raised when no valid (non-expired) Upstox access token is on file.
    Caller (admin router) should surface the /admin/upstox/login link."""


class UpstoxProvider(MarketDataProvider):
    def __init__(self, access_token: str | None, token_expires_at: datetime | None):
        self._access_token = access_token
        self._token_expires_at = token_expires_at
        self._symbol_index = {s.symbol: s for s in NIFTY50_SEED}
        self._symbol_index.update(_INDEX_SEEDS)

    @staticmethod
    def authorization_url() -> str:
        return (
            f"{UPSTOX_BASE}/v2/login/authorization/dialog"
            f"?response_type=code&client_id={settings.upstox_api_key}"
            f"&redirect_uri={settings.upstox_redirect_uri}"
        )

    @staticmethod
    async def exchange_code_for_token(code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{UPSTOX_BASE}/v2/login/authorization/token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "code": code,
                    "client_id": settings.upstox_api_key,
                    "client_secret": settings.upstox_api_secret,
                    "redirect_uri": settings.upstox_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def next_expiry_ist() -> datetime:
        """Upstox tokens expire 3:30 AM IST the day after issue."""
        now_ist = datetime.now(IST)
        expiry_date = now_ist.date() + timedelta(days=1)
        return datetime(expiry_date.year, expiry_date.month, expiry_date.day, 3, 30, tzinfo=IST)

    def _require_token(self) -> str:
        if not self._access_token:
            raise UpstoxAuthRequired("No Upstox access token on file. Visit /admin/upstox/login.")
        if self._token_expires_at and datetime.now(timezone.utc) >= self._token_expires_at:
            raise UpstoxAuthRequired("Upstox access token expired (daily expiry). Re-authenticate.")
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._require_token()}", "Accept": "application/json"}

    async def get_quote(self, symbol: str) -> Quote:
        seed = self._symbol_index[symbol]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{UPSTOX_BASE}/v3/market-quote/ohlc",
                params={"instrument_key": seed.instrument_key, "interval": "1d"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()["data"]
            row = next(iter(payload.values()))
            ohlc = row["live_ohlc"]
            now = datetime.now(timezone.utc)
            return Quote(
                symbol=symbol,
                price=ohlc["close"],
                open=ohlc["open"],
                high=ohlc["high"],
                low=ohlc["low"],
                close=ohlc["close"],
                volume=ohlc.get("volume", 0),
                source="upstox",
                is_stale=False,
                market_time=now,
                retrieved_at=now,
            )

    async def get_historical_ohlcv(
        self, symbol: str, interval: Literal["1d", "1w", "1mo"], from_date: date, to_date: date
    ) -> list[Candle]:
        seed = self._symbol_index[symbol]
        unit, step = _INTERVAL_TO_UPSTOX_UNIT[interval]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{UPSTOX_BASE}/v3/historical-candle/{seed.instrument_key}/{unit}/{step}"
                f"/{to_date.isoformat()}/{from_date.isoformat()}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            candles = resp.json()["data"]["candles"]
            retrieved_at = datetime.now(timezone.utc)
            parsed = [
                Candle(
                    timestamp=datetime.fromisoformat(c[0]),
                    open=c[1],
                    high=c[2],
                    low=c[3],
                    close=c[4],
                    volume=c[5],
                    source="upstox",
                    retrieved_at=retrieved_at,
                )
                for c in candles
            ]
            # Upstox returns newest-first; callers rely on ascending order
            # (e.g. `candles[-1]` as the latest price, return-series math).
            parsed.sort(key=lambda c: c.timestamp)
            return parsed

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
        # NIFTY 50 index instrument_key on Upstox: "NSE_INDEX|Nifty 50"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{UPSTOX_BASE}/v3/market-quote/ohlc",
                params={"instrument_key": "NSE_INDEX|Nifty 50", "interval": "1d"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()["data"]
            row = next(iter(payload.values()))
            ohlc = row["live_ohlc"]
            now = datetime.now(timezone.utc)
            return [
                Quote(
                    symbol="NIFTY50",
                    price=ohlc["close"],
                    open=ohlc["open"],
                    high=ohlc["high"],
                    low=ohlc["low"],
                    close=ohlc["close"],
                    volume=0,
                    source="upstox",
                    is_stale=False,
                    market_time=now,
                    retrieved_at=now,
                )
            ]

    async def get_market_status(self, exchange: str = "NSE") -> MarketStatus:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{UPSTOX_BASE}/v2/market/status/{exchange}", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()["data"]
            raw_status = str(data.get("status", "")).upper()
            status = raw_status if raw_status in {"PRE_OPEN", "OPEN", "CLOSED"} else "UNKNOWN"
            return MarketStatus(exchange=exchange, status=status, checked_at=datetime.now(timezone.utc))
