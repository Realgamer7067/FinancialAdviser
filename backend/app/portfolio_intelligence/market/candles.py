"""Daily candle parsing, storage and incremental refresh rules.

Refresh rule (the source can RE-ADJUST all history after a split/bonus, so appending alone would leave a
series stitched from two adjustment bases): fetch from a few days before the last stored date; if the
overlapping closes still match, append the new days; if they differ, the source re-based its history, so
replace the whole series."""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import CandleSync, SecurityCandle
from app.utils.time import utcnow

HISTORY_DAYS = 5 * 365
OVERLAP_DAYS = 7
REBASE_TOLERANCE = Decimal("0.005")  # a stored close differing from the re-fetched one by more than 0.5%: history was re-based


def _dec(v) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def parse_candles(raw: list) -> tuple[list[dict], int]:
    """[[ts, o, h, l, c, v], ...] -> ascending unique-by-date dicts, plus the number of rows rejected. A row with
    a non-positive price, high < low, or a close outside [low, high] is rejected, never repaired."""
    out: dict[date, dict] = {}
    bad = 0
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) < 5 or not isinstance(r[0], str):
            bad += 1
            continue
        try:
            d = datetime.fromisoformat(r[0]).date()
        except ValueError:
            bad += 1
            continue
        o, h, lo, c = (_dec(x) for x in r[1:5])
        v = _dec(r[5]) if len(r) > 5 else None
        if None in (o, h, lo, c) or min(o, h, lo, c) <= 0 or h < lo or not (lo <= c <= h) or (v is not None and v < 0):
            bad += 1
            continue
        out[d] = {"trade_date": d, "open": o, "high": h, "low": lo, "close": c, "volume": int(v) if v is not None else None}
    return [out[d] for d in sorted(out)], bad


def expected_last_session(now: datetime) -> date:
    """Most recent trading day whose close is final (16:00 IST). Uses the exchange holiday calendar for the years it covers and weekdays for any
    other (see market/calendar.py), so a holiday no longer looks like a session whose candle is "missing"."""
    from app.portfolio_intelligence.market import calendar as cal
    from app.portfolio_intelligence.sources.angel.token_store import IST

    ist = now.astimezone(IST)
    return cal.previous_session(ist.date(), inclusive=ist.hour >= 16)


async def stored_range(db: AsyncSession, security_id) -> tuple[date | None, date | None, int]:
    row = (await db.execute(select(func.min(SecurityCandle.trade_date), func.max(SecurityCandle.trade_date), func.count())
                            .where(SecurityCandle.security_id == security_id))).one()
    return row[0], row[1], row[2]


async def apply_fetch(db: AsyncSession, security_id, fetched: list[dict], *, today: date, now: datetime | None = None,
                      refetch_full=None) -> dict:
    """Store `fetched` (parsed, ascending) for one security, given that it was requested from
    last_date - OVERLAP (or from the start if nothing is stored). `refetch_full` is an async callable returning a
    full-history parsed list, used only when the overlap shows the source re-based history."""
    now = now or utcnow()
    first, last, n = await stored_range(db, security_id)
    rebased = False
    if n and fetched:
        stored = {c.trade_date: c.close for c in (await db.execute(select(SecurityCandle).where(
            SecurityCandle.security_id == security_id, SecurityCandle.trade_date >= last - timedelta(days=OVERLAP_DAYS)))).scalars()}
        for row in fetched:
            old = stored.get(row["trade_date"])
            if old is not None and abs(row["close"] - old) / old > REBASE_TOLERANCE:
                rebased = True
                break
    if rebased:
        fetched = await refetch_full() if refetch_full else fetched
        await db.execute(delete(SecurityCandle).where(SecurityCandle.security_id == security_id))
        existing: set[date] = set()
    else:
        existing = {d for (d,) in (await db.execute(select(SecurityCandle.trade_date).where(SecurityCandle.security_id == security_id))).all()}
    added = 0
    for row in fetched:
        if row["trade_date"] in existing:
            continue
        db.add(SecurityCandle(security_id=security_id, **row))
        added += 1
    await db.flush()
    first, last, n = await stored_range(db, security_id)
    sync = await db.get(CandleSync, security_id)
    if sync is None:
        sync = CandleSync(security_id=security_id, fetched_at=now, row_count=0, full_refetches=0)
        db.add(sync)
    sync.first_date, sync.last_date, sync.row_count, sync.fetched_at, sync.last_error = first, last, n, now, None
    if rebased:
        sync.full_refetches = (sync.full_refetches or 0) + 1
    return {"added": added, "rebased": rebased, "rows": n}


async def mark_sync_error(db: AsyncSession, security_id, message: str, now: datetime | None = None) -> None:
    sync = await db.get(CandleSync, security_id)
    if sync is None:
        sync = CandleSync(security_id=security_id, row_count=0, full_refetches=0, fetched_at=now or utcnow())
        db.add(sync)
    sync.last_error, sync.fetched_at = message[:200], now or utcnow()
