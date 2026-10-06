"""Latest quotes from Angel One (read-only) and market-hours labelling.

Quotes are observations with their own times: `retrieved_at` always, and
`exchange_time` only when the payload carried a parseable one. A weekend or
after-hours quote is labelled as the last session, never "live"."""

from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.watchlist import BrokerInstrument, MarketQuote
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

OPEN, CLOSE = time(9, 15), time(15, 30)
LIVE_MAX_AGE_SECONDS = 120
_FORMATS = ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def market_status(now: datetime | None = None) -> dict:
    from app.portfolio_intelligence.market import calendar as cal

    ist = (now or utcnow()).astimezone(IST)
    day = ist.date()
    is_open = cal.is_trading_day(day) and OPEN <= ist.time() <= CLOSE
    holiday = cal.holiday_name(day)
    label = ("Market open (NSE, 09:15-15:30 IST)" if is_open else f"Market closed for {holiday}: prices are from the last session" if holiday else "Market closed: prices are from the last session")
    cov = cal.coverage()
    return {"open": is_open, "ist_time": ist.strftime("%a %H:%M"), "label": label, "holiday": holiday,
            "note": (f"NSE holidays are applied for {', '.join(map(str, cov['years_covered']))}." if cov["years_covered"] else "The NSE holiday calendar is not loaded; weekends only are treated as closed.")}


def last_close_time(now: datetime | None = None) -> datetime:
    """The most recent 15:30 IST weekday close at or before `now` (holidays not modeled)."""
    from datetime import timedelta

    ist = (now or utcnow()).astimezone(IST)
    from app.portfolio_intelligence.market import calendar as cal

    d = cal.previous_session(ist.date(), inclusive=ist.time() >= CLOSE)
    return datetime.combine(d, CLOSE, tzinfo=IST)


def quote_freshness(retrieved_at: datetime | None, now: datetime | None = None) -> str:
    """live | delayed | last_session | none"""
    if retrieved_at is None:
        return "none"
    now = now or utcnow()
    if market_status(now)["open"]:
        age = (now - retrieved_at.replace(tzinfo=retrieved_at.tzinfo or now.tzinfo)).total_seconds()
        return "live" if age <= LIVE_MAX_AGE_SECONDS else "delayed"
    return "last_session"


def _d(v) -> Decimal | None:
    if v is None or isinstance(v, bool) or v == "":
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _time(v) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    for f in _FORMATS:
        try:
            return datetime.strptime(v.strip(), f).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_quote(entry: dict) -> dict | None:
    """One `fetched` entry -> normalized fields, or None if it has no usable price (never a 0 price)."""
    if not isinstance(entry, dict):
        return None
    ltp = _d(entry.get("ltp"))
    if ltp is None or ltp <= 0:
        return None
    prev = _d(entry.get("close"))
    pct = _d(entry.get("percentChange"))
    if pct is None and prev:  # fall back to our own arithmetic
        pct = ((ltp / prev) - 1) * 100
    vol = _d(entry.get("tradeVolume"))
    return {"token": str(entry.get("symbolToken") or ""), "ltp": ltp, "prev_close": prev, "open": _d(entry.get("open")),
            "high": _d(entry.get("high")), "low": _d(entry.get("low")), "volume": int(vol) if vol is not None else None,
            "percent_change": pct, "week52_high": _d(entry.get("52WeekHigh", entry.get("52WeekHighPrice"))),  # live payload uses 52WeekHigh; docs say ...Price
            "week52_low": _d(entry.get("52WeekLow", entry.get("52WeekLowPrice"))),
            "exchange_time": _time(entry.get("exchTradeTime")) or _time(entry.get("exchFeedTime"))}


async def refresh_quotes(db: AsyncSession, broker_ids: list, client: AngelClient, *, mode: str = "FULL",
                         now: datetime | None = None) -> dict:
    now = now or utcnow()
    if not broker_ids:
        return {"requested": 0, "refreshed": 0, "unfetched": [], "unparsed": []}
    rows = (await db.execute(select(BrokerInstrument).where(BrokerInstrument.id.in_(broker_ids)))).scalars().all()
    by_token = {b.token: b for b in rows}
    result = await client.get_quotes({"NSE": sorted(by_token)}, mode=mode)
    existing = {q.broker_instrument_id: q for q in (await db.execute(
        select(MarketQuote).where(MarketQuote.broker_instrument_id.in_([b.id for b in rows])))).scalars()}
    refreshed, unparsed = 0, []
    for entry in result["fetched"]:
        parsed = parse_quote(entry)
        b = by_token.get(str((entry or {}).get("symbolToken") if isinstance(entry, dict) else ""))
        if parsed is None or b is None:
            unparsed.append(str((entry or {}).get("tradingSymbol") if isinstance(entry, dict) else "?"))
            continue
        q = existing.get(b.id)
        if q is None:
            q = MarketQuote(broker_instrument_id=b.id, ltp=parsed["ltp"], retrieved_at=now, mode=mode)
            db.add(q)
        for k in ("ltp", "prev_close", "open", "high", "low", "volume", "percent_change", "week52_high", "week52_low", "exchange_time"):
            setattr(q, k, parsed[k])
        q.retrieved_at, q.mode = now, mode
        refreshed += 1
    await db.commit()
    unfetched = [str(u.get("symbolToken") or u.get("tradingSymbol") or u) if isinstance(u, dict) else str(u) for u in result["unfetched"]]
    return {"requested": len(by_token), "refreshed": refreshed, "unfetched": unfetched, "unparsed": unparsed}
