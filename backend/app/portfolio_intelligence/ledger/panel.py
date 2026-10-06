"""Load the stored, audited, split/bonus-adjusted daily history of stocks into wide date x security frames for the study."""

import asyncio
from collections import defaultdict

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle
from app.portfolio_intelligence.market import total_return as tr_mod
from app.portfolio_intelligence.ledger import registry as R

CHUNK = 120


async def load_panel(db: AsyncSession) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """-> (close, volume, total_return, meta). `close` is the split/bonus-adjusted PRICE; `total_return` adds scaled cash dividends (market/total_return.py). Stocks only (ETFs are scored separately), at least WARMUP sessions of history. Adjusted per event exactly as
    the signals do. `meta` carries the data marker used to key the stored study."""
    sec = (await db.execute(select(Security.id, Security.symbol, CandleSync.row_count, CandleSync.last_date, CandleSync.full_refetches).join(CandleSync, CandleSync.security_id == Security.id)
                            .where(Security.kind == "stock", Security.is_active.is_(True), CandleSync.row_count >= R.WARMUP_SESSIONS).order_by(Security.id))).all()
    events: dict[str, list[dict]] = defaultdict(list)
    for a in (await db.execute(select(CorporateAction).where((CorporateAction.price_factor.is_not(None)) | (CorporateAction.needs_review.is_(True)) | (CorporateAction.kind == "dividend")))).scalars():
        events[a.symbol].append({"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review, "amount": a.amount})
    closes, vols, trs = {}, {}, {}
    totals = {"dividends_applied": 0, "needs_review": 0, "uncertain_scaling": 0, "outside_range": 0}
    for i in range(0, len(sec), CHUNK):
        part = sec[i : i + CHUNK]
        data: dict = defaultdict(list)
        for sid, d, o, h, lo, c, v in (await db.execute(select(SecurityCandle.security_id, SecurityCandle.trade_date, SecurityCandle.open, SecurityCandle.high, SecurityCandle.low,
                                                              SecurityCandle.close, SecurityCandle.volume).where(SecurityCandle.security_id.in_([p[0] for p in part]))
                                                       .order_by(SecurityCandle.security_id, SecurityCandle.trade_date))).all():
            data[sid].append({"trade_date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v})

        def build(part=part, data=data):
            out = []
            for sid, symbol, *_ in part:
                rows = data.get(sid)
                if not rows:
                    continue
                prep = tr_mod.prepare(rows, events.get(symbol or "", []))
                adj = prep["rows"]
                idx = pd.to_datetime([r["trade_date"] for r in adj])
                out.append((sid, pd.Series([float(r["close"]) for r in adj], index=idx), pd.Series([float(r["volume"] or 0) for r in adj], index=idx),
                            pd.Series([float(x) for x in prep["tr"]], index=idx), prep))
            return out

        for sid, c, v, t, prep in await asyncio.to_thread(build):
            closes[str(sid)], vols[str(sid)], trs[str(sid)] = c, v, t
            totals["dividends_applied"] += prep["applied"]
            for k, n in prep["skipped"].items():
                totals[k] += n
    close = pd.DataFrame(closes).sort_index()
    volume = pd.DataFrame(vols).reindex(close.index)
    total_return = pd.DataFrame(trs).reindex(close.index)
    last = max((s[3] for s in sec if s[3]), default=None)
    meta = {"securities": len(closes), "sessions": len(close), "first": close.index[0].date().isoformat() if len(close) else None, "last": close.index[-1].date().isoformat() if len(close) else None,
            "data_marker": f"{len(closes)}:{len(close)}:{last}:{sum((s[4] or 0) for s in sec)}:{tr_mod.TR_METHOD}", "dividends": totals}
    return close, volume, total_return, meta
