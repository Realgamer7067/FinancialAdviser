"""One-time historical EOD cache pull from TrueData (see .TD_API_Docs/TrueData
Market Data API Documentation v2.6.pdf -- gitignored, NDA-covered, never
reference its contents outside this repo).

Scope is deliberately narrow (see the beyond-MVP plan, Part 3): the user has a
short trial TrueData key and wants a one-time snapshot of daily OHLCV for a
fixed watchlist, permanently cached into the same `MarketCandle` table the
live pipeline already reads through its DB-cache-first path
(`_get_cached_candles`/`_fetch_candles` in `app/pipelines/recommendation_pipeline.py`).
No live/real-time feature, no new MarketDataProvider -- this is a manual CLI
script, run during the trial window, not a service.

Auth:   POST https://auth.truedata.in/token (form-encoded username/password)
History: GET https://history.truedata.in/getlastnbars?symbol=...&interval=eod
         (the only endpoint that supports a daily/eod bar interval)

Usage: cd backend && python scripts/sync_truedata_history.py
Requires TRUEDATA_USERNAME / TRUEDATA_PASSWORD in .env.

Reminder (see feedback memory "TrueData NDA -- never push to GitHub"): this
script's only output is rows in the local Postgres DB. It writes no files to
the repo. Never commit credentials or anything derived from TrueData to git.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.market import Instrument, MarketCandle
from app.providers.nifty50_seed import NIFTY50_SEED
from app.utils.time import utcnow

IST = timezone(timedelta(hours=5, minutes=30))

TRUEDATA_AUTH_URL = "https://auth.truedata.in/token"
TRUEDATA_HISTORY_URL = "https://history.truedata.in/getlastnbars"
NBARS = 200  # max allowed by getlastnbars
SOURCE = "truedata"

# 30 liquid, well-known Nifty50 names -- well under the plan's 50-symbol cap.
# Edit this list to change the watchlist; each must exist in NIFTY50_SEED.
WATCHLIST_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "LT",
    "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN",
    "ULTRACEMCO", "WIPRO", "KOTAKBANK", "BAJFINANCE", "NESTLEIND",
    "HCLTECH", "TATAMOTORS", "TATASTEEL", "POWERGRID", "NTPC",
    "ONGC", "ADANIENT", "ADANIPORTS", "JSWSTEEL", "GRASIM",
]


async def _get_access_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        TRUEDATA_AUTH_URL,
        data={
            "username": settings.truedata_username,
            "password": settings.truedata_password,
            "grant_type": "password",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if "access_token" not in body:
        raise RuntimeError(f"TrueData auth failed: {body}")
    return body["access_token"]


def _parse_timestamp(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


async def _fetch_eod_bars(client: httpx.AsyncClient, token: str, symbol: str) -> list[dict]:
    resp = await client.get(
        TRUEDATA_HISTORY_URL,
        params={"symbol": symbol, "response": "csv", "nbars": NBARS, "interval": "eod", "bidask": 0},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or text.lower().startswith("no data exists"):
        print(f"  {symbol}: no data returned", file=sys.stderr)
        return []

    bars = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 7:
            continue
        timestamp, open_, high, low, close, volume, _oi = parts[:7]
        bars.append(
            {
                "timestamp": _parse_timestamp(timestamp),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": int(float(volume)),
            }
        )
    return bars


async def main() -> None:
    if not settings.truedata_username or not settings.truedata_password:
        print("TRUEDATA_USERNAME / TRUEDATA_PASSWORD not set in .env -- aborting.", file=sys.stderr)
        sys.exit(1)

    seed_by_symbol = {s.symbol: s for s in NIFTY50_SEED}
    symbols = [s for s in WATCHLIST_SYMBOLS if s in seed_by_symbol]
    missing = [s for s in WATCHLIST_SYMBOLS if s not in seed_by_symbol]
    if missing:
        print(f"WARNING: not in NIFTY50_SEED, skipping: {missing}", file=sys.stderr)

    async with httpx.AsyncClient() as client, AsyncSessionLocal() as db:
        token = await _get_access_token(client)
        print(f"Authenticated. Pulling {len(symbols)} symbols, {NBARS} EOD bars each...")

        total_rows = 0
        for symbol in symbols:
            seed = seed_by_symbol[symbol]
            instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
            if instrument is None:
                instrument = Instrument(
                    symbol=seed.symbol, exchange="NSE", isin=seed.isin, name=seed.name,
                    sector=seed.sector, instrument_key=seed.instrument_key,
                )
                db.add(instrument)
                await db.flush()

            bars = await _fetch_eod_bars(client, token, symbol)
            if not bars:
                continue

            # Idempotent re-run: replace any prior truedata-sourced rows for
            # this symbol rather than appending duplicates.
            await db.execute(
                delete(MarketCandle).where(
                    MarketCandle.instrument_id == instrument.id,
                    MarketCandle.interval == "1d",
                    MarketCandle.source == SOURCE,
                )
            )
            retrieved_at = utcnow()
            for bar in bars:
                db.add(
                    MarketCandle(
                        instrument_id=instrument.id,
                        interval="1d",
                        timestamp=bar["timestamp"],
                        open=bar["open"],
                        high=bar["high"],
                        low=bar["low"],
                        close=bar["close"],
                        volume=bar["volume"],
                        source=SOURCE,
                        retrieved_at=retrieved_at,
                    )
                )
            await db.commit()
            total_rows += len(bars)
            print(f"  {symbol}: {len(bars)} bars cached")

        print(f"Done. {total_rows} candle rows cached across {len(symbols)} symbols.")


if __name__ == "__main__":
    asyncio.run(main())
