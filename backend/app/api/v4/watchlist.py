"""Watchlists and Angel One market data (read-only).

Better than a plain price list because every row is shown in the context of the
owner's OWN portfolio and limits (what they already hold, room before their
concentration limits, confirmed restrictions, any thesis), alerts become
deduplicated inbox items instead of notification spam, and prices are always
dated (live / delayed / last session). There are no buy/sell signals, target
prices or order buttons anywhere."""

import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.risk import twin_positions
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.theses import Thesis, ThesisAssessment
from app.models.watchlist import BrokerInstrument, MarketQuote, WatchAlert, Watchlist, WatchlistItem
from app.portfolio_intelligence.decisions import engine
from app.portfolio_intelligence.decisions.inbox import clear_external
from app.portfolio_intelligence.market import alerts as alerts_mod
from app.portfolio_intelligence.market import master as master_mod
from app.portfolio_intelligence.market import quotes as quotes_mod
from app.portfolio_intelligence.market.context import build_context
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AngelError, AuthExpired
from app.portfolio_intelligence.sources.angel.token_store import load_session
from app.portfolio_intelligence.state.build import active_preferences, latest_state, latest_valuation
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-watchlist"])

MAX_LISTS, MAX_ITEMS, MAX_ALERTS_PER_ITEM = 10, 100, 5
MIN_REFRESH_SECONDS = 10
_last_refresh: dict[str, float] = {}


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")


# --- instrument master & search ---------------------------------------------------------------

@router.get("/market/status")
async def market_status(db: AsyncSession = Depends(get_db)):
    from app.portfolio_intelligence.market import holidays as hol

    await hol.ensure_fresh(db)
    sess = load_session()
    n = (await db.execute(select(func.count()).select_from(BrokerInstrument))).scalar_one()
    return {**quotes_mod.market_status(), "broker_session": "connected" if sess else "not_connected",
            "session_expires_at": sess.expires_at.isoformat() if sess else None, "instrument_master_rows": n,
            "data_source": "Angel One SmartAPI (read-only)"}


@router.post("/market/instrument-master/refresh")
async def refresh_master(db: AsyncSession = Depends(get_db)):
    """Download Angel's public instrument master and (re)build the NSE equity list. No credentials involved."""
    try:
        rows = await master_mod.download_master()
    except Exception as exc:  # noqa: BLE001 -- network failure is a clean 503, never a crash
        raise HTTPException(503, f"could not download the instrument master: {type(exc).__name__}")
    parsed = master_mod.parse_master(rows)
    if not parsed:
        raise HTTPException(502, "the instrument master had no NSE equity rows; nothing was changed")
    return await master_mod.upsert_master(db, parsed)


@router.get("/market/search")
async def search(q: str, db: AsyncSession = Depends(get_db)):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, "type at least 2 characters")
    like = f"%{q}%"
    rows = (await db.execute(select(BrokerInstrument).where(
        or_(BrokerInstrument.symbol.ilike(like), BrokerInstrument.name.ilike(like))).order_by(BrokerInstrument.symbol).limit(20))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(BrokerInstrument))).scalar_one()
    return {"needs_master": total == 0, "results": [
        {"broker_instrument_id": str(b.id), "symbol": b.symbol, "name": b.name, "exchange": b.exchange, "in_universe": b.instrument_id is not None}
        for b in rows]}


# --- watchlists ----------------------------------------------------------------------------------

class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ItemIn(BaseModel):
    broker_instrument_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)
    why_watching: str | None = Field(default=None, max_length=300)


class ItemUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=300)
    why_watching: str | None = Field(default=None, max_length=300)


class AlertIn(BaseModel):
    kind: Literal["price_above", "price_below", "day_move_up", "day_move_down"]
    threshold: Decimal


