"""Nightly Kronos forecasts for a SHORTLIST, stored point-in-time and counted for nothing.

Why a shortlist and why weight 0: a CPU forecast costs about 30 s, so ~2,600 stocks are out of reach, and tests on this
data showed the model's output is strongly biased upward (random walks with zero drift came back +4% to +29%), with
published directional accuracy near a coin flip. The honest use is to STORE each forecast with its inputs so a later
scoring ledger can measure, against realized prices, whether it has any skill. Until then it is displayed, not counted.

Strict mode: model, weights or package failures raise and are reported by type; they are never turned into a silent
"no signal"."""

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle, SecurityForecast, SecuritySignal
from app.models.watchlist import BrokerInstrument, WatchlistItem
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.portfolio_intelligence.market import adjust as adjust_mod
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.signals import compute as sig
from app.utils.time import utcnow

logger = logging.getLogger("kronos_job")
KIND = "kronos_forecast"
CHUNK = 4                 # ~30 s each on CPU: about 120 s per job, inside the 300 s lease
MAX_BARS = 400            # Kronos-small context is 512; a little under it
MIN_BARS = 200
SHORTLIST_MAX = 90


def model_version() -> str:
    from app.models_iface.kronos import KronosModel

    return KronosModel()._model_version


async def shortlist(db: AsyncSession) -> list:
    """Watched securities, the Nifty 50 (securities linked to the legacy `instruments` table), and the most liquid ETF
    per underlying (there are dozens of near-identical Nifty and gold ETFs; forecasting all 351 is waste)."""
    ids: dict = {}
    for (sid,) in (await db.execute(select(BrokerInstrument.security_id).join(WatchlistItem, WatchlistItem.broker_instrument_id == BrokerInstrument.id)
                                    .where(BrokerInstrument.security_id.is_not(None)))).all():
        ids[sid] = 0
    for (sid,) in (await db.execute(select(Security.id).where(Security.is_active.is_(True), Security.instrument_id.is_not(None), Security.kind == "stock"))).all():
        ids.setdefault(sid, 1)
    etfs = (await db.execute(select(Security.id, Security.category, SecuritySignal.liquidity_value, SecuritySignal.as_of_date)
                             .join(SecuritySignal, SecuritySignal.security_id == Security.id)
                             .where(Security.is_active.is_(True), Security.kind == "etf", SecuritySignal.quality == "ok", SecuritySignal.liquidity_value.is_not(None))
                             .order_by(SecuritySignal.as_of_date.desc()))).all()
    best: dict = {}
    seen = set()
    for sid, cat, liq, _d in etfs:
        if sid in seen:
            continue  # newest row per ETF only
        seen.add(sid)
        key = cat or str(sid)
        if key not in best or float(liq) > best[key][1]:
            best[key] = (sid, float(liq))
    for sid, _ in best.values():
        ids.setdefault(sid, 2)
    ordered = sorted(ids, key=lambda s: (ids[s], str(s)))
    return ordered[:SHORTLIST_MAX]


async def pending(db: AsyncSession, now: datetime, version: str, horizon: str) -> list[tuple]:
    """[(security_id, symbol, as_of_date, rows, full_refetches)] on the shortlist with fresh enough history and no
    forecast yet for their newest candle date."""
    expected = candles_mod.expected_last_session(now)
    out = []
    for sid in await shortlist(db):
        row = (await db.execute(select(Security.symbol, CandleSync.last_date, CandleSync.row_count, CandleSync.full_refetches)
                                .join(CandleSync, CandleSync.security_id == Security.id).where(Security.id == sid))).first()
        if row is None or row[1] is None or (row[2] or 0) < MIN_BARS or (expected - row[1]).days > sig.STALE_DAYS:
            continue
        done = (await db.execute(select(SecurityForecast.security_id).where(SecurityForecast.security_id == sid, SecurityForecast.as_of_date == row[1],
                                                                              SecurityForecast.model_version == version, SecurityForecast.horizon == horizon))).first()
        if done is None:
            out.append((sid, row[0], row[1], row[2], row[3] or 0))
    return out


