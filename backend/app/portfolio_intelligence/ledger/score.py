"""Live scoring: join what was logged (signal rows, forecasts, observations, owner plan legs) to what prices did afterwards.

Point-in-time and insert-only:
- Entry = the first stored close AFTER the day the subject was known (signals: computed_at; observations: logged_at; plans: created_at).
- Exit = the close `horizon` sessions after entry. Scored ONLY once the full horizon exists in stored candles.
- A subject whose exit never arrives although the market has long passed it is recorded as `missing_exit`, never silently dropped.
- If the security's history was later re-based (candle_syncs.full_refetches changed), a NEW version row is written beside the old one.
- Verification and what-if plans are never scored (origin)."""

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import AllocationPlan, CandleSync, CorporateAction, LedgerOutcome, Security, SecurityCandle, SecurityForecast, SecuritySignal, SuggestionLog
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.market import total_return as tr_mod
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

OVERDUE_DAYS = 10   # a missing exit is declared only this long after it was due


def known_date(ts: datetime) -> date:
    from datetime import timezone

    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(IST).date()


def add_sessions(d: date, n: int) -> date:
    """Trading-day arithmetic using the exchange calendar where it applies: used only for 'expected by' dates, never for scoring."""
    from app.portfolio_intelligence.market import calendar as cal

    return cal.add_sessions(d, n)


def locate(dates: list[date], known: date, horizon: int) -> dict:
    """-> {state: ready, i, j} | {state: waiting, entry_idx?}. Entry is the first date strictly after `known`."""
    i = bisect_right(dates, known)
    if i >= len(dates):
        return {"state": "waiting"}
    j = i + horizon
    return {"state": "ready", "i": i, "j": j} if j < len(dates) else {"state": "waiting", "entry_idx": i}


async def _subjects(db: AsyncSession) -> list[dict]:
    out: list[dict] = []
    sig_claims = [c for c in R.LIVE_CLAIMS if c["source"] == "signal"]
    for g in (await db.execute(select(SecuritySignal).where(SecuritySignal.origin == "live", SecuritySignal.method_version == R.SIGNAL_METHOD, SecuritySignal.quality == "ok"))).scalars():
        for c in sig_claims:
            v = getattr(g, c["feature"])
            if v is not None:
                out.append({"claim": c, "type": "signal", "key": f"{g.security_id}:{g.as_of_date}", "security_id": g.security_id, "as_of": g.as_of_date, "known_at": g.computed_at,
                            "feature": Decimal(str(v)), "direction": None, "marker": g.input_marker})
    score_claim = next(c for c in R.LIVE_CLAIMS if c["source"] == "score")
    from app.models.securities import SecurityScore
    from app.portfolio_intelligence.scoring.checklist import CHECKLIST_VERSION

    for r in (await db.execute(select(SecurityScore).where(SecurityScore.method_version == CHECKLIST_VERSION, SecurityScore.score.is_not(None)))).scalars():
        out.append({"claim": score_claim, "type": "score", "key": f"{r.security_id}:{r.as_of_date}", "security_id": r.security_id, "as_of": r.as_of_date, "known_at": r.computed_at,
                    "feature": Decimal(str(r.score)), "direction": None, "marker": f"{CHECKLIST_VERSION}:{r.as_of_date}"})
    rank_claim = next(c for c in R.LIVE_CLAIMS if c["source"] == "rank")
    from app.portfolio_intelligence.scoring.ranking import RANK_VERSION

    for r in (await db.execute(select(SecurityScore).where(SecurityScore.method_version == RANK_VERSION, SecurityScore.score.is_not(None)))).scalars():
        out.append({"claim": rank_claim, "type": "rank", "key": f"{r.security_id}:{r.as_of_date}:rank", "security_id": r.security_id, "as_of": r.as_of_date, "known_at": r.computed_at,
                    "feature": Decimal(str(r.score)), "direction": None, "marker": f"{RANK_VERSION}:{r.as_of_date}"})
    fc = next(c for c in R.LIVE_CLAIMS if c["source"] == "forecast")
    for f in (await db.execute(select(SecurityForecast).where(SecurityForecast.origin == "live"))).scalars():
        out.append({"claim": fc, "type": "forecast", "key": f"{f.security_id}:{f.as_of_date}:{f.model_version}:{f.horizon}", "security_id": f.security_id, "as_of": f.as_of_date,
                    "known_at": f.computed_at, "feature": Decimal(str(f.predicted_return)), "direction": None, "marker": f.input_marker})
    sc = next(c for c in R.LIVE_CLAIMS if c["source"] == "suggestion")
    for s in (await db.execute(select(SuggestionLog).where(SuggestionLog.origin == "live", SuggestionLog.kind == sc["kind"], SuggestionLog.context.in_(sc["contexts"])))).scalars():
        out.append({"claim": sc, "type": "suggestion", "key": f"{s.fingerprint}:{s.trigger_date}", "security_id": s.security_id, "as_of": s.trigger_date, "known_at": s.logged_at,
                    "feature": None, "direction": sc["direction"], "marker": s.signal_input_marker})
    pc = next(c for c in R.LIVE_CLAIMS if c["source"] == "plan_leg")
    for p in (await db.execute(select(AllocationPlan).where(AllocationPlan.origin == "owner"))).scalars():
        for leg in p.result.get("legs", []):
            out.append({"claim": pc, "type": "plan_leg", "key": f"{p.id}:{leg['instrument_id']}", "security_id": uuid_of(leg["instrument_id"]), "as_of": p.created_at.date(), "known_at": p.created_at,
                        "feature": Decimal(leg["planned_debit"]), "direction": None, "marker": p.inputs_hash})
    return out


