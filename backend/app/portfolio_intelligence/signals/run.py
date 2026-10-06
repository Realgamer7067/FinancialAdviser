"""Nightly signal run: read stored history, audit/adjust, compute, rank against a fixed reference set, store
point-in-time rows (append-only) and measure how independent the signal families really are."""

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle, SecuritySignal
from app.portfolio_intelligence.market import adjust as adjust_mod
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.signals import compute as sig
from app.utils.time import utcnow

logger = logging.getLogger("signals")
CHUNK = 150


def input_marker(full_refetches: int, rows: int, last: date | None, last_close: float | None) -> str:
    """Changes whenever the stored inputs change (history re-based, new day, revised close), so a signal can later be
    told apart from one computed on different inputs."""
    return f"{full_refetches}:{rows}:{last}:{last_close:.4f}" if last_close is not None else f"{full_refetches}:{rows}:{last}:none"


async def _universe(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(Security.id, Security.kind, Security.symbol, Security.sector, CandleSync.row_count, CandleSync.full_refetches)
                             .join(CandleSync, CandleSync.security_id == Security.id)
                             .where(Security.is_active.is_(True), Security.kind.in_(("stock", "etf", "mutual_fund")), CandleSync.row_count > 0)
                             .order_by(Security.id))).all()
    return [{"id": r[0], "kind": r[1], "symbol": r[2], "sector": r[3], "rows": r[4], "full_refetches": r[5] or 0} for r in rows]


