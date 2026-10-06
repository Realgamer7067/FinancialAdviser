"""Ledoit-Wolf shrunk covariance of stock returns (PyPortfolioOpt, already installed), used to DESCRIBE the risk of a proposed set of stocks next to what is
held. There is no optimiser and no expected-return input: nothing here chooses weights."""

import math

import pandas as pd

METHOD = "Ledoit-Wolf shrinkage (PyPortfolioOpt), daily total-return returns over the latest aligned 252 sessions, annualised"
MIN_RETURNS = 126
WINDOW = 252
CORRELATION_WARN = 0.7


def analyse(series: dict[str, pd.Series], picks: list[str], held: list[str]) -> dict:
    """series: {symbol: total-return level series indexed by date}. picks: the proposed stocks. held: stocks already held directly."""
    from pypfopt import risk_models

    symbols = [s for s in dict.fromkeys([*picks, *held]) if s in series]
    base = {"method": METHOD, "min_returns": MIN_RETURNS, "correlation_warning_above": CORRELATION_WARN}
    if len([s for s in picks if s in series]) < 2:
        return {**base, "status": "insufficient_data", "reason": "fewer than two proposed stocks have price history"}
    levels = pd.DataFrame({s: series[s] for s in symbols}).sort_index().dropna()
    rets = levels.pct_change().dropna().iloc[-WINDOW:]
    if len(rets) < MIN_RETURNS:
        return {**base, "status": "insufficient_data", "reason": f"only {len(rets)} aligned daily returns (need {MIN_RETURNS})"}
    shrink = risk_models.CovarianceShrinkage(rets, returns_data=True, frequency=252)
    cov = shrink.ledoit_wolf()
    sd = pd.Series({s: math.sqrt(cov.loc[s, s]) for s in rets.columns})
    corr = cov / (sd.values[:, None] * sd.values[None, :])
    ps = [s for s in picks if s in rets.columns]
    w = pd.Series(1.0 / len(ps), index=ps)
    sleeve_vol = float(math.sqrt(w.values @ cov.loc[ps, ps].values @ w.values))
    pairs = [(a, b, float(corr.loc[a, b])) for i, a in enumerate(ps) for b in ps[i + 1:]]
    avg_corr = sum(c for _, _, c in pairs) / len(pairs)
    vs_held = {}
    for s in ps:
        others = [h for h in held if h in rets.columns and h != s]
        if others:
            vs_held[s] = round(sum(float(corr.loc[s, h]) for h in others) / len(others), 3)
    warnings = [f"{a} and {b} have moved together (correlation {c:.2f}), so holding both adds less diversification than two separate stocks usually do" for a, b, c in pairs if c > CORRELATION_WARN]
    warnings += [f"{s} has moved closely with what you already hold (average correlation {c:.2f})" for s, c in vs_held.items() if c > CORRELATION_WARN]
    return {**base, "status": "ready", "returns_used": len(rets), "shrinkage_intensity": round(float(shrink.delta), 3), "stocks": ps,
            "equal_weight_volatility": round(sleeve_vol, 4), "average_pairwise_correlation": round(avg_corr, 3), "stand_alone_volatility": {s: round(float(sd[s]), 4) for s in ps},
            "average_correlation_with_held": vs_held, "warnings": warnings,
            "note": "A description of the past window, not a forecast. Shrinkage pulls noisy pairwise correlations toward a common value so a short history does not exaggerate them."}
