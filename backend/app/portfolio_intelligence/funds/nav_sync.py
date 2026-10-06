"""Store verified fund NAV histories as daily rows (open=high=low=close=NAV) in the same candle tables as stocks, so the signals, suggestions and
re-base protection all work on funds unchanged. Only GROWTH-option, active schemes are ever fetched."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import CandleSync, Security
from app.portfolio_intelligence.funds import nav_source as N
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

logger = logging.getLogger("fund_nav")
POLITE_SECONDS = 1.0
DEFAULT_LIMIT = 40


async def target_funds(db: AsyncSession, held_isins: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> list[Security]:
    """Active Growth funds worth having a history for: the SIP list (direct Nifty 50 index funds) plus any held fund."""
    from app.portfolio_intelligence.allocation.select import fund_alternatives

    names = {f["scheme_code"] for f in await fund_alternatives(db)}
    stmt = select(Security).where(Security.kind == "mutual_fund", Security.is_active.is_(True), Security.option == "growth")
    conds = [Security.scheme_code.in_(sorted(names))] if names else []
    if held_isins:
        conds.append(Security.isin.in_(held_isins))
    if not conds:
        return []
    return list((await db.execute(stmt.where(or_(*conds)).order_by(Security.scheme_code).limit(limit))).scalars())


async def sync_fund(db: AsyncSession, c: httpx.AsyncClient, sec: Security, *, today, now: datetime, sleep=None) -> dict:
    kw = {"sleep": sleep} if sleep else {}
    if sec.option != "growth":
        return {"status": "skipped", "reason": "only Growth options have a return series"}
    try:
        data = await N.fetch_scheme(c, sec.scheme_code, **kw)
    except N.NavError as exc:
        await candles_mod.mark_sync_error(db, sec.id, f"mfapi: {exc}", now)
        await db.commit()
        return {"status": "error", "reason": str(exc)}
    rows, bad = N.parse_history(data["data"])
    meta_isin = (data["meta"].get("isin_growth") or "").upper()
    reason = (None if len(rows) >= 30 else "fewer than 30 NAV points") or N.sane(rows)
    verdict, detail = ("rejected", reason) if reason else N.verify_against_amfi(rows, sec.nav, sec.nav_date, meta_isin, sec.isin)
    if verdict == "deferred":      # not a failure: mfapi is simply behind AMFI. Nothing is stored; the next run tries again.
        await candles_mod.mark_sync_error(db, sec.id, f"deferred: {detail}", now)
        await db.commit()
        return {"status": "deferred", "reason": detail}
    if verdict == "rejected":
        await candles_mod.mark_sync_error(db, sec.id, f"rejected: {detail}", now)
        await db.commit()
        return {"status": "rejected", "reason": detail}

    async def full():
        return rows

    first, last, n = await candles_mod.stored_range(db, sec.id)
    new = rows if not n else [r for r in rows if r["trade_date"] >= (last - __import__("datetime").timedelta(days=candles_mod.OVERLAP_DAYS))]
    res = await candles_mod.apply_fetch(db, sec.id, new, today=today, now=now, refetch_full=full)
    await db.commit()
    return {"status": "stored", "rows": res["rows"], "added": res["added"], "rebased": res["rebased"], "rejected_points": bad, "verified_via": verdict}


async def sync_all(db: AsyncSession, funds: list[Security], *, now: datetime, client: httpx.AsyncClient | None = None, sleep=None) -> dict:
    import asyncio

    own = client is None
    client = client or N.client()
    today = now.astimezone(IST).date()
    out = {"stored": 0, "rejected": {}, "deferred": {}, "errors": {}, "skipped": 0}
    try:
        for i, f in enumerate(funds):
            r = await sync_fund(db, client, f, today=today, now=now, sleep=sleep)
            if r["status"] == "stored":
                out["stored"] += 1
            elif r["status"] == "rejected":
                out["rejected"][f.scheme_code] = r["reason"]
            elif r["status"] == "deferred":
                out["deferred"][f.scheme_code] = r["reason"]
            elif r["status"] == "error":
                out["errors"][f.scheme_code] = r["reason"]
            else:
                out["skipped"] += 1
            if i + 1 < len(funds):
                await (sleep or asyncio.sleep)(POLITE_SECONDS)
    finally:
        if own:
            await client.aclose()
    return out


async def held_fund_isins(db: AsyncSession) -> list[str]:
    from app.api.v4.risk import twin_positions
    from app.core.single_user import SINGLE_USER_ID
    from app.portfolio_intelligence.state.build import latest_state, latest_valuation

    state = await latest_state(db, SINGLE_USER_ID)
    valuation = await latest_valuation(db, state.id) if state else None
    if not (state and valuation):
        return []
    return sorted({(p.get("isin") or "").upper() for p in await twin_positions(db, state, valuation) if p["asset_type"] == "mutual_fund" and p.get("isin")})
