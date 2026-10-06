"""Historical volatility and drawdown of the CURRENT holdings (plan 5.1).

Precision is earned, not assumed: needs >= 252 aligned daily returns on a
common-date window AND the instruments used must cover >= 80% of known
portfolio value; otherwise the status is insufficient_data and NO number is
shown. Adjusted closes only (caller filters). Static current weights; the
result describes the observed window, not future or worst-case risk."""

import math
from datetime import date
from decimal import Decimal

METHOD_VERSION = "volatility-v1"
MIN_RETURNS = 252
MIN_COVERAGE = Decimal("0.80")


def annualized_vol(rets: list[float]) -> float:
    """Sample standard deviation of daily simple returns times sqrt(252). The ONE definition: the Risk page's portfolio
    figure and the Market page's per-security signal both call this, so they cannot disagree."""
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252)


def max_drawdown(rets: list[float]) -> float:
    """Worst peak-to-trough fall of the compounded return path (a negative number, 0 if it never fell)."""
    peak, level, mdd = 1.0, 1.0, 0.0
    for r in rets:
        level *= 1.0 + r
        peak = max(peak, level)
        mdd = min(mdd, level / peak - 1.0)
    return mdd


def portfolio_volatility(series: dict[str, list[tuple[date, float]]], values: dict[str, Decimal], total_known: Decimal) -> dict:
    base = {"method_version": METHOD_VERSION, "price_basis": "adjusted close (split/dividend adjusted), daily",
            "weights": "current values held constant (static weights)", "min_returns": MIN_RETURNS,
            "min_coverage": str(MIN_COVERAGE)}
    if total_known <= 0 or not values:
        return {**base, "status": "insufficient_data", "coverage_fraction": "0", "reason": "no valued direct equity holdings with price history"}

    usable: dict[str, list[tuple[date, float]]] = {}
    for key, s in series.items():
        clean = [(d, p) for d, p in s if p is not None and math.isfinite(p) and p > 0]
        if len(clean) >= MIN_RETURNS + 1:
            usable[key] = sorted(clean)
    if not usable:
        return {**base, "status": "insufficient_data", "coverage_fraction": "0",
                "reason": f"no holding has at least {MIN_RETURNS + 1} adjusted daily prices"}

    common = sorted(set.intersection(*[{d for d, _ in s} for s in usable.values()]))
    if len(common) < MIN_RETURNS + 1:
        return {**base, "status": "insufficient_data", "coverage_fraction": None,
                "reason": f"only {max(len(common) - 1, 0)} aligned daily returns across the holdings (need {MIN_RETURNS})"}

    used_value = sum((values[k] for k in usable if k in values), Decimal(0))
    coverage = used_value / total_known
    if coverage < MIN_COVERAGE:
        return {**base, "status": "insufficient_data", "coverage_fraction": format(coverage.quantize(Decimal("0.0001")), "f"),
                "reason": f"price history covers {coverage:.0%} of known portfolio value (need {MIN_COVERAGE:.0%}); no figure is shown"}

    keys = sorted(usable)
    weights = [float(values[k] / used_value) for k in keys]
    lookup = {k: dict(usable[k]) for k in keys}
    rets: list[float] = []
    for prev, cur in zip(common, common[1:]):
        rets.append(sum(w * (lookup[k][cur] / lookup[k][prev] - 1.0) for w, k in zip(weights, keys)))
    n = len(rets)
    vol, mdd = annualized_vol(rets), max_drawdown(rets)
    return {
        **base, "status": "ready", "coverage_fraction": format(coverage.quantize(Decimal("0.0001")), "f"),
        "annualized_volatility": round(vol, 4), "max_drawdown_in_window": round(mdd, 4),
        "window_start": common[0].isoformat(), "window_end": common[-1].isoformat(), "observations": n,
        "instruments_used": len(keys),
        "warnings": ([] if coverage == 1 else [f"this figure describes the covered {coverage:.0%} of known value; the rest "
                                               "(cash, deposits, funds or holdings without enough price history) is not included"])
                    + ["describes the observed window only; not a forecast or a worst case"],
    }
