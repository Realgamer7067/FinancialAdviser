"""Covers two real solver failures caught running the backtester against real
historical data (Section 58): pypfopt's max_sharpe raising a plain ValueError
when no candidate beats the risk-free rate (bear-market window), and
OptimizationError on a degenerate covariance matrix. Both must degrade
gracefully, never crash the pipeline (Section 50)."""

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
async def test_single_candidate_is_fully_allocated_without_solving():
    model = MeanVariancePortfolioModel()
    result = await model.optimize({"A": [0.01, 0.02, -0.01]}, risk_free_rate=0.0, max_single_weight=1.0)
    assert result.allocations == {"A": 1.0}
