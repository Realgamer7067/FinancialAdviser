"""Securities catalogue (read-only): browse every stock, ETF and mutual fund scheme we know of.

Reference data from public files plus the latest dated price we hold. Nothing here recommends anything:
suggestions come from the decision engine, never from a list endpoint. Prices are shown with their own
as-of time; a security with no quote simply has none (never a stale zero)."""

import asyncio
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle, SecurityForecast, SecuritySignal, SecurityTer
from app.models.watchlist import BrokerInstrument, MarketQuote
from app.portfolio_intelligence.catalogue.jobs import KIND, enqueue_refresh
from app.portfolio_intelligence.market import adjust as adjust_mod
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.market import jobs as market_jobs
from app.portfolio_intelligence.market import quotes as quotes_mod
from app.portfolio_intelligence.signals import compute as sig_mod
from app.portfolio_intelligence.signals import jobs as sig_jobs
from app.portfolio_intelligence.market.quotes import quote_freshness
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AngelError, AuthExpired
from app.portfolio_intelligence.sources.angel.token_store import load_session
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4/catalogue", tags=["v4-catalogue"])

SORTS = {"name": Security.name, "symbol": Security.symbol, "sector": Security.sector,
         "change": MarketQuote.percent_change, "volume": MarketQuote.volume, "price": MarketQuote.ltp,
         "momentum": SecuritySignal.mom_12_1_rank, "volatility": SecuritySignal.vol_252, "drawdown": SecuritySignal.drawdown_current, "ter": SecurityTer.ter}
QUOTE_SORTS = {"change", "volume", "price", "momentum", "volatility", "drawdown", "ter"}  # nulls always last
MAX_QUOTE_IDS = 50                 # one broker request
MIN_API_QUOTE_INTERVAL = 3.0       # seconds between API-driven broker calls, across all callers (the worker does bulk work)
_quote_lock = asyncio.Lock()
_last_quote_call = 0.0


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")


def _f(v) -> float | None:
    return None if v is None else float(v)


def _signals_brief(g: SecuritySignal | None) -> dict | None:
    if g is None:
        return None
    return {"as_of": g.as_of_date.isoformat(), "quality": g.quality, "trend_state": g.trend_state, "mom_12_1_rank": _f(g.mom_12_1_rank),
            "vol_252": _f(g.vol_252), "drawdown_current": _f(g.drawdown_current), "liquidity": sig_mod.liquidity_flag(_f(g.liquidity_value))}


def _latest_signals():
    """Subquery: each security's newest stored signal date for the current method."""
    return (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d"))
            .where(SecuritySignal.method_version == sig_mod.METHOD_VERSION).group_by(SecuritySignal.security_id).subquery())


def _row(s: Security, bi: BrokerInstrument | None, q: MarketQuote | None, g: SecuritySignal | None = None) -> dict:
    out = {"id": str(s.id), "kind": s.kind, "symbol": s.symbol, "isin": s.isin, "name": s.name, "sector": s.sector, "asset_class": s.asset_class,
           "category": s.category, "series": s.series, "is_active": s.is_active, "tradable_in_angel": bi is not None,
           "broker_instrument_id": str(bi.id) if bi else None, "instrument_id": str(s.instrument_id) if s.instrument_id else None}
    if g is not None:
        out["signals"] = _signals_brief(g)
    if s.kind == "mutual_fund":
        out.update(scheme_code=s.scheme_code, amc=s.amc, plan=s.plan, option=s.option, nav=_s(s.nav), nav_date=s.nav_date.isoformat() if s.nav_date else None)
    elif q is not None:
        out.update(price={"ltp": _s(q.ltp), "prev_close": _s(q.prev_close), "percent_change": _s(q.percent_change), "week52_high": _s(q.week52_high),
                          "week52_low": _s(q.week52_low), "volume": q.volume, "as_of": q.retrieved_at.isoformat(),
                          "exchange_time": q.exchange_time.isoformat() if q.exchange_time else None, "freshness": quote_freshness(q.retrieved_at)})
    return out


