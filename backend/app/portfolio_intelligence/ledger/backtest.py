"""The retrospective study: for each month-end rebalance date, rank today's stored stocks on a `signals-v1` feature and see what they
earned next. Pure (DataFrames in, a JSON-able dict out).

No look-ahead, by construction and by test: a feature at date t uses closes up to and including t; the outcome uses closes from the
session AFTER t (entry) to `horizon` sessions after entry. Eligibility (history, liquidity) is judged point-in-time at t.

This is BACKTEST evidence: survivorship-biased, price-only, partly in-sample and gross of costs (registry.BIASES). Its best possible
verdict is `backtest_suggestive`."""

import math

import numpy as np
import pandas as pd

from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger import stats as S


def feature_frames(close: pd.DataFrame, volume: pd.DataFrame, *, horizon: int, vol_window: int, outcome: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Features come from `close` (price). Outcomes come from `outcome` (a total-return index) when given, else from `close`."""
    out = close if outcome is None else outcome
    ret = close.pct_change(fill_method=None)
    oret = out.pct_change(fill_method=None)
    feats = {
        "sma200_ratio": close / close.rolling(200).mean() - 1.0,
        "mom_12_1": close.shift(21) / close.shift(252) - 1.0,
        "vol_252": ret.rolling(252).std() * math.sqrt(252),
        "liquidity": (close * volume).rolling(20).median(),
    }
    entry = out.shift(-1)
    outcomes = {
        f"fwd_{horizon}": out.shift(-(1 + horizon)) / entry - 1.0,
        f"fwd_{R.SECONDARY_HORIZON}": out.shift(-(1 + R.SECONDARY_HORIZON)) / entry - 1.0,
        "forward_vol": oret.rolling(vol_window).std().shift(-(1 + vol_window)) * math.sqrt(252),
    }
    return {**feats, **outcomes}


def rebalance_dates(index: pd.DatetimeIndex, *, warmup: int, tail: int) -> list[pd.Timestamp]:
    """Last session of each calendar month with `warmup` sessions behind it and `tail` sessions of future ahead of it."""
    s = pd.Series(np.arange(len(index)), index=index)
    last = s.groupby([index.year, index.month]).tail(1)
    return [d for d, pos in last.items() if pos >= warmup - 1 and pos + tail < len(index)]


def _by_year(ics: dict[pd.Timestamp, float]) -> dict[str, float]:
    out: dict[str, list[float]] = {}
    for d, v in ics.items():
        out.setdefault(str(d.year), []).append(v)
    return {y: round(float(np.mean(v)), 4) for y, v in sorted(out.items())}


def run_study(close: pd.DataFrame, volume: pd.DataFrame, total_return: pd.DataFrame | None = None, version: str | None = None) -> dict:
    """close/volume: index = sessions (ascending DatetimeIndex), columns = security ids. `total_return` (same shape) makes this study-v2:
    outcomes are scored on it while the features stay price-based."""
    primary, secondary = R.PRIMARY_HORIZON, R.SECONDARY_HORIZON
    version = version or (R.STUDY_VERSION_V2 if total_return is not None else R.STUDY_VERSION)
    reg_hash = R.REGISTRIES[version][1]()
    F = feature_frames(close, volume, horizon=primary, vol_window=R.FORWARD_VOL_WINDOW, outcome=total_return)
    dates = rebalance_dates(close.index, warmup=R.WARMUP_SESSIONS, tail=1 + secondary)
    skipped, eligible_counts = [], {}
    per_claim_ic: dict[str, dict] = {c["id"]: {} for c in R.CLAIMS}
    per_claim_ic63: dict[str, dict] = {c["id"]: {} for c in R.CLAIMS if c["kind"] == "return"}
    spreads: dict[str, dict] = {c["id"]: {} for c in R.CLAIMS if c["kind"] == "return"}
    for t in dates:
        liq = F["liquidity"].loc[t]
        ok = (liq >= R.LIQUIDITY_FLOOR_RUPEES) & F["vol_252"].loc[t].notna() & F["mom_12_1"].loc[t].notna() & F["sma200_ratio"].loc[t].notna()
        if int(ok.sum()) < R.MIN_NAMES_PER_DATE:
            skipped.append(t.date().isoformat())
            continue
        names = ok.index[ok]
        eligible_counts[t.date().isoformat()] = len(names)
        fwd = F[f"fwd_{primary}"].loc[t, names]
        fwd63 = F[f"fwd_{secondary}"].loc[t, names]
        fvol = F["forward_vol"].loc[t, names]
        for c in R.CLAIMS:
            x = c["sign"] * F[c["feature"]].loc[t, names]
            y = fvol if c.get("outcome") == "forward_vol" else fwd
            ic = S.spearman(x, y)
            if ic is not None:
                per_claim_ic[c["id"]][t] = ic
            if c["kind"] == "return":
                ic63 = S.spearman(x, fwd63)
                if ic63 is not None:
                    per_claim_ic63[c["id"]][t] = ic63
                d = pd.DataFrame({"x": x, "y": fwd}).dropna()
                if len(d) >= R.MIN_NAMES_PER_DATE:
                    top = d[d["x"] >= d["x"].quantile(0.8)]["y"].mean()
                    spreads[c["id"]][t] = float(top - d["y"].mean())     # top quintile minus the equal-weight universe, gross
    claims_out = []
    for c in R.CLAIMS:
        ics = per_claim_ic[c["id"]]
        vals = list(ics.values())
        plain = S.summarize_dates(vals, R.ALPHA)
        corrected = S.summarize_dates(vals, R.ALPHA_PER_CLAIM)
        boot = S.bootstrap_ci(vals, R.ALPHA_PER_CLAIM, R.BOOTSTRAP["resamples"], R.BOOTSTRAP["seed"], R.BOOTSTRAP["block"])
        mde = S.minimum_detectable_ic(corrected["sd"], corrected["n_dates"], R.ALPHA_PER_CLAIM)
        v = S.verdict(corrected, mde=mde, evidence="backtest", alpha_ok=True, min_dates=R.MIN_DATES_FOR_ANY_VERDICT, live_min_dates=R.LIVE_MIN_DATES)
        entry = {"id": c["id"], "statement": c["statement"], "kind": c["kind"], "feature": c["feature"], "sign": c["sign"], "verdict": v, "verdict_meaning": R.VERDICTS[v],
                 "primary": {"horizon": primary, **{k: (None if corrected[k] is None else (round(corrected[k], 5) if not isinstance(corrected[k], list) else [round(z, 5) for z in corrected[k]])) for k in ("n_dates", "mean_ic", "sd", "t", "p_two_sided", "ci")},
                             "ci_95_unadjusted": None if plain["ci"] is None else [round(z, 5) for z in plain["ci"]],
                             "bootstrap_ci_corrected": None if boot is None else [round(z, 5) for z in boot], "minimum_detectable_ic": None if mde is None else round(mde, 4),
                             "share_of_dates_positive": round(float(np.mean([x > 0 for x in vals])), 3) if vals else None, "by_year_mean_ic": _by_year(ics)}}
        if c["kind"] == "return":
            v63 = [per_claim_ic63[c["id"]][d] for d in sorted(per_claim_ic63[c["id"]])][::3]     # every third month: non-overlapping 63-session windows
            s63 = S.summarize_dates(v63, R.ALPHA)
            sp = list(spreads[c["id"]].values())
            ssp = S.summarize_dates(sp, R.ALPHA)
            entry["secondary_63"] = {"horizon": secondary, "descriptive_only": True, "n_dates": s63["n_dates"], "mean_ic": None if s63["mean_ic"] is None else round(s63["mean_ic"], 5),
                                     "ci_95": None if s63["ci"] is None else [round(z, 5) for z in s63["ci"]]}
            entry["top_quintile_minus_universe"] = {"horizon": primary, "gross_of_costs": True, "n_dates": ssp["n_dates"], "mean": None if ssp["mean_ic"] is None else round(ssp["mean_ic"], 5),
                                                    "ci_95": None if ssp["ci"] is None else [round(z, 5) for z in ssp["ci"]], "note": "the average one-month return of the top fifth minus the average of all eligible stocks, before costs and tax"}
        claims_out.append(entry)
    n_names = list(eligible_counts.values())
    return {"study_version": version, "registry_hash": reg_hash, "outcome_basis": "total_return" if total_return is not None else "price", "evidence": "backtest", "dates": {"n": len(eligible_counts), "first": min(eligible_counts) if eligible_counts else None,
            "last": max(eligible_counts) if eligible_counts else None, "skipped_for_too_few_names": skipped}, "names_per_date": {"min": min(n_names) if n_names else None, "median": int(np.median(n_names)) if n_names else None,
            "max": max(n_names) if n_names else None}, "claims": claims_out, "biases": R.BIASES, "alpha_per_claim": R.ALPHA_PER_CLAIM, "k": R.K}
