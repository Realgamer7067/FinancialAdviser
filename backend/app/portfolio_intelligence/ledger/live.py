"""Live claim status from stored outcomes, with the same ladder as the backtest but with the stricter live requirements.

The unit of evidence is a DATE. Daily signal rows with a 21-session horizon overlap heavily, so dates are thinned greedily to at
least `horizon` sessions apart before any statistic is computed."""

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import LedgerOutcome
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger import score as score_mod
from app.portfolio_intelligence.ledger import stats as S
from app.utils.time import utcnow

K_LIVE = sum(1 for c in R.LIVE_CLAIMS if c["type"] != "accounting")
ALPHA_LIVE = R.ALPHA / K_LIVE


def thin_dates(dates: list[date], horizon: int) -> list[date]:
    """Keep the first date, then each next date at least `horizon` weekdays after the last kept one (non-overlapping outcome windows)."""
    keep: list[date] = []
    for d in sorted(set(dates)):
        if not keep or score_mod.add_sessions(keep[-1], horizon) <= d:
            keep.append(d)
    return keep


def _f(x) -> float | None:
    return None if x is None else float(x)


async def _latest_scored(db: AsyncSession, claim_id: str) -> list[LedgerOutcome]:
    rows = (await db.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == claim_id, LedgerOutcome.origin == "live", LedgerOutcome.status == "scored")
                             .order_by(LedgerOutcome.subject_key, LedgerOutcome.version))).scalars().all()
    latest: dict = {}
    for r in rows:
        latest[r.subject_key] = r        # ascending version: the last one wins (a re-based history supersedes the old row, never edits it)
    return list(latest.values())


def _summ(vals: list[float], alpha: float) -> dict:
    return S.summarize_dates(vals, alpha)


async def claim_status(db: AsyncSession, c: dict, logged: list[dict] | None = None) -> dict:
    cid, h = c["id"], c["horizon"]
    logged = logged if logged is not None else await score_mod._subjects(db)
    mine = [s for s in logged if s["claim"]["id"] == cid]
    rows = await _latest_scored(db, cid)
    missing = (await db.execute(select(func.count()).select_from(LedgerOutcome).where(LedgerOutcome.claim_id == cid, LedgerOutcome.status == "missing_exit"))).scalar_one()
    scored_keys = {r.subject_key for r in rows}
    pending = [s for s in mine if s["key"] not in scored_keys]
    first_expected = min((score_mod.add_sessions(score_mod.known_date(s["known_at"]), h + 1) for s in pending), default=None)
    base = {"id": cid, "type": c["type"], "source": c["source"], "horizon_sessions": h, "logged": len(mine), "scored": len(rows), "missing_exit": missing, "pending": len(pending),
            "first_results_expected": first_expected.isoformat() if first_expected else None, "evidence": "live"}
    if c["type"] == "accounting":
        paid = sum((r.feature or 0) for r in rows)
        w_ret = (sum(((r.feature or 0) * (r.fwd_return or 0) for r in rows), 0) / paid) if paid else None
        etf = [r.etf_return for r in rows if r.etf_return is not None]
        return {**base, "label": "ACCOUNTING, not skill evidence", "note": c["note"], "plan_weighted_return": _f(w_ret), "market_etf_average_return_same_dates": _f(sum(etf) / len(etf)) if etf else None,
                "verdict": None}
    by_date: dict[date, list[LedgerOutcome]] = defaultdict(list)
    for r in rows:
        by_date[r.as_of_date].append(r)
    dates = thin_dates(list(by_date), h)
    vals, spreads = [], []
    for d in dates:
        rs = by_date[d]
        if c["type"] == "ic":
            if len(rs) < R.LIVE_MIN_NAMES:
                continue
            y = [(_f(r.fwd_vol) if c["outcome"] == "forward_vol" else _f(r.fwd_return)) for r in rs]
            x = [c["sign"] * _f(r.feature) for r in rs]
            ic = S.spearman(x, y)
            if ic is None:
                continue
            vals.append(ic)
            if c["outcome"] == "return":
                arr = np.array(x)
                top = [yy for xx, yy in zip(x, y) if xx >= np.quantile(arr, 0.8)]
                spreads.append(float(np.mean(top) - np.mean(y)) - R.ROUND_TRIP_COST)      # top fifth minus the average scored name, after an assumed round trip
        else:  # event_excess: claim true when the excess return after the event has the claimed sign
            ex = [(_f(r.fwd_return) - _f(r.universe_return)) for r in rs if r.universe_return is not None]
            if ex:
                vals.append(c["direction"] * float(np.mean(ex)))    # direction -1 ("falls"): a NEGATIVE excess return makes the claim hold, so the value is -excess
    s = _summ(vals, ALPHA_LIVE)
    mde = S.minimum_detectable_ic(s["sd"], s["n_dates"], ALPHA_LIVE) if c["type"] == "ic" else None
    net = _summ(spreads, ALPHA_LIVE)["ci"][0] if (len(spreads) >= 3 and _summ(spreads, ALPHA_LIVE)["ci"]) else (s["ci"][0] if (c["type"] == "event_excess" and s["ci"]) else None)
    v = S.verdict(s, mde=mde, evidence="live", alpha_ok=True, min_dates=R.MIN_DATES_FOR_ANY_VERDICT, live_min_dates=R.LIVE_MIN_DATES, net_lower=net)
    return {**base, "n_dates_used": s["n_dates"], "mean": s["mean_ic"], "ci_corrected": s["ci"], "minimum_detectable_ic": mde, "verdict": v, "verdict_meaning": R.VERDICTS[v],
            "net_of_cost_lower_bound": net, "dates_needed_for_earned": R.LIVE_MIN_DATES,
            "unit": "mean per-date rank IC" if c["type"] == "ic" else "mean per-date excess return after the event, signed so a positive number means the claim held"}


async def live_status(db: AsyncSession) -> dict:
    logged = await score_mod._subjects(db)      # read the logged subjects ONCE for all claims
    claims = [await claim_status(db, c, logged) for c in R.LIVE_CLAIMS]
    total_scored = (await db.execute(select(func.count()).select_from(LedgerOutcome).where(LedgerOutcome.status == "scored"))).scalar_one()
    return {"registry_hash": R.live_registry_hash(), "k": K_LIVE, "alpha_per_claim": ALPHA_LIVE, "claims": claims, "outcomes_scored": total_scored,
            "rule": "A live claim becomes `earned` only after at least %d distinct non-overlapping dates with its lower bound above zero after the Bonferroni correction and an assumed %.1f%% round-trip cost. "
                    "`earned` changes nothing automatically: it only lets the owner review whether to give the signal a weight." % (R.LIVE_MIN_DATES, R.ROUND_TRIP_COST * 100),
            "generated_at": utcnow().isoformat()}