def uuid_of(s):
    import uuid

    return uuid.UUID(str(s))


async def _series(db: AsyncSession, cache: dict, sid):
    """-> (dates, split/bonus-adjusted prices, total-return index, flags). Same preparation as the study (market/total_return.py)."""
    if sid not in cache:
        symbol = (await db.execute(select(Security.symbol).where(Security.id == sid))).scalar_one_or_none()
        rows = [{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
                for r in (await db.execute(select(SecurityCandle).where(SecurityCandle.security_id == sid).order_by(SecurityCandle.trade_date))).scalars()]
        events = [{"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review, "amount": a.amount}
                  for a in (await db.execute(select(CorporateAction).where(CorporateAction.symbol == symbol))).scalars()] if symbol else []
        if rows:
            prep = tr_mod.prepare(rows, events)
            sk = ",".join(f"{k}:{v}" for k, v in prep["skipped"].items() if v)
            cache[sid] = ([r["trade_date"] for r in prep["rows"]], [r["close"] for r in prep["rows"]], prep["tr"], f"applied={prep['applied']}" + (f";skipped={sk}" if sk else ""))
        else:
            cache[sid] = ([], [], [], "no candles")
    return cache[sid]


async def _universe_return(db: AsyncSession, cache: dict, entry: date, exit_: date) -> Decimal | None:
    """Equal-weight average TOTAL return of every active stored stock that has both dates (the primary benchmark). The all-stock frame is
    built once per scoring run, on first need."""
    if "_all_tr" not in cache:
        from app.portfolio_intelligence.ledger import panel

        close, _vol, total, _meta = await panel.load_panel(db)
        cache["_all_tr"] = total
    k = (entry, exit_)
    if k not in cache:
        tr = cache["_all_tr"]
        ts_e, ts_x = __import__("pandas").Timestamp(entry), __import__("pandas").Timestamp(exit_)
        if ts_e not in tr.index or ts_x not in tr.index:
            cache[k] = None
        else:
            r = (tr.loc[ts_x] / tr.loc[ts_e] - 1.0).dropna()
            cache[k] = Decimal(str(float(r.mean()))) if len(r) else None
    return cache[k]


async def _etf_return(db: AsyncSession, cache: dict, entry: date, exit_: date) -> Decimal | None:
    """NIFTYBEES PRICE return over the same dates (secondary benchmark; labelled price)."""
    sid = (await db.execute(select(Security.id).where(Security.symbol == "NIFTYBEES", Security.kind == "etf"))).scalar_one_or_none()
    if sid is None:
        return None
    dates, prices, _tr, _flags = await _series(db, cache, sid)
    if entry in dates and exit_ in dates:
        return prices[dates.index(exit_)] / prices[dates.index(entry)] - 1
    return None


def realized_vol(closes: list[Decimal]) -> Decimal | None:
    import math

    if len(closes) < 3:
        return None
    r = [float(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    return Decimal(str(math.sqrt(var) * math.sqrt(252)))


async def score_pending(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or utcnow()
    market_last = candles_mod.expected_last_session(now)
    existing: dict[tuple, tuple[int, int | None]] = {}
    for key in (await db.execute(select(LedgerOutcome.claim_id, LedgerOutcome.subject_key, LedgerOutcome.horizon_sessions, LedgerOutcome.version, LedgerOutcome.full_refetches, LedgerOutcome.status))).all():
        k = key[:3]
        if k not in existing or key[3] > existing[k][0]:
            existing[k] = (key[3], key[4], key[5])
    refetch = {sid: n for sid, n in (await db.execute(select(CandleSync.security_id, CandleSync.full_refetches))).all()}
    cache: dict = {}
    ucache: dict = {}
    stats = {"subjects": 0, "scored": 0, "missing_exit": 0, "waiting": 0, "already_scored": 0, "rebased_rewritten": 0}
    for sub in await _subjects(db):
        stats["subjects"] += 1
        c = sub["claim"]
        h = c["horizon"]
        k = (c["id"], sub["key"], h)
        cur_refetch = refetch.get(sub["security_id"])
        prev = existing.get(k)
        if prev is not None and prev[2] == "scored" and prev[1] == cur_refetch:
            stats["already_scored"] += 1
            continue
        if prev is not None and prev[2] == "missing_exit" and prev[1] == cur_refetch:
            stats["already_scored"] += 1
            continue
        dates, closes, trs, flags = await _series(db, cache, sub["security_id"])
        loc = locate(dates, known_date(sub["known_at"]), h)
        version = 1 if prev is None else prev[0] + 1
        if prev is not None:
            stats["rebased_rewritten"] += 1
        base = dict(claim_id=c["id"], subject_type=sub["type"], subject_key=sub["key"], security_id=sub["security_id"], as_of_date=sub["as_of"], known_at=sub["known_at"], horizon_sessions=h,
                    version=version, feature=sub["feature"], direction=sub["direction"], origin="live", input_marker=sub["marker"], full_refetches=cur_refetch, scored_at=now)
        if loc["state"] == "waiting":
            due = add_sessions(known_date(sub["known_at"]), h + 1)
            if (market_last - due).days > OVERDUE_DAYS:
                db.add(LedgerOutcome(status="missing_exit", **base))
                stats["missing_exit"] += 1
            else:
                stats["waiting"] += 1
            continue
        i, j = loc["i"], loc["j"]
        db.add(LedgerOutcome(status="scored", entry_date=dates[i], exit_date=dates[j], entry_price=closes[i], exit_price=closes[j], fwd_return=trs[j] / trs[i] - 1, fwd_price_return=closes[j] / closes[i] - 1,
                             dividend_flags=flags, fwd_vol=realized_vol(trs[i : j + 1]), universe_return=await _universe_return(db, ucache, dates[i], dates[j]),
                             etf_return=await _etf_return(db, cache, dates[i], dates[j]), **base))
        stats["scored"] += 1
    await db.commit()
    return stats