async def _candles(db: AsyncSession, sid, symbol: str):
    from app.providers.base import Candle

    rows = [{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
            for r in (await db.execute(select(SecurityCandle).where(SecurityCandle.security_id == sid).order_by(SecurityCandle.trade_date))).scalars()]
    events = [{"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review}
              for a in (await db.execute(select(CorporateAction).where(CorporateAction.symbol == symbol))).scalars()] if symbol else []
    adj = adjust_mod.adjust_series(rows, events) if events else {"rows": rows, "unreliable": []}
    now = utcnow()
    return [Candle(timestamp=datetime(r["trade_date"].year, r["trade_date"].month, r["trade_date"].day, tzinfo=timezone.utc), open=float(r["open"]), high=float(r["high"]),
                   low=float(r["low"]), close=float(r["close"]), volume=int(r["volume"] or 0), source="angel_one", retrieved_at=now, adjusted=True)
            for r in adj["rows"][-MAX_BARS:]], adj["unreliable"]


async def run_forecasts(db: AsyncSession, now: datetime, model=None, limit: int = CHUNK) -> dict:
    from app.models_iface.kronos import KronosModel

    model = model or KronosModel()
    horizon = settings.signals_kronos_horizon
    version = model._model_version
    todo = await pending(db, now, version, horizon)
    res = {"done": 0, "errors": [], "remaining_after": 0, "model_version": version, "horizon": horizon}
    for sid, symbol, as_of, rows, refetches in todo[:limit]:
        candles, unreliable = await _candles(db, sid, symbol)
        try:
            f = await model.forecast_strict(symbol or str(sid), candles, horizon)
        except Exception as exc:  # noqa: BLE001 -- reported by type, never swallowed into "no signal"
            res["errors"].append({"symbol": symbol, "error": type(exc).__name__, "message": str(exc)[:120]})
            continue
        if f is None:
            res["errors"].append({"symbol": symbol, "error": "NoForecast", "message": "unknown horizon or too little history"})
            continue
        db.add(SecurityForecast(
            security_id=sid, as_of_date=as_of, model_version=version, horizon=horizon, origin="live", computed_at=now,
            input_marker=f"{refetches}:{rows}:{as_of}:{candles[-1].close:.4f}", bars_used=len(candles), sample_count=f.sample_count,
            predicted_return=f.predicted_return, p10=f.predicted_return_p10, p90=f.predicted_return_p90, direction=f.direction,
            direction_agreement=f.direction_agreement, calibrated_confidence=None,
            detail={"calibration": "none: no calibration table for this data, so the number is not a probability", "last_close": candles[-1].close,
                    "unreliable_dates": [u["date"].isoformat() for u in unreliable], "counts_toward_checks": False}))
        await db.commit()
        res["done"] += 1
    res["remaining_after"] = max(0, len(todo) - res["done"] - len(res["errors"])) if len(todo) > limit else 0
    return res


async def enqueue_forecasts(db: AsyncSession, key: str, now: datetime | None = None, exclude_job_id: uuid.UUID | None = None):
    if not settings.signals_kronos_enabled:
        return None
    return await enqueue_unique(db, KIND, key, now=now, exclude_job_id=exclude_job_id)


async def process_forecast_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail

    summary, code = None, None
    try:
        async with AsyncSessionLocal() as db:
            now = utcnow()
            summary = await run_forecasts(db, now)
            if summary["remaining_after"] and summary["done"]:
                await enqueue_forecasts(db, "continue", now, exclude_job_id=job_id)
    except Exception as exc:  # noqa: BLE001 -- model/weights/package problem: reported, not swallowed
        logger.exception("kronos job %s failed", job_id)
        code = "INTERNAL"
        message = f"{type(exc).__name__}: {str(exc)[:160]}"
    if code:
        await _fail(job_id, token, code, message, None)
        return
    if summary["errors"] and not summary["done"]:
        # nothing worked this round: surface it (retries are bounded) instead of reporting success
        await finish_job(AsyncSessionLocal, job_id, token, summary, complete=False)
        await _fail(job_id, token, "UNAVAILABLE", f"every forecast in this chunk failed: {summary['errors'][0]['error']}", None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("kronos chunk done: %s", {k: v for k, v in summary.items() if k != "errors"} | {"errors": len(summary["errors"])})