async def _attach_ter(db: AsyncSession, items: list[dict]) -> None:
    """Expense ratio for funds and ETFs, ONLY where a defensible match exists; otherwise the field stays absent (unknown, never zero)."""
    ids = [uuid.UUID(i["id"]) for i in items if i["kind"] in ("mutual_fund", "etf")]
    if not ids:
        return
    got = {t.security_id: t for t in (await db.execute(select(SecurityTer).where(SecurityTer.security_id.in_(ids)))).scalars()}
    for i in items:
        t = got.get(uuid.UUID(i["id"])) if i["kind"] in ("mutual_fund", "etf") else None
        if t is not None:
            i["ter"] = {"percent": _s(t.ter), "plan": t.plan_used, "as_of": t.ter_date.isoformat(), "scheme": t.scheme_name, "source": "AMFI total expense ratio"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)   # SQLite returns naive datetimes; Postgres aware


def _relevance(q: str):
    """Exact symbol first, then symbol prefix, then name prefix, then any other match: 'reliance' must put
    RELIANCE above 'Reliance Chemotex'."""
    t = q.strip().lower().replace("%", "").replace("_", "")
    sym, name = func.lower(func.coalesce(Security.symbol, "")), func.lower(Security.name)
    return case((sym == t, 0), (sym.like(f"{t}%"), 1), (name.like(f"{t}%"), 2), else_=3)


def _order(sort: str, order: str, q: str | None = None):
    col = SORTS[sort]
    col = col.desc() if order == "desc" else col.asc()
    if sort in QUOTE_SORTS:
        return (col.nulls_last(),)
    return ((_relevance(q), col) if q and q.strip() and sort in ("name", "symbol") and order == "asc" else (col,))


@router.get("/securities")
async def list_securities(
    q: str | None = Query(None, max_length=60), kind: Literal["stock", "etf", "mutual_fund"] | None = None, sector: str | None = Query(None, max_length=80),
    asset_class: str | None = Query(None, max_length=30), category: str | None = Query(None, max_length=100),
    plan: Literal["direct", "regular"] | None = None, option: Literal["growth", "idcw"] | None = None,
    trend: Literal["above", "below"] | None = None,
    include_inactive: bool = False,
    sort: Literal["name", "symbol", "sector", "change", "volume", "price", "momentum", "volatility", "drawdown", "ter"] = "name",
    order: Literal["asc", "desc"] = "asc", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
):
    conds = []
    if not include_inactive:
        conds.append(Security.is_active.is_(True))
    for col, val in ((Security.kind, kind), (Security.sector, sector), (Security.asset_class, asset_class), (Security.category, category), (Security.plan, plan), (Security.option, option),
                     (SecuritySignal.trend_state, trend)):
        if val is not None:
            conds.append(col == val)
    if q and q.strip():
        like = f"%{q.strip().lower().replace('%', '').replace('_', '')}%"
        conds.append(or_(func.lower(Security.name).like(like), func.lower(func.coalesce(Security.symbol, "")).like(like), func.lower(func.coalesce(Security.isin, "")).like(like)))
    latest = _latest_signals()
    sig_join = and_(SecuritySignal.security_id == Security.id, SecuritySignal.as_of_date == latest.c.d, SecuritySignal.method_version == sig_mod.METHOD_VERSION)
    total = (await db.execute(select(func.count()).select_from(Security).outerjoin(latest, latest.c.sid == Security.id).outerjoin(SecuritySignal, sig_join).where(*conds))).scalar_one()
    stmt = (select(Security, BrokerInstrument, MarketQuote, SecuritySignal).outerjoin(BrokerInstrument, BrokerInstrument.security_id == Security.id)
            .outerjoin(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id).outerjoin(latest, latest.c.sid == Security.id).outerjoin(SecuritySignal, sig_join)
            .outerjoin(SecurityTer, SecurityTer.security_id == Security.id)
            .where(*conds).order_by(*_order(sort, order, q), Security.id).limit(limit).offset(offset))
    rows = (await db.execute(stmt)).all()
    items = [_row(s, bi, qt, g) for s, bi, qt, g in rows]
    await _attach_ter(db, items)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/facets")
