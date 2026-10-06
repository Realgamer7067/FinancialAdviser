"""Statistics for the scoring ledger. Pure, no scipy: the t distribution is implemented here (regularized incomplete beta) and
tested against known values. The unit of evidence is a DATE (one cross-sectional rank IC per rebalance date), never a stock-row:
stocks on the same date share the market's move, so treating them as independent would overstate the evidence enormously."""

import math

import numpy as np
import pandas as pd


def spearman(x, y) -> float | None:
    """Rank correlation over the pairs where both values exist; None if fewer than 10 pairs or no variation."""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 10:
        return None
    rx, ry = df["x"].rank(), df["y"].rank()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _betacf(a: float, b: float, x: float) -> float:
    tiny, qab, qap, qam = 1e-30, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    p = 0.5 * betainc(df / 2.0, 0.5, x)
    return 1.0 - p if t > 0 else p


def t_ppf(p: float, df: float) -> float:
    """Inverse CDF by bisection (the study needs a handful of these, so speed does not matter)."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    lo, hi = -50.0, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def summarize_dates(values: list[float], alpha: float) -> dict:
    """Mean, standard error, t, two-sided p and the (1 - alpha) t-interval of per-date rank ICs."""
    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    n = len(v)
    if n < 3:
        return {"n_dates": n, "mean_ic": float(v.mean()) if n else None, "sd": None, "se": None, "t": None, "p_two_sided": None, "ci": None}
    mean, sd = float(v.mean()), float(v.std(ddof=1))
    se = sd / math.sqrt(n)
    t = mean / se if se > 0 else 0.0
    p = 2.0 * (1.0 - t_cdf(abs(t), n - 1))
    crit = t_ppf(1.0 - alpha / 2.0, n - 1)
    return {"n_dates": n, "mean_ic": mean, "sd": sd, "se": se, "t": t, "p_two_sided": p, "ci": [mean - crit * se, mean + crit * se], "alpha": alpha}


def bootstrap_ci(values: list[float], alpha: float, resamples: int, seed: int, block: int = 1) -> list[float] | None:
    """Percentile interval of the mean over resampled blocks of consecutive dates (block 1 = plain resampling of dates)."""
    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    n = len(v)
    if n < 5:
        return None
    rng = np.random.default_rng(seed)
    nb = max(1, math.ceil(n / block))
    starts = rng.integers(0, max(1, n - block + 1), size=(resamples, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(resamples, -1)[:, :n]
    means = v[idx].mean(axis=1)
    return [float(np.quantile(means, alpha / 2.0)), float(np.quantile(means, 1.0 - alpha / 2.0))]


def minimum_detectable_ic(sd: float | None, n: int, alpha: float, power: float = 0.8) -> float | None:
    """The smallest true mean IC this many dates would detect at the stated alpha and power."""
    if sd is None or n < 3:
        return None
    df = n - 1
    return float((t_ppf(1.0 - alpha / 2.0, df) + t_ppf(power, df)) * sd / math.sqrt(n))


def verdict(summary: dict, *, mde: float | None, evidence: str, alpha_ok: bool, n_live_dates: int | None = None, min_dates: int, live_min_dates: int, net_lower: float | None = None) -> str:
    """The ladder from registry.VERDICTS. `evidence` is "backtest" or "live". `alpha_ok` means the interval was built at the Bonferroni alpha."""
    n = summary["n_dates"]
    if n == 0:
        return "no_data"
    if n < min_dates or summary["ci"] is None:
        return "too_early"
    lo, hi = summary["ci"]
    if hi < 0:
        return "negative"
    if lo > 0 and summary["mean_ic"] > 0 and alpha_ok:
        if evidence == "backtest":
            return "backtest_suggestive"
        if n >= live_min_dates and net_lower is not None and net_lower > 0:
            return "earned"
        return "promising"
    if lo > 0 and evidence == "live":
        return "promising"
    return "underpowered" if (mde is not None and mde > 0.05) else "no_evidence"
