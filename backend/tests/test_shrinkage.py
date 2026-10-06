import numpy as np
import pandas as pd
import pytest

from app.portfolio_intelligence.risk import shrinkage as SH


def levels(n=300, seed=1, corr_with=None, rho=0.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.012, n)
    if corr_with is not None:
        r = rho * corr_with + np.sqrt(1 - rho**2) * r
    return r


def to_series(r):
    return pd.Series(100 * np.cumprod(1 + r), index=pd.bdate_range("2025-01-01", periods=len(r)))


def test_shrunk_covariance_describes_the_sleeve_and_flags_pairs_that_move_together():
    base = levels(seed=1)
    series = {"A": to_series(base), "B": to_series(levels(seed=2, corr_with=base, rho=0.95)), "C": to_series(levels(seed=3)), "H": to_series(levels(seed=4, corr_with=base, rho=0.9))}
    out = SH.analyse(series, picks=["A", "B", "C"], held=["H"])
    assert out["status"] == "ready" and out["returns_used"] == 252 and 0.0 <= out["shrinkage_intensity"] <= 1.0
    assert out["equal_weight_volatility"] > 0 and set(out["stand_alone_volatility"]) == {"A", "B", "C"}
    assert any("A and B have moved together" in w for w in out["warnings"])                 # the correlated pair is called out
    assert out["average_correlation_with_held"]["A"] > 0.6 > out["average_correlation_with_held"]["C"]
    assert "not a forecast" in out["note"] and "expected" not in out["method"].lower()      # no expected-return input anywhere


def test_too_little_history_or_too_few_stocks_is_stated_not_faked():
    s = {"A": to_series(levels(n=60)), "B": to_series(levels(n=60, seed=2))}
    assert SH.analyse(s, ["A", "B"], [])["status"] == "insufficient_data" and "aligned daily returns" in SH.analyse(s, ["A", "B"], [])["reason"]
    assert SH.analyse({"A": to_series(levels())}, ["A"], [])["status"] == "insufficient_data"
