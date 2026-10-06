"""Parse, store and load the NSE holiday list (equity segment `CM`) into the calendar."""

from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import MarketHoliday
from app.portfolio_intelligence.market import calendar as cal
from app.utils.time import utcnow


def parse_holidays(payload) -> dict[date, str]:
    """NSE `holiday-master?type=trading` JSON -> {date: description} for the CM segment. Rows with an unparseable date are skipped; the whole
    payload is rejected (None of the rows trusted) if the CM list is missing or empty, since an empty calendar is indistinguishable from a bad answer."""
    if not isinstance(payload, dict) or not isinstance(payload.get("CM"), list) or not payload["CM"]:
        raise ValueError("NSE holiday payload has no CM list")
    out: dict[date, str] = {}
    for r in payload["CM"]:
        try:
            d = datetime.strptime(str(r["tradingDate"]).strip(), "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        out[d] = " ".join(str(r.get("description") or "holiday").split()).rstrip("*").strip()
    if not out:
        raise ValueError("NSE holiday payload had no usable dates")
    return out


async def store_holidays(db: AsyncSession, holidays: dict[date, str], now: datetime | None = None) -> dict:
    """Replace the stored holidays of the YEARS the new payload covers (so a corrected list removes a withdrawn holiday); other years are untouched."""
    now = now or utcnow()
    years = {d.year for d in holidays}
    for row in (await db.execute(select(MarketHoliday))).scalars():
        if row.trade_date.year in years and row.trade_date not in holidays:
            await db.delete(row)
    existing = {r.trade_date: r for r in (await db.execute(select(MarketHoliday))).scalars()}
    for d, text in holidays.items():
        r = existing.get(d)
        if r is None:
            db.add(MarketHoliday(trade_date=d, description=text, fetched_at=now))
        else:
            r.description, r.fetched_at = text, now
    await db.commit()
    await load_calendar(db)
    return {"stored": len(holidays), "years": sorted(years)}


async def load_calendar(db: AsyncSession) -> dict:
    rows = {r.trade_date: r.description for r in (await db.execute(select(MarketHoliday))).scalars()}
    cal.set_holidays(rows)
    return cal.coverage()


async def refresh_holidays(db: AsyncSession, fetch=None) -> dict:
    from app.portfolio_intelligence.catalogue import sources

    payload = await (fetch or sources.fetch_holidays)()
    return await store_holidays(db, parse_holidays(payload))


_last_load: float = 0.0


async def ensure_fresh(db: AsyncSession, max_age_seconds: float = 300.0) -> None:
    """Reload the calendar from the database if it has not been loaded for a while. The worker stores holidays; the API process would otherwise only
    see them after its next restart or scheduler tick."""
    import time

    global _last_load
    if time.monotonic() - _last_load > max_age_seconds:
        _last_load = time.monotonic()
        await load_calendar(db)
