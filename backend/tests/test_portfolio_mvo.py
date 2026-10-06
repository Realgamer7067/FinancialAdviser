"""Covers two real solver failures caught running the backtester against real
historical data (Section 58): pypfopt's max_sharpe raising a plain ValueError
when no candidate beats the risk-free rate (bear-market window), and
OptimizationError on a degenerate covariance matrix. Both must degrade
gracefully, never crash the pipeline (Section 50)."""

import pandas as pd
import pytest

from app.models_iface.portfolio_mvo import MeanVariancePortfolioModel


@pytest.mark.asyncio
async def test_normal_case_uses_max_sharpe():
    model = MeanVariancePortfolioModel()
    returns = {
        "A": [0.01, 0.02, -0.01, 0.015, 0.005, 0.02, -0.005, 0.01, 0.03, -0.01] * 3,
        "B": [0.005, -0.01, 0.02, 0.01, -0.005, 0.015, 0.01, -0.02, 0.02, 0.005] * 3,
    }
    result = await model.optimize(returns, risk_free_rate=0.0, max_single_weight=0.8)
    assert result.model_version == "pyportfolioopt_mean_variance_v1"
    assert abs(sum(result.allocations.values()) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_all_returns_below_risk_free_rate_falls_back_instead_of_raising():
    # Every candidate has a small negative/flat mean return; a risk-free rate
    # above all of them reproduces the real "at least one asset must exceed
    # the risk-free rate" ValueError from pypfopt.
    returns = {
        "A": [-0.001, -0.002, 0.0005, -0.0015, -0.001] * 4,
        "B": [-0.0005, -0.001, -0.002, 0.0002, -0.0018] * 4,
    }
    model = MeanVariancePortfolioModel()
    result = await model.optimize(returns, risk_free_rate=0.5, max_single_weight=0.8)
    assert "fallback" in result.model_version
    assert abs(sum(result.allocations.values()) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_unequal_length_return_series_are_aligned_not_crashed():
    # Reproduces a real crash: one candidate backed by a shorter cached
    # history (e.g. TrueData's 200-bar cache) than another pulled fresh with
    # a longer window (e.g. yfinance) -- pd.DataFrame(dict-of-lists) used to
    # raise "All arrays must be of the same length" here.
    model = MeanVariancePortfolioModel()
    returns = {
        "A": [0.01, 0.02, -0.01, 0.015, 0.005, 0.02, -0.005, 0.01, 0.03, -0.01] * 3,
        "B": [0.005, -0.01, 0.02, 0.01, -0.005, 0.015, 0.01, -0.02, 0.02, 0.005] * 5,
    }
    result = await model.optimize(returns, risk_free_rate=0.0, max_single_weight=0.8)
    assert abs(sum(result.allocations.values()) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_single_candidate_is_fully_allocated_without_solving():
    model = MeanVariancePortfolioModel()
    result = await model.optimize({"A": [0.01, 0.02, -0.01]}, risk_free_rate=0.0, max_single_weight=1.0)
    assert result.allocations == {"A": 1.0}
    assert result.unallocated_cash == 0.0


@pytest.mark.asyncio
async def test_single_candidate_respects_concentration_cap():
    # docs/V2-RETHINK.md P0: a single-symbol allocation must never bypass the
    # cap just because there's no diversification decision to make.
    model = MeanVariancePortfolioModel()
    result = await model.optimize({"A": [0.01, 0.02, -0.01]}, risk_free_rate=0.0, max_single_weight=0.15)
    assert result.allocations == {"A": 0.15}
    assert result.unallocated_cash == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_equal_weight_fallback_respects_concentration_cap_with_explicit_cash():
    # docs/V2-RETHINK.md P0 finding: 3 candidates can't fill 100% under a 15%
    # cap (3 * 0.15 = 0.45) -- equal-weighting used to silently give ~33%
    # each, violating the cap. The fallback must cap each at 15% and report
    # the remaining 55% as explicit unallocated cash, never as an invisible
    # gap or a renormalized-back-up violation.
    model = MeanVariancePortfolioModel()
    result = model._equal_weight_result({"A": [], "B": [], "C": []}, max_single_weight=0.15)
    assert result.allocations == {"A": 0.15, "B": 0.15, "C": 0.15}
    assert all(w <= 0.15 + 1e-9 for w in result.allocations.values())
    assert result.unallocated_cash == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_equal_weight_fallback_fully_invests_when_cap_allows_it():
    model = MeanVariancePortfolioModel()
    result = model._equal_weight_result({"A": [], "B": []}, max_single_weight=0.8)
    assert result.allocations == {"A": 0.5, "B": 0.5}
    assert result.unallocated_cash == 0.0


@pytest.mark.asyncio
async def test_date_indexed_returns_align_by_trading_date_not_position():
    # docs/V2-RETHINK.md P1: candidate B has a mid-window gap (a missing
    # session) that candidate A doesn't share. Positional truncation to the
    # shortest length would zip A's and B's returns up by row position and
    # silently compare returns from different actual days once the gap
    # shifts everything. Date-indexed inputs must instead inner-join on the
    # real DatetimeIndex, dropping only the day that's actually missing.
    dates_a = pd.date_range("2025-01-01", periods=10, freq="D")
    dates_b = dates_a.delete(5)  # B is missing one day in the middle
    returns_a = pd.Series([0.01] * len(dates_a), index=dates_a)
    returns_b = pd.Series([0.02] * len(dates_b), index=dates_b)

    model = MeanVariancePortfolioModel()
    result = await model.optimize({"A": returns_a, "B": returns_b}, risk_free_rate=0.0, max_single_weight=0.8)

    assert set(result.allocations.keys()) <= {"A", "B"}
    assert abs(sum(result.allocations.values()) + result.unallocated_cash - 1.0) < 1e-6
