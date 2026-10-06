"""Angel One instrument master -> `broker_instruments` (NSE cash equities only).

The master is a public JSON file (no credentials, so it is not fetched through
the broker client and its allowlist). Rows carry no ISIN, so the match to our
canonical `instruments` is by symbol on the NSE EQ series and is labelled
`symbol_series_match`; unmatched rows are still stored so ANY NSE stock can be
watched (just without sector context)."""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Instrument
from app.models.watchlist import BrokerInstrument
from app.utils.time import utcnow

logger = logging.getLogger("angel_master")

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
ALLOWED_MASTER_HOSTS = {"margincalculator.angelbroking.com"}
MAX_MASTER_BYTES = 80_000_000


def parse_master(rows: list) -> list[dict]:
    """Keep NSE cash-equity rows (series EQ). Tolerant: malformed rows are skipped, never guessed."""
    out = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict) or r.get("exch_seg") != "NSE":
            continue
        ts = str(r.get("symbol") or "").strip()
        token = str(r.get("token") or "").strip()
        if not ts.endswith("-EQ") or not token or token in seen:
            continue
        itype = str(r.get("instrumenttype") or "").strip()
        if itype not in ("", "EQ"):  # derivatives/indices carry an instrument type
            continue
        try:
            lot = int(float(r.get("lotsize") or 1))
        except (TypeError, ValueError):
            lot = 1
        try:
            tick = Decimal(str(r.get("tick_size"))) / 100 if r.get("tick_size") not in (None, "") else None  # master reports paise
        except InvalidOperation:
            tick = None
        seen.add(token)
        out.append({"token": token, "trading_symbol": ts, "symbol": ts[:-3], "name": str(r.get("name") or ts[:-3]).strip(),
                    "lot_size": max(lot, 1), "tick_size": tick})
    return out


async def upsert_master(db: AsyncSession, parsed: list[dict], now: datetime | None = None) -> dict:
    now = now or utcnow()
    instruments = {i.symbol.upper(): i for i in (await db.execute(select(Instrument))).scalars()}
    existing = {b.token: b for b in (await db.execute(select(BrokerInstrument).where(
        BrokerInstrument.provider == "angel_one", BrokerInstrument.exchange == "NSE"))).scalars()}
    added = updated = matched = 0
    for p in parsed:
        inst = instruments.get(p["symbol"].upper())
        row = existing.get(p["token"])
        if row is None:
            row = BrokerInstrument(provider="angel_one", exchange="NSE", token=p["token"], series="EQ")
            db.add(row)
            added += 1
        else:
            updated += 1
        row.trading_symbol, row.symbol, row.name = p["trading_symbol"], p["symbol"], p["name"]
        row.lot_size, row.tick_size, row.seen_at = p["lot_size"], p["tick_size"], now
        row.instrument_id = inst.id if inst else None
        row.match_basis = "symbol_series_match" if inst else None
        matched += 1 if inst else 0
    await db.commit()
    return {"rows": len(parsed), "added": added, "updated": updated, "matched_to_universe": matched}


async def download_master(client: httpx.AsyncClient | None = None) -> list:
    url = MASTER_URL
    if urlparse(url).hostname not in ALLOWED_MASTER_HOSTS:
        raise RuntimeError("master host not allowlisted")
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False, trust_env=False)
    try:
        r = await client.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_MASTER_BYTES:
            raise RuntimeError("instrument master is unexpectedly large")
        data = r.json()
        if not isinstance(data, list):
            raise RuntimeError("instrument master is not a list")
        return data
    finally:
        if own:
            await client.aclose()