async def _owned_list(db: AsyncSession, list_id: uuid.UUID) -> Watchlist:
    wl = (await db.execute(select(Watchlist).where(Watchlist.id == list_id, Watchlist.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if wl is None:
        raise HTTPException(404, "watchlist not found")
    return wl


async def _owned_item(db: AsyncSession, item_id: uuid.UUID) -> WatchlistItem:
    row = (await db.execute(select(WatchlistItem).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                            .where(WatchlistItem.id == item_id, Watchlist.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "watchlist item not found")
    return row


async def _portfolio_facts(db: AsyncSession) -> dict:
    state = await latest_state(db, SINGLE_USER_ID)
    val = None if state is None else await latest_valuation(db, state.id)
    holdings: dict = {}
    sector_values: dict = {}
    total = Decimal(0)
    if state is not None and val is not None:
        for p in await twin_positions(db, state, val):
            if p["value"] is None:
                continue
            total += p["value"]
            if p["asset_type"] == "listed_equity" and p["resolution"] == "resolved" and p["instrument_id"]:
                h = holdings.setdefault(p["instrument_id"], {"value": Decimal(0), "accounts": set()})
                h["value"] += p["value"]
                h["accounts"].add(p["account_label"])
                if p.get("sector"):
                    sector_values[p["sector"]] = sector_values.get(p["sector"], Decimal(0)) + p["value"]
    restrictions = [{"kind": r.kind, "value": r.value} for r in await active_preferences(db, SINGLE_USER_ID)]
    theses: dict = {}
    latest_thesis: dict = {}
    for t in (await db.execute(select(Thesis).where(Thesis.user_id == SINGLE_USER_ID).order_by(Thesis.chain_id, Thesis.version.desc()))).scalars():
        latest_thesis.setdefault(t.chain_id, t)
    for chain, t in latest_thesis.items():
        if t.status != "active":
            continue
        a = (await db.execute(select(ThesisAssessment).where(ThesisAssessment.thesis_chain_id == chain)
                              .order_by(ThesisAssessment.created_at.desc()).limit(1))).scalar_one_or_none()
        theses[str(t.instrument_id)] = {"chain_id": str(chain), "status": None if a is None else a.status}
    return {"holdings": holdings, "sector_values": sector_values, "total": total, "restrictions": restrictions, "theses": theses}


def _quote_out(q: MarketQuote | None, now: datetime) -> dict | None:
    if q is None:
        return None
    pos52 = None
    if q.week52_high is not None and q.week52_low is not None and q.week52_high > q.week52_low:
        pos52 = max(0.0, min(1.0, float((q.ltp - q.week52_low) / (q.week52_high - q.week52_low))))
    return {"ltp": _s(q.ltp), "prev_close": _s(q.prev_close), "day_change_pct": _s(q.percent_change), "high": _s(q.high), "low": _s(q.low),
            "week52_high": _s(q.week52_high), "week52_low": _s(q.week52_low), "position_in_52w_range": pos52,
            "retrieved_at": q.retrieved_at.isoformat(), "exchange_time": q.exchange_time.isoformat() if q.exchange_time else None,
            "freshness": quotes_mod.quote_freshness(q.retrieved_at, now)}


@router.get("/watchlists")
async def list_watchlists(db: AsyncSession = Depends(get_db)):
    now = utcnow()
    facts = await _portfolio_facts(db)
    limits = {k: engine.POLICY[k] for k in ("max_single_issuer_weight", "max_sector_weight")}
    lists = (await db.execute(select(Watchlist).where(Watchlist.user_id == SINGLE_USER_ID).order_by(Watchlist.created_at))).scalars().all()
    from app.models.market import Instrument

    out = []
    for wl in lists:
        rows = (await db.execute(select(WatchlistItem, BrokerInstrument, MarketQuote).join(BrokerInstrument, BrokerInstrument.id == WatchlistItem.broker_instrument_id)
                                 .outerjoin(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id)
                                 .where(WatchlistItem.watchlist_id == wl.id).order_by(WatchlistItem.added_at))).all()
        items = []
        for it, bi, q in rows:
            inst = await db.get(Instrument, bi.instrument_id) if bi.instrument_id else None
            alerts = (await db.execute(select(WatchAlert).where(WatchAlert.item_id == it.id).order_by(WatchAlert.created_at))).scalars().all()
            ctx = build_context(symbol=bi.symbol, instrument_id=None if bi.instrument_id is None else str(bi.instrument_id),
                                sector=inst.sector if inst else None, isin=inst.isin if inst else None, holdings=facts["holdings"],
                                total=facts["total"], sector_values=facts["sector_values"], restrictions=facts["restrictions"],
                                thesis=facts["theses"].get(str(bi.instrument_id)) if bi.instrument_id else None, limits=limits)
            ctx["accounts"] = list(ctx["accounts"])
            items.append({"item_id": str(it.id), "broker_instrument_id": str(bi.id), "security_id": None if bi.security_id is None else str(bi.security_id), "symbol": bi.symbol, "name": bi.name, "note": it.note,
                          "why_watching": it.why_watching, "added_at": it.added_at.isoformat(), "instrument_id": None if bi.instrument_id is None else str(bi.instrument_id),
                          "quote": _quote_out(q, now), "context": ctx,
                          "alerts": [{"id": str(a.id), "kind": a.kind, "threshold": _s(a.threshold), "triggered": a.triggered,
                                      "text": alerts_mod.describe(a.kind, a.threshold)} for a in alerts]})
        out.append({"id": str(wl.id), "name": wl.name, "items": items})
    return {"lists": out, "market": quotes_mod.market_status(now), "broker_session": "connected" if load_session() else "not_connected",
            "context_basis": "your latest portfolio snapshot and limits; facts only, never a recommendation"}


@router.post("/watchlists", status_code=201)
async def create_watchlist(payload: NameIn, db: AsyncSession = Depends(get_db)):
    n = (await db.execute(select(func.count()).select_from(Watchlist).where(Watchlist.user_id == SINGLE_USER_ID))).scalar_one()
    if n >= MAX_LISTS:
        raise HTTPException(422, f"at most {MAX_LISTS} watchlists")
    wl = Watchlist(user_id=SINGLE_USER_ID, name=payload.name.strip(), created_at=utcnow())
    db.add(wl)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "a watchlist with this name already exists")
    return {"id": str(wl.id), "name": wl.name, "items": []}


@router.put("/watchlists/{list_id}")
async def rename_watchlist(list_id: uuid.UUID, payload: NameIn, db: AsyncSession = Depends(get_db)):
    wl = await _owned_list(db, list_id)
    wl.name = payload.name.strip()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "a watchlist with this name already exists")
    return {"id": str(wl.id), "name": wl.name}


async def _delete_item(db: AsyncSession, item: WatchlistItem) -> None:
    now = utcnow()
    for a in (await db.execute(select(WatchAlert).where(WatchAlert.item_id == item.id))).scalars().all():
        await clear_external(db, SINGLE_USER_ID, f"watch_alert:{a.id}", now)  # the inbox item resolves with the alert
        await db.delete(a)
    await db.flush()  # no ORM relationships here: children must be gone before their parent is deleted (Postgres enforces it)
    await db.delete(item)
    await db.flush()


@router.delete("/watchlists/{list_id}", status_code=204)
async def delete_watchlist(list_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wl = await _owned_list(db, list_id)
    for it in (await db.execute(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id))).scalars().all():
        await _delete_item(db, it)
    await db.delete(wl)
    await db.commit()


@router.post("/watchlists/{list_id}/items", status_code=201)
async def add_item(list_id: uuid.UUID, payload: ItemIn, db: AsyncSession = Depends(get_db)):
    wl = await _owned_list(db, list_id)
    bi = await db.get(BrokerInstrument, payload.broker_instrument_id)
    if bi is None:
        raise HTTPException(422, "unknown instrument; search the instrument list first")
    total = (await db.execute(select(func.count()).select_from(WatchlistItem).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                              .where(Watchlist.user_id == SINGLE_USER_ID))).scalar_one()
    if total >= MAX_ITEMS:
        raise HTTPException(422, f"at most {MAX_ITEMS} watched stocks")
    it = WatchlistItem(watchlist_id=wl.id, broker_instrument_id=bi.id, note=payload.note, why_watching=payload.why_watching, added_at=utcnow())
    db.add(it)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "already on this watchlist")
    return {"item_id": str(it.id), "symbol": bi.symbol}


@router.put("/watchlists/items/{item_id}")
async def update_item(item_id: uuid.UUID, payload: ItemUpdate, db: AsyncSession = Depends(get_db)):
    it = await _owned_item(db, item_id)
    it.note, it.why_watching = payload.note, payload.why_watching
    await db.commit()
    return {"item_id": str(it.id), "note": it.note, "why_watching": it.why_watching}


@router.delete("/watchlists/items/{item_id}", status_code=204)
async def remove_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _delete_item(db, await _owned_item(db, item_id))
    await db.commit()


@router.post("/watchlists/items/{item_id}/alerts", status_code=201)
async def add_alert(item_id: uuid.UUID, payload: AlertIn, db: AsyncSession = Depends(get_db)):
    it = await _owned_item(db, item_id)
    if not payload.threshold.is_finite() or payload.threshold <= 0:
        raise HTTPException(422, "threshold must be a positive number")
    if payload.kind.startswith("day_move") and payload.threshold > 50:
        raise HTTPException(422, "a daily move threshold is a percentage up to 50")
    n = (await db.execute(select(func.count()).select_from(WatchAlert).where(WatchAlert.item_id == it.id))).scalar_one()
    if n >= MAX_ALERTS_PER_ITEM:
        raise HTTPException(422, f"at most {MAX_ALERTS_PER_ITEM} alerts per stock")
    a = WatchAlert(item_id=it.id, kind=payload.kind, threshold=payload.threshold, active=True, triggered=False, created_at=utcnow())
    db.add(a)
    await db.commit()
    await alerts_mod.evaluate_alerts(db, SINGLE_USER_ID, utcnow())  # may trigger immediately from the last known quote
    await db.refresh(a)
    return {"id": str(a.id), "kind": a.kind, "threshold": _s(a.threshold), "triggered": a.triggered, "text": alerts_mod.describe(a.kind, a.threshold)}


@router.delete("/watchlists/alerts/{alert_id}", status_code=204)
async def remove_alert(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(WatchAlert).join(WatchlistItem, WatchlistItem.id == WatchAlert.item_id)
                          .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                          .where(WatchAlert.id == alert_id, Watchlist.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "alert not found")
    await clear_external(db, SINGLE_USER_ID, f"watch_alert:{a.id}", utcnow())
    await db.delete(a)
    await db.commit()


# --- quote refresh ---------------------------------------------------------------------------------

async def _make_client() -> AngelClient:
    sess = load_session()
    if sess is None:
        raise AuthExpired("no valid Angel session")
    return AngelClient(jwt=sess.jwt)


def get_client_factory():
    """Overridable in tests; returns an async callable producing a connected read-only client."""
    return _make_client


@router.post("/watchlist/refresh")
async def refresh_prices(force: bool = False, db: AsyncSession = Depends(get_db), make_client=Depends(get_client_factory)):
    """Fetch the latest quotes for everything on a watchlist from Angel (batched, rate-limited). With no valid
    broker session the last saved quotes stay, clearly dated. Coalesced: at most one real fetch per 10 seconds."""
    now = utcnow()
    key = str(SINGLE_USER_ID)
    if not force and time.monotonic() - _last_refresh.get(key, -1e9) < MIN_REFRESH_SECONDS:
        return {"throttled": True, "refreshed": 0, "note": "prices were refreshed a moment ago"}
    ids = [r for (r,) in (await db.execute(select(WatchlistItem.broker_instrument_id).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                                           .where(Watchlist.user_id == SINGLE_USER_ID).distinct())).all()]
    if not ids:
        return {"throttled": False, "refreshed": 0, "requested": 0, "unfetched": [], "unparsed": []}
    try:
        client = await make_client()
    except AuthExpired:
        raise HTTPException(409, {"message": "reconnect_required: the Angel session ended; showing the last saved prices",
                                  "instructions": "Run in your own terminal: python -m app.portfolio_intelligence.sources.angel.setup connect"})
    try:
        stats = await quotes_mod.refresh_quotes(db, ids, client, now=now)
    except AuthExpired:
        raise HTTPException(409, {"message": "reconnect_required: the Angel session ended; showing the last saved prices"})
    except AngelError as exc:
        raise HTTPException(503 if exc.code in ("UNAVAILABLE", "RATE_LIMITED") else 502, f"{exc.code}: could not refresh prices ({exc})")
    finally:
        await client.aclose()
    _last_refresh[key] = time.monotonic()
    alert_stats = await alerts_mod.evaluate_alerts(db, SINGLE_USER_ID, now)
    return {"throttled": False, **stats, "alerts": alert_stats}
