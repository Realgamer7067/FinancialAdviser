"""12-1 and 6-1 month momentum from stored, audited, split/bonus-adjusted history, on TOTAL return where dividends could be applied.

12-1 = value[t-21] / value[t-252] - 1 and 6-1 = value[t-21] / value[t-126] - 1, where t is the newest session. The most recent month is skipped
on purpose (the standard way to avoid short-term reversal). Needs 253 sessions of history; anything less gives None, never a shorter window."""

import asyncio
import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import CorporateAction, SecurityCandle
from app.portfolio_intelligence.market import total_return as tr_mod

SKIP, LONG, SHORT = 21, 252, 126
MIN_SESSIONS = LONG + 1


def momentum_from_series(values: list[float]) -> tuple[float | None, float | None]:
    n = len(values)
    if n < MIN_SESSIONS:
        return None, None
    t = n - 1
    skip = values[t - SKIP]
    long_, short_ = values[t - LONG], values[t - SHORT]
    return (skip / long_ - 1.0 if long_ > 0 else None), (skip / short_ - 1.0 if short_ > 0 else None)


REGIME_LONG, REGIME_SHORT = 504, 21          # two years and one month of sessions


def momentum_regime(closes: list[float]) -> dict:
    """The market state in which momentum has crashed (Daniel and Moskowitz): a market that is down over the past two years and is now rebounding.
    DISPLAY ONLY: nothing in the ranking or the plan changes with it. `closes` are ascending market closes (a Nifty 50 index ETF)."""
    if len(closes) < REGIME_LONG + 1 or closes[-1 - REGIME_LONG] <= 0 or closes[-1 - REGIME_SHORT] <= 0:
        return {"state": "unknown", "market_2y": None, "market_1m": None,
                "note": "Not enough market history to tell whether this is a state in which momentum has crashed."}
    two_y, one_m = closes[-1] / closes[-1 - REGIME_LONG] - 1.0, closes[-1] / closes[-1 - REGIME_SHORT] - 1.0
    if two_y < 0 and one_m > 0:
        state, note = "elevated", ("The market is down over two years but rebounding. Momentum strategies have had their worst losses in exactly this state, so the momentum part of the score is "
                                   "less reliable now. The score is not changed.")
    elif two_y < 0:
        state, note = "watch", "The market is down over two years. If it rebounds sharply, momentum can lose heavily. The score is not changed."
    else:
        state, note = "normal", "The market is not in the two-year-decline state where momentum has historically crashed. That lowers the risk, it does not remove it."
    return {"state": state, "market_2y": two_y, "market_1m": one_m, "note": note}


def trailing_dividends(events: list[dict], scaled: list[dict], last: date) -> tuple[float | None, bool]:
    """-> (cash dividends per share with an ex-date in the 365 days to `last`, in today's share terms; whether that total can be trusted).
    A dividend in the window that was skipped (amount unparsed, or its split/bonus scaling uncertain) makes the total UNRELIABLE, never silently lower.
    No dividend in the window is a real zero only when the dividend feed reaches the window start, which the caller checks via history length."""
    start = last - timedelta(days=365)
    window = [e for e in events if e["kind"] == "dividend" and start < e["ex_date"] <= last]
    kept = {d["ex_date"] for d in scaled}
    if any(e.get("needs_review") or e.get("amount") is None or e["ex_date"] not in kept for e in window):
        return None, False
    return float(sum(d["amount"] for d in scaled if start < d["ex_date"] <= last)), True


async def _tr_series(db: AsyncSession, securities: list) -> dict[uuid.UUID, dict]:
    """{security id: {"dates": [...], "tr": [floats], "basis", "applied"}} from stored adjusted candles plus dividends (the same preparation the study uses)."""
    if not securities:
        return {}
    ids = [s.id for s in securities]
    symbols = {s.symbol for s in securities if s.symbol}
    events: dict[str, list[dict]] = defaultdict(list)
    for a in (await db.execute(select(CorporateAction).where(CorporateAction.symbol.in_(symbols), (CorporateAction.price_factor.is_not(None)) | (CorporateAction.needs_review.is_(True)) | (CorporateAction.kind == "dividend")))).scalars():
        events[a.symbol].append({"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review, "amount": a.amount})
    data: dict = defaultdict(list)
    for sid, d, o, h, lo, c, v in (await db.execute(select(SecurityCandle.security_id, SecurityCandle.trade_date, SecurityCandle.open, SecurityCandle.high, SecurityCandle.low, SecurityCandle.close,
                                                          SecurityCandle.volume).where(SecurityCandle.security_id.in_(ids)).order_by(SecurityCandle.security_id, SecurityCandle.trade_date))).all():
        data[sid].append({"trade_date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v})

    def build():
        out = {}
        for s in securities:
            rows = data.get(s.id)
            if not rows:
                continue
            prep = tr_mod.prepare(rows, events.get(s.symbol or "", []))
            dates = [r["trade_date"] for r in prep["rows"]]
            dps, reliable = trailing_dividends(events.get(s.symbol or "", []), prep.get("scaled", []), dates[-1])
            out[s.id] = {"dates": dates, "tr": [float(x) for x in prep["tr"]], "basis": "total_return" if prep["applied"] > 0 else "price", "applied": prep["applied"],
                         "dps_ttm": dps, "dps_reliable": reliable}
        return out

    return await asyncio.to_thread(build)


async def tr_series_for(db: AsyncSession, securities: list) -> dict[uuid.UUID, dict]:
    return await _tr_series(db, securities)


async def momentum_for(db: AsyncSession, securities: list) -> dict[uuid.UUID, dict]:
    """{security id: {mom_12_1, mom_6_1, basis, as_of, dividends_applied}}; basis is "total_return" when at least one dividend was applied, else "price"
    (with no dividend to add the two series are identical)."""
    series = await _tr_series(db, securities)
    out = {}
    for sid, x in series.items():
        m12, m6 = momentum_from_series(x["tr"])
        out[sid] = {"mom_12_1": m12, "mom_6_1": m6, "basis": x["basis"], "as_of": x["dates"][-1].isoformat() if x["dates"] else None, "dividends_applied": x["applied"],
                  "dps_ttm": x["dps_ttm"], "dps_reliable": x["dps_reliable"]}
    return out