async def facets(db: AsyncSession = Depends(get_db)):
    async def count_by(col, *where):
        rows = (await db.execute(select(col, func.count()).where(Security.is_active.is_(True), *where).group_by(col).order_by(func.count().desc()))).all()
        return [{"value": v, "count": n} for v, n in rows if v]

    kinds = {k: n for k, n in (await db.execute(select(Security.kind, func.count()).where(Security.is_active.is_(True)).group_by(Security.kind))).all()}
    return {"kinds": kinds, "sectors": await count_by(Security.sector, Security.kind == "stock"),
            "asset_classes": await count_by(Security.asset_class),
            "fund_categories": await count_by(Security.category, Security.kind == "mutual_fund"),
            "unclassified_stocks": (await db.execute(select(func.count()).select_from(Security).where(
                Security.is_active.is_(True), Security.kind == "stock", Security.sector.is_(None)))).scalar_one()}


@router.get("/securities/{security_id}")
async def get_security(security_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(Security, BrokerInstrument, MarketQuote).outerjoin(BrokerInstrument, BrokerInstrument.security_id == Security.id)
                            .outerjoin(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id).where(Security.id == security_id))).first()
    if row is None:
        raise HTTPException(404, "security not found")
    s, bi, qt = row
    actions = []
    if s.symbol and s.kind in ("stock", "etf"):
        actions = (await db.execute(select(CorporateAction).where(CorporateAction.symbol == s.symbol).order_by(CorporateAction.ex_date.desc()).limit(20))).scalars().all()
    base = _row(s, bi, qt)
    await _attach_ter(db, [base])
    return {**base, "face_value": _s(s.face_value), "lot_size": s.lot_size, "listing_date": s.listing_date.isoformat() if s.listing_date else None,
            "isin_reinvest": s.isin_reinvest, "source": s.source, "seen_at": s.seen_at.isoformat(),
            "corporate_actions": [{"ex_date": a.ex_date.isoformat(), "kind": a.kind, "subject": a.subject, "amount": _s(a.amount),
                                   "price_factor": _s(a.price_factor), "needs_review": a.needs_review} for a in actions]}


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db)):
    counts = {k: n for k, n in (await db.execute(select(Security.kind, func.count()).group_by(Security.kind))).all()}
    newest = (await db.execute(select(func.max(Security.seen_at)))).scalar_one()
    newest_nav = (await db.execute(select(func.max(Security.nav_date)).where(Security.kind == "mutual_fund"))).scalar_one()
    last_action = (await db.execute(select(func.max(CorporateAction.fetched_at)))).scalar_one()
    job = (await db.execute(select(PortfolioJob).where(PortfolioJob.kind == KIND).order_by(PortfolioJob.created_at.desc()).limit(1))).scalar_one_or_none()
    return {"counts": counts, "securities_seen_at": newest.isoformat() if newest else None,
            "newest_fund_nav_date": newest_nav.isoformat() if newest_nav else None, "corporate_actions_fetched_at": last_action.isoformat() if last_action else None,
            "last_job": None if job is None else {"id": str(job.id), "status": job.status, "error_code": job.error_code, "error": job.error,
                                                  "created_at": job.created_at.isoformat(), "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                                                  "result": job.result}}


@router.post("/refresh", status_code=202)
async def refresh(db: AsyncSession = Depends(get_db)):
    """Queue a catalogue + corporate-actions refresh for the worker. 202 with already_queued=true when one is pending."""
    job = await enqueue_refresh(db, "manual", utcnow())
    return {"queued": job is not None, "already_queued": job is None, "job_id": str(job.id) if job else None}


@router.get("/movers")
async def movers(kind: Literal["stock", "etf"] = "stock", limit: int = Query(8, ge=1, le=25), min_volume: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    """Biggest gainers/losers and most traded among instruments with a saved quote. `min_volume` filters out
    thinly traded names that otherwise dominate a % change list."""
    base = (select(Security, BrokerInstrument, MarketQuote).join(BrokerInstrument, BrokerInstrument.security_id == Security.id)
            .join(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id)
            .where(Security.is_active.is_(True), Security.kind == kind, MarketQuote.percent_change.is_not(None), func.coalesce(MarketQuote.volume, 0) >= min_volume))

    async def top(col):
        return [_row(s, bi, qt) for s, bi, qt in (await db.execute(base.order_by(col.nulls_last(), Security.id).limit(limit))).all()]

    as_of = (await db.execute(select(func.max(MarketQuote.retrieved_at)))).scalar_one()
    return {"as_of": as_of.isoformat() if as_of else None, "gainers": await top(MarketQuote.percent_change.desc()),
            "losers": await top(MarketQuote.percent_change.asc()), "most_traded": await top(MarketQuote.volume.desc())}


class QuoteRefresh(BaseModel):
    security_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_QUOTE_IDS)


@router.post("/quotes/refresh")
async def refresh_visible_quotes(body: QuoteRefresh, db: AsyncSession = Depends(get_db)):
    """Refresh the prices of the rows currently on screen (at most 50 = one broker request). Rate-limit economy:
    one broker call per 3 s across all callers, no call at all when the market is closed and the saved quotes are
    already from the last final session. Returns the rows either way, with `refreshed` saying what happened."""
    global _last_quote_call
    from app.portfolio_intelligence.market import holidays as hol

    await hol.ensure_fresh(db)
    ids = list(dict.fromkeys(body.security_ids))
    brokers = (await db.execute(select(BrokerInstrument).where(BrokerInstrument.security_id.in_(ids), BrokerInstrument.series == "EQ"))).scalars().all()
    quotes = {q.broker_instrument_id: q for q in (await db.execute(select(MarketQuote).where(MarketQuote.broker_instrument_id.in_([b.id for b in brokers] or [uuid.uuid4()])))).scalars()}
    now = utcnow()
    reason, refreshed = None, False
    status = quotes_mod.market_status(now)
    last_final = quotes_mod.last_close_time(now)
    stale = [b for b in brokers if b.id not in quotes or (status["open"] or _aware(quotes[b.id].retrieved_at) < last_final)]
    if not brokers:
        reason = "none of these are tradable in Angel One"
    elif not stale:
        reason = "market closed: prices are from the last session"
    elif load_session(now=now) is None:
        reason = "broker not connected: showing the last saved prices"
    else:
        async with _quote_lock:
            wait = MIN_API_QUOTE_INTERVAL - (time.monotonic() - _last_quote_call)
            if wait > 0:
                reason = "refreshed moments ago: showing saved prices"
            else:
                client = AngelClient(jwt=load_session(now=now).jwt)
                try:
                    _last_quote_call = time.monotonic()
                    await quotes_mod.refresh_quotes(db, [b.id for b in stale], client, mode="FULL", now=now)
                    refreshed = True
                except AuthExpired:
                    await db.rollback()
                    reason = "broker session expired: reconnect to refresh prices"
                except AngelError as exc:
                    await db.rollback()
                    reason = f"broker unavailable ({exc.code}): showing the last saved prices"
                finally:
                    await client.aclose()
    rows = (await db.execute(select(Security, BrokerInstrument, MarketQuote).outerjoin(BrokerInstrument, BrokerInstrument.security_id == Security.id)
                             .outerjoin(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id).where(Security.id.in_(ids)))).all()
    return {"refreshed": refreshed, "reason": reason, "items": [_row(s, bi, qt) for s, bi, qt in rows], "market": status}


async def _tradable(db: AsyncSession, security_id: uuid.UUID) -> tuple[Security, BrokerInstrument | None]:
    row = (await db.execute(select(Security, BrokerInstrument).outerjoin(BrokerInstrument, BrokerInstrument.security_id == Security.id)
                            .where(Security.id == security_id))).first()
    if row is None:
        raise HTTPException(404, "security not found")
    return row


@router.get("/securities/{security_id}/history")
async def history(security_id: uuid.UUID, days: int = Query(365, ge=30, le=1830), db: AsyncSession = Depends(get_db)):
    """Daily history with every corporate-action adjustment VERIFIED against the stored prices (see market/adjust.py):
    `adjustment.audit` says, per split/bonus, whether the source already adjusted it or we did, and
    `adjustment.unreliable` lists dates where returns/volatility should not be trusted."""
    s, bi = await _tradable(db, security_id)
    sync = await db.get(CandleSync, security_id)
    if s.kind == "mutual_fund" and (sync is None or not sync.row_count):
        queued = any(str(security_id) in ((j.params or {}).get("security_ids") or []) for j in (await db.execute(
            select(market_jobs.PortfolioJob).where(market_jobs.PortfolioJob.kind == "fund_nav_sync", market_jobs.PortfolioJob.status.in_(("queued", "running"))))).scalars())
        if queued:
            return {"status": "queued", "coverage": None, "candles": [], "adjustment": None}
        return {"status": "unsupported", "message": "NAV history is fetched only for the funds on the SIP list and the ones you hold; use Fetch NAV history to add this one", "candles": []}
    if s.kind not in ("stock", "etf", "mutual_fund"):
        return {"status": "unsupported", "message": "no price history is kept for this kind of security", "candles": []}
    pending = any((j.params or {}).get("security_ids") == [str(security_id)] for j in (await db.execute(
        select(market_jobs.PortfolioJob).where(market_jobs.PortfolioJob.kind == market_jobs.BACKFILL, market_jobs.PortfolioJob.status.in_(("queued", "running"))))).scalars())
    cov = None if sync is None else {"first_date": sync.first_date.isoformat() if sync.first_date else None, "last_date": sync.last_date.isoformat() if sync.last_date else None,
                                     "rows": sync.row_count, "fetched_at": sync.fetched_at.isoformat(), "last_error": sync.last_error, "full_refetches": sync.full_refetches}
    if sync is None or not sync.row_count:
        return {"status": "queued" if pending else "none", "tradable_in_angel": bi is not None, "coverage": cov, "candles": [], "adjustment": None}
    since = (sync.last_date or date.today()) - timedelta(days=days)
    rows = [{"trade_date": c.trade_date, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
            for c in (await db.execute(select(SecurityCandle).where(SecurityCandle.security_id == security_id, SecurityCandle.trade_date >= since)
                                       .order_by(SecurityCandle.trade_date))).scalars()]
    events = [{"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review, "subject": a.subject}
              for a in (await db.execute(select(CorporateAction).where(CorporateAction.symbol == s.symbol))).scalars()] if s.symbol else []
    adj = adjust_mod.adjust_series(rows, events)
    return {"status": "ready", "coverage": cov, "adjustment": {
                "applied": adj["applied"],
                "audit": [{"ex_date": a["ex_date"].isoformat(), "kind": a["kind"], "factor": _s(a["factor"]), "ratio": None if a["ratio"] is None else f"{a['ratio']:.4f}", "status": a["status"]} for a in adj["audit"]],
                "unreliable": [{"date": u["date"].isoformat(), "reason": u["reason"]} for u in adj["unreliable"]]},
            "candles": [{"d": r["trade_date"].isoformat(), "o": _s(r["open"]), "h": _s(r["high"]), "l": _s(r["low"]), "c": _s(r["close"]), "v": r["volume"]} for r in adj["rows"]]}


@router.post("/securities/{security_id}/history/sync", status_code=202)
async def sync_history(security_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Queue a candle fetch for ONE security (the worker does it). Used when a detail page finds no history."""
    s, bi = await _tradable(db, security_id)
    if s.kind not in ("stock", "etf") or bi is None:
        raise HTTPException(409, "history is only available for Angel-tradable stocks and ETFs")
    job = await market_jobs.enqueue_backfill(db, "ondemand", security_ids=[str(security_id)])
    return {"queued": job is not None, "already_queued": job is None}


@router.get("/market-jobs")
async def market_job_status(db: AsyncSession = Depends(get_db)):
    """Latest snapshot and backfill job, plus how much of the candle universe is covered."""
    out = {}
    for kind in (market_jobs.SNAPSHOT, market_jobs.BACKFILL):
        j = (await db.execute(select(market_jobs.PortfolioJob).where(market_jobs.PortfolioJob.kind == kind).order_by(market_jobs.PortfolioJob.created_at.desc()).limit(1))).scalar_one_or_none()
        out[kind] = None if j is None else {"status": j.status, "error_code": j.error_code, "created_at": j.created_at.isoformat(),
                                            "completed_at": j.completed_at.isoformat() if j.completed_at else None, "result": j.result}
    out["candle_securities"] = (await db.execute(select(func.count()).select_from(CandleSync).where(CandleSync.row_count > 0))).scalar_one()
    out["quotes"] = (await db.execute(select(func.count()).select_from(MarketQuote))).scalar_one()
    return out


@router.post("/market-jobs/refresh", status_code=202)
async def queue_market_jobs(db: AsyncSession = Depends(get_db)):
    """Queue a full-market price snapshot and the candle top-up for the worker (needs a connected broker session)."""
    if load_session() is None:
        raise HTTPException(409, "Angel One is not connected: reconnect first (see Holdings)")
    snap = await market_jobs.enqueue_snapshot(db, "manual")
    back = await market_jobs.enqueue_backfill(db, "manual")
    return {"snapshot": {"queued": snap is not None}, "backfill": {"queued": back is not None}}


@router.get("/securities/{security_id}/signals")
async def security_signals(security_id: uuid.UUID, history: int = Query(30, ge=1, le=250), db: AsyncSession = Depends(get_db)):
    """Latest stored signals plus their history, grouped into independent families. Descriptions of the past, never
    a forecast or a recommendation; the forecast family is shown but counts 0."""
    s, _bi = await _tradable(db, security_id)
    rows = (await db.execute(select(SecuritySignal).where(SecuritySignal.security_id == security_id, SecuritySignal.method_version == sig_mod.METHOD_VERSION)
                             .order_by(SecuritySignal.as_of_date.desc()).limit(history))).scalars().all()
    if not rows:
        return {"status": "none", "kind": s.kind, "message": "no signals stored yet" if s.kind != "mutual_fund" else "signals are computed for exchange-traded stocks and ETFs only", "latest": None, "history": []}
    g = rows[0]
    fc = (await db.execute(select(SecurityForecast).where(SecurityForecast.security_id == security_id).order_by(SecurityForecast.as_of_date.desc()).limit(1))).scalar_one_or_none()
    row = {"quality": g.quality, "trend_state": g.trend_state, "mom_12_1_rank": _f(g.mom_12_1_rank), "vol_252_rank": _f(g.vol_252_rank), "drawdown_current": _f(g.drawdown_current),
           "liquidity_value": _f(g.liquidity_value), "circuit_days_20": g.circuit_days_20}
    rel = None
    if fc is not None:
        peers = [float(x) for (x,) in (await db.execute(select(SecurityForecast.predicted_return).where(
            SecurityForecast.as_of_date == fc.as_of_date, SecurityForecast.model_version == fc.model_version, SecurityForecast.horizon == fc.horizon))).all()]
        if len(peers) >= 10:   # relative standing only means something against enough peers made on the same date
            below, equal = sum(p < float(fc.predicted_return) for p in peers), sum(p == float(fc.predicted_return) for p in peers)
            rel = round(100.0 * (below + 0.5 * equal) / len(peers), 1)
    forecast = None if fc is None else {"relative_rank": rel, "peers_on_date": len(peers) if fc is not None else 0,
                                        "bias_warning": "In our tests this model leaned strongly upward (even on random data), so the absolute number is not meaningful; only its standing against other forecasts made the same day is shown. It counts for nothing in any check yet.",
                                        "as_of": fc.as_of_date.isoformat(), "horizon": fc.horizon, "model_version": fc.model_version, "direction": fc.direction,
                                        "predicted_return": _f(fc.predicted_return), "p10": _f(fc.p10), "p90": _f(fc.p90), "direction_agreement": _f(fc.direction_agreement),
                                        "sample_count": fc.sample_count, "calibrated_confidence": _f(fc.calibrated_confidence), "counts_toward_checks": False}
    cols = ("sma200_ratio", "mom_12_1", "mom_6_1", "mom_12_1_rank", "vol_60", "vol_252", "vol_252_rank", "vol_ratio", "drawdown_current", "max_dd_1y", "week52_pos", "liquidity_value")
    return {"status": "ready", "kind": s.kind,
            "latest": {"as_of": g.as_of_date.isoformat(), "computed_at": g.computed_at.isoformat(), "method_version": g.method_version, "origin": g.origin, "quality": g.quality,
                       "universe": g.universe, "rank_universe_size": g.rank_universe_size, "history_len": g.history_len, "trend_state": g.trend_state,
                       "circuit_days_20": g.circuit_days_20, "detail": g.detail, **{c: _f(getattr(g, c)) for c in cols}},
            "families": sig_mod.summarize(row, forecast),
            "forecast": forecast,
            "history": [{"as_of": r.as_of_date.isoformat(), "quality": r.quality, "trend_state": r.trend_state, "mom_12_1_rank": _f(r.mom_12_1_rank), "vol_252": _f(r.vol_252),
                         "drawdown_current": _f(r.drawdown_current)} for r in rows],
            "note": "These describe past prices; they are not forecasts or recommendations."}


@router.post("/signals/refresh", status_code=202)
async def refresh_signals(db: AsyncSession = Depends(get_db)):
    job = await sig_jobs.enqueue_signals(db, "manual")
    return {"queued": job is not None, "already_queued": job is None}


@router.get("/signals/status")
async def signals_status(db: AsyncSession = Depends(get_db)):
    j = (await db.execute(select(market_jobs.PortfolioJob).where(market_jobs.PortfolioJob.kind == sig_jobs.COMPUTE).order_by(market_jobs.PortfolioJob.created_at.desc()).limit(1))).scalar_one_or_none()
    newest = (await db.execute(select(func.max(SecuritySignal.as_of_date)).where(SecuritySignal.method_version == sig_mod.METHOD_VERSION))).scalar_one()
    n = (await db.execute(select(func.count()).select_from(SecuritySignal).where(SecuritySignal.method_version == sig_mod.METHOD_VERSION))).scalar_one()
    return {"method_version": sig_mod.METHOD_VERSION, "policy_version": sig_mod.POLICY_VERSION, "stored_rows": n, "newest_as_of": newest.isoformat() if newest else None,
            "last_job": None if j is None else {"status": j.status, "error_code": j.error_code, "created_at": j.created_at.isoformat(),
                                                "completed_at": j.completed_at.isoformat() if j.completed_at else None, "result": j.result}}


@router.get("/ter/status")
async def ter_status(db: AsyncSession = Depends(get_db)):
    from app.models.securities import SchemeTer

    schemes = (await db.execute(select(func.count()).select_from(SchemeTer))).scalar_one()
    matched = {k: n for k, n in (await db.execute(select(Security.kind, func.count()).join(SecurityTer, SecurityTer.security_id == Security.id).group_by(Security.kind))).all()}
    totals = {k: n for k, n in (await db.execute(select(Security.kind, func.count()).where(Security.kind.in_(("mutual_fund", "etf")), Security.is_active.is_(True)).group_by(Security.kind))).all()}
    newest = (await db.execute(select(func.max(SchemeTer.fetched_at)))).scalar_one()
    j = (await db.execute(select(market_jobs.PortfolioJob).where(market_jobs.PortfolioJob.kind == "ter_refresh").order_by(market_jobs.PortfolioJob.created_at.desc()).limit(1))).scalar_one_or_none()
    return {"schemes_with_ter": schemes, "matched": matched, "active_total": totals, "fetched_at": newest.isoformat() if newest else None,
            "last_job": None if j is None else {"status": j.status, "error_code": j.error_code, "created_at": j.created_at.isoformat(), "result": j.result},
            "note": "A fund or ETF without a match has an UNKNOWN expense ratio (shown as unknown, never zero). Matching is by fund house plus exact normalized scheme name; ambiguous names match nothing."}


@router.post("/ter/refresh", status_code=202)
async def ter_refresh(db: AsyncSession = Depends(get_db)):
    from app.portfolio_intelligence.costs.jobs import enqueue_ter

    job = await enqueue_ter(db, "manual", now=utcnow())
    return {"queued": job is not None, "already_queued": job is None}


@router.post("/securities/{security_id}/nav-history/sync", status_code=202)
async def sync_nav_history(security_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Queue a verified NAV-history fetch for ONE Growth-option fund (the worker does it)."""
    from app.portfolio_intelligence.funds.jobs import enqueue_nav

    s, _ = await _tradable(db, security_id)
    if s.kind != "mutual_fund" or s.option != "growth":
        raise HTTPException(409, "NAV history is only fetched for Growth-option mutual funds (an IDCW NAV falls on every payout and is not a return series)")
    job = await enqueue_nav(db, "ondemand", params={"security_ids": [str(security_id)]})
    return {"queued": job is not None, "already_queued": job is None}


@router.post("/ter/rematch")
async def ter_rematch(db: AsyncSession = Depends(get_db)):
    """Re-run the matching rules over the STORED expense-ratio rows (no download): used after a rule is corrected."""
    from app.portfolio_intelligence.costs.ter_sync import match_all

    return await match_all(db, utcnow())
