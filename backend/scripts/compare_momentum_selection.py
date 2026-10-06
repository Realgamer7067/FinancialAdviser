"""A small chronological, cost-aware comparison on the stored 5-year history (run from backend/: python -m scripts.compare_momentum_selection).

What it CAN test: the MOMENTUM component of the new ranking (12-1 and 6-1 on total return, one vote) against the old selection logic's liquidity ordering and
against the equal-weighted universe. What it CANNOT test: value and quality, because there is no point-in-time fundamentals history in this project (only today's
snapshot), so the composite's predictive performance remains UNTESTED. Caveats that apply to every number: the universe is today's listed stocks (survivorship),
only about five years / one market regime, monthly rebalance dates give roughly 45 observations, gross of tax.

Method: each month-end t, among stocks with 253 sessions of history and a median 20-day traded value of at least Rs 1 crore at t (point-in-time), form an equal-weighted
top-10. Entry is the close of the session after t, exit 21 sessions later (the registry's rule). Cost: 0.3% on every rupee bought and every rupee sold at each rebalance
(first month: buy only). Per-date results are compared; the interval is a bootstrap of the per-date differences."""

import asyncio
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.db import AsyncSessionLocal
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger import stats as S
from app.portfolio_intelligence.ledger.backtest import rebalance_dates
from app.portfolio_intelligence.ledger.panel import load_panel

TOP_N = 10
SIDE_COST = 0.003


def pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def run(close: pd.DataFrame, volume: pd.DataFrame, tr: pd.DataFrame) -> dict:
    mom12 = tr.shift(21) / tr.shift(252) - 1.0
    mom6 = tr.shift(21) / tr.shift(126) - 1.0
    liq = (close * volume).rolling(20).median()
    entry = tr.shift(-1)
    fwd = tr.shift(-(1 + R.PRIMARY_HORIZON)) / entry - 1.0
    dates = rebalance_dates(close.index, warmup=R.WARMUP_SESSIONS, tail=R.PRIMARY_HORIZON + 1)
    book = {"momentum": [], "liquidity": [], "universe": []}
    prev: dict[str, set] = {"momentum": set(), "liquidity": set()}
    rows = []
    for d in dates:
        ok = liq.loc[d].ge(R.LIQUIDITY_FLOOR_RUPEES) & mom12.loc[d].notna() & mom6.loc[d].notna() & fwd.loc[d].notna()
        names = ok[ok].index
        if len(names) < 100:
            continue
        comp = (pct_rank(mom12.loc[d, names]) + pct_rank(mom6.loc[d, names])) / 2
        picks = {"momentum": set(comp.nlargest(TOP_N).index), "liquidity": set(liq.loc[d, names].nlargest(TOP_N).index)}
        row = {"date": d.date().isoformat(), "n_eligible": int(len(names)), "universe": float(fwd.loc[d, names].mean())}
        for k, sel in picks.items():
            gross = float(fwd.loc[d, list(sel)].mean())
            kept = len(sel & prev[k]) / TOP_N if prev[k] else 0.0
            turnover_cost = SIDE_COST * ((1 - kept) + (1 - kept if prev[k] else 0.0))      # buy what is new, sell what left (first month: buy only)
            row[k], row[k + "_net"], row[k + "_turnover"] = gross, gross - turnover_cost, 1 - kept
            prev[k] = sel
        rows.append(row)
    df = pd.DataFrame(rows)

    def summ(col):
        x = df[col].dropna().tolist()
        m = float(np.mean(x))
        return {"mean_monthly": round(m, 5), "annualised_simple": round(m * 12, 4), "hit_rate_vs_universe": None}

    out = {"dates": len(df), "first": df["date"].iloc[0], "last": df["date"].iloc[-1], "top_n": TOP_N, "side_cost": SIDE_COST, "eligible_per_date_median": float(df["n_eligible"].median()), "strategies": {}}
    for k in ("momentum", "liquidity"):
        diff = (df[k + "_net"] - df["universe"]).tolist()
        ci = S.bootstrap_ci(diff, 0.05, R.BOOTSTRAP["resamples"], R.BOOTSTRAP["seed"], 1)
        out["strategies"][k] = {"net_mean_monthly": round(float(df[k + "_net"].mean()), 5), "gross_mean_monthly": round(float(df[k].mean()), 5), "avg_turnover": round(float(df[k + "_turnover"].mean()), 3),
                                 "net_excess_over_universe_monthly": round(float(np.mean(diff)), 5), "excess_ci95": [round(c, 5) for c in ci] if ci else None,
                                 "months_beating_universe": f"{sum(1 for x in diff if x > 0)} of {len(diff)}"}
    out["universe_mean_monthly"] = round(float(df["universe"].mean()), 5)
    mom_vs_liq = (df["momentum_net"] - df["liquidity_net"]).tolist()
    ci = S.bootstrap_ci(mom_vs_liq, 0.05, R.BOOTSTRAP["resamples"], R.BOOTSTRAP["seed"], 1)
    out["momentum_minus_liquidity"] = {"mean_monthly": round(float(np.mean(mom_vs_liq)), 5), "ci95": [round(c, 5) for c in ci] if ci else None}
    return out


async def main() -> None:
    async with AsyncSessionLocal() as db:
        close, volume, tr, meta = await load_panel(db)
    res = run(close, volume, tr)
    res["panel"] = meta | {"dividends": meta.get("dividends")}
    res["caveats"] = [
        "Survivorship: the universe is today's listed stocks with enough history, so names that were delisted, merged or dropped are absent and winners are over-represented, which flatters momentum.",
        "Returns are TOTAL return (split/bonus-adjusted price plus scaled cash dividends); the study-v1 note that dividends are missing does not apply to this run.",
        "Only about five years, one market regime, 47 monthly observations: only large effects are detectable, and the interval on the momentum excess includes zero.",
        "The baseline is a pure liquidity ordering of the whole listed universe (the 10 most traded by rupees), a proxy for the old selection, which picked the most traded Nifty 50 stock per sector; it is not the identical rule.",
        "Only the momentum component can be tested here: value and quality need point-in-time fundamentals, which this project does not have, so the composite as a whole is UNTESTED.",
        "Top-10 equal weight with a 0.3% cost on each side of every change; real fills, taxes and market impact are not modelled."]
    text = json.dumps(res, indent=2, default=str)
    Path("../docs/portfolio-intelligence-execution/momentum-comparison.json").write_text(text)
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