async def _events_by_symbol(db: AsyncSession) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for a in (await db.execute(select(CorporateAction).where((CorporateAction.price_factor.is_not(None)) | (CorporateAction.needs_review.is_(True))))).scalars():
        out[a.symbol].append({"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review})
    return out


async def _series(db: AsyncSession, ids: list) -> dict:
    data: dict = defaultdict(list)
    q = (select(SecurityCandle.security_id, SecurityCandle.trade_date, SecurityCandle.open, SecurityCandle.high, SecurityCandle.low,
                SecurityCandle.close, SecurityCandle.volume).where(SecurityCandle.security_id.in_(ids)).order_by(SecurityCandle.security_id, SecurityCandle.trade_date))
    for sid, d, o, h, lo, c, v in (await db.execute(q)).all():
        data[sid].append({"trade_date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return data


def _one(meta: dict, rows: list[dict], events: list[dict], expected: date) -> dict:
    adj = adjust_mod.adjust_series(rows, events) if events else {"rows": rows, "audit": [], "applied": 0, "unreliable": []}
    r = adj["rows"]
    m = sig.compute_metrics([x["trade_date"] for x in r], [float(x["close"]) for x in r], [float(x["high"]) for x in r], [float(x["low"]) for x in r],
                            [x["volume"] for x in r], expected_last_session=expected, unreliable_dates=[u["date"] for u in adj["unreliable"]])
    m["detail"] = {"reasons": m.pop("reasons"), "adjustments_applied": adj["applied"],
                   "audit": [{"ex_date": a["ex_date"].isoformat(), "kind": a["kind"], "status": a["status"]} for a in adj["audit"]],
                   "unreliable": [{"date": u["date"].isoformat(), "reason": u["reason"]} for u in adj["unreliable"]], "policy_version": sig.POLICY_VERSION}
    m["input_marker"] = input_marker(meta["full_refetches"], meta["rows"], m["last_candle_date"], float(rows[-1]["close"]) if rows else None)
    return {**meta, **m}


async def compute_all(db: AsyncSession, now: datetime) -> list[dict]:
    universe = await _universe(db)
    events = await _events_by_symbol(db)
    expected = candles_mod.expected_last_session(now)
    out: list[dict] = []
    for i in range(0, len(universe), CHUNK):
        part = universe[i : i + CHUNK]
        series = await _series(db, [m["id"] for m in part])
        results = await asyncio.to_thread(lambda: [_one(m, series.get(m["id"], []), events.get(m["symbol"] or "", []), expected) for m in part if series.get(m["id"])])
        out.extend(results)
    for kind in ("stock", "etf"):
        rows = [r for r in out if r["kind"] == kind]
        # reference set: clean, fresh, liquid and (for stocks) classified. Outside names are placed against it, never added to it.
        mask = [r["quality"] == "ok" and sig.liquidity_flag(r.get("liquidity_value")) == "ok" and (kind == "etf" or r["sector"] is not None) for r in rows]
        sig.rank_against_reference(rows, mask)
        for r in rows:
            r["universe"] = kind
    for r in out:
        if r["kind"] == "mutual_fund":      # a fund has no peers among stocks/ETFs and no traded volume: its measures are stored, but never ranked or liquidity-flagged
            r["universe"] = "fund"
            r["mom_12_1_rank"] = r["vol_252_rank"] = r["rank_universe_size"] = None
    return out


def independence(rows: list[dict]) -> dict:
    """Spearman correlation between the family measures across clean rows. |rho| above ~0.7 means two families are not
    independent evidence and must not be counted as two votes."""
    clean = [r for r in rows if r["quality"] == "ok" and r["kind"] == "stock"]
    if len(clean) < 30:
        return {"status": "insufficient_data", "n": len(clean)}
    df = pd.DataFrame({"trend_sma200": [r["sma200_ratio"] for r in clean], "momentum_12_1": [r["mom_12_1"] for r in clean],
                       "risk_vol_252": [r["vol_252"] for r in clean], "risk_drawdown": [r["drawdown_current"] for r in clean],
                       "liquidity": [np.log(r["liquidity_value"]) if r.get("liquidity_value") else np.nan for r in clean]}).dropna()
    corr = df.corr(method="spearman")
    pairs = {f"{a}~{b}": round(float(corr.loc[a, b]), 3) for i, a in enumerate(corr.columns) for b in corr.columns[i + 1:]}
    return {"status": "ready", "n": int(len(df)), "pairs": pairs, "above_0_7": sorted(k for k, v in pairs.items() if abs(v) > 0.7)}


async def store(db: AsyncSession, rows: list[dict], now: datetime) -> dict:
    """Insert-only: a (security, as_of, method) row that already exists is left exactly as it was."""
    existing = {(s, d) for s, d in (await db.execute(select(SecuritySignal.security_id, SecuritySignal.as_of_date).where(
        SecuritySignal.method_version == sig.METHOD_VERSION, SecuritySignal.security_id.in_([r["id"] for r in rows] or [None])))).all()}
    inserted = skipped = 0
    for r in rows:
        key = (r["id"], r["last_candle_date"])
        if key in existing:
            skipped += 1
            continue
        db.add(SecuritySignal(
            security_id=r["id"], as_of_date=r["last_candle_date"], method_version=sig.METHOD_VERSION, origin="live", computed_at=now,
            history_len=r["history_len"], input_marker=r["input_marker"], quality=r["quality"], universe=r["universe"],
            rank_universe_size=r.get("rank_universe_size"), sma200_ratio=r["sma200_ratio"], trend_state=r["trend_state"], mom_12_1=r["mom_12_1"],
            mom_6_1=r["mom_6_1"], mom_12_1_rank=r.get("mom_12_1_rank"), vol_60=r["vol_60"], vol_252=r["vol_252"], vol_252_rank=r.get("vol_252_rank"),
            vol_ratio=r["vol_ratio"], drawdown_current=r["drawdown_current"], max_dd_1y=r["max_dd_1y"], week52_pos=r["week52_pos"],
            liquidity_value=r["liquidity_value"], circuit_days_20=r["circuit_days_20"], detail=r["detail"]))
        inserted += 1
    await db.commit()
    return {"inserted": inserted, "skipped_existing": skipped}


async def run_signals(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = await compute_all(db, now)
    counts = defaultdict(int)
    for r in rows:
        counts[r["quality"]] += 1
    res = await store(db, rows, now)
    ref = {k: next((r["rank_universe_size"] for r in rows if r["kind"] == k and r.get("rank_universe_size")), 0) for k in ("stock", "etf")}
    return {"securities": len(rows), "quality": dict(counts), **res, "reference_sizes": ref, "independence": independence(rows),
            "method_version": sig.METHOD_VERSION, "policy_version": sig.POLICY_VERSION}
