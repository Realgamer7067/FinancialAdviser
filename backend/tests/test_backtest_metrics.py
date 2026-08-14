import numpy as np
import pandas as pd

from app.backtesting.metrics import (
    annualized_return,
    annualized_volatility,
    hit_rate,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)


def test_annualized_return_of_constant_daily_return():
    daily = 0.001
    returns = pd.Series([daily] * 252)
    result = annualized_return(returns, periods_per_year=252)
    expected = (1 + daily) ** 252 - 1
    assert abs(result - expected) < 1e-9


def test_annualized_return_of_zero_returns_is_zero():
    returns = pd.Series([0.0] * 100)
    assert annualized_return(returns, periods_per_year=252) == 0.0


def test_annualized_volatility_scales_with_sqrt_time():
    rng = np.random.default_rng(42)
    daily_std = 0.01
    returns = pd.Series(rng.normal(0, daily_std, 1000))
    result = annualized_volatility(returns, periods_per_year=252)
    expected = daily_std * (252**0.5)
    assert abs(result - expected) < 0.02  # sample noise tolerance


def test_sharpe_ratio_higher_for_less_volatile_equal_mean_series():
    rng = np.random.default_rng(1)
    low_vol = pd.Series(rng.normal(0.0005, 0.005, 500))
    high_vol = pd.Series(rng.normal(0.0005, 0.05, 500))
    assert sharpe_ratio(low_vol, 0.0, 252) > sharpe_ratio(high_vol, 0.0, 252)


def test_sharpe_ratio_zero_std_returns_zero_not_error():
    returns = pd.Series([0.001] * 50)
    assert sharpe_ratio(returns, 0.0, 252) == 0.0


def test_sortino_ignores_upside_volatility():
    # Same mean/total variance, but sortino should be less punishing when
    # the volatility is all on the upside.
    upside_only = pd.Series([0.0, 0.0, 0.0, 0.0, 0.10])
    mixed = pd.Series([0.0, 0.02, -0.02, 0.03, -0.03])
    assert sortino_ratio(upside_only, 0.0, 252) >= sortino_ratio(mixed, 0.0, 252)


def test_max_drawdown_known_series():
    # Prices: 100 -> 110 -> 88 -> 99  (peak 110, trough 88 => -20% drawdown)
    returns = pd.Series([0.10, -0.20, 0.125])
    result = max_drawdown(returns)
    assert abs(result - (-0.20)) < 1e-6


def test_max_drawdown_monotonic_gains_is_zero():
    returns = pd.Series([0.01, 0.01, 0.01])
    assert max_drawdown(returns) == 0.0


def test_hit_rate_known_series():
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.0])
    assert hit_rate(returns) == 0.4  # 2 of 5 strictly positive


def test_hit_rate_empty_series_is_zero():
    assert hit_rate(pd.Series(dtype=float)) == 0.0
