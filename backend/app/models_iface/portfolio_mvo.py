"""Deterministic mean-variance PortfolioModel (PyPortfolioOpt). This is the
real, working MVP portfolio optimizer -- see build plan for why FinRL's DRL
agent is a stub instead (CPU-only training would be undertrained while
claiming "FinRL integrated", which Section 74 forbids)."""

import asyncio

import pandas as pd
from pypfopt import EfficientFrontier, exceptions, expected_returns, risk_models

from app.models_iface.base import PortfolioAllocationResult, PortfolioModel

_VERSION = "pyportfolioopt_mean_variance_v1"


class MeanVariancePortfolioModel(PortfolioModel):
    async def optimize(
        self,
        candidate_returns: dict[str, list[float]],
        risk_free_rate: float,
        max_single_weight: float,
    ) -> PortfolioAllocationResult:
        if len(candidate_returns) < 2:
            symbol = next(iter(candidate_returns), None)
            allocations = {symbol: 1.0} if symbol else {}
            return PortfolioAllocationResult(
                method="mean_variance",
                allocations=allocations,
                expected_return=None,
                expected_volatility=None,
                sharpe=None,
                model_version=_VERSION,
            )
        return await asyncio.to_thread(self._optimize_sync, candidate_returns, risk_free_rate, max_single_weight)

    def _optimize_sync(
        self, candidate_returns: dict[str, list[float]], risk_free_rate: float, max_single_weight: float
    ) -> PortfolioAllocationResult:
        prices_like = pd.DataFrame(candidate_returns)
        mu = expected_returns.mean_historical_return(prices_like, returns_data=True)
        cov = risk_models.sample_cov(prices_like, returns_data=True)

        # max_sharpe can fail two different real ways, both observed running
        # the backtester over real historical windows, not hypothetical:
        # (1) `exceptions.OptimizationError` -- the solver reports infeasible
        #     on a near-singular/degenerate covariance matrix (thin trailing
        #     window, near-zero-variance assets).
        # (2) a plain `ValueError` -- pypfopt refuses outright when no
        #     candidate's expected return exceeds the risk-free rate (a real
        #     bear-market trailing window, not an edge case).
        # Degrade through min_volatility (doesn't need returns > risk-free
        # rate), then equal-weight, rather than let this crash the whole
        # recommendation run (Section 50). `model_version` records which path
        # was actually used.
        solver_errors = (exceptions.OptimizationError, ValueError)
        version_suffix = ""
        try:
            ef = EfficientFrontier(mu, cov, weight_bounds=(0, max_single_weight))
            ef.max_sharpe(risk_free_rate=risk_free_rate)
        except solver_errors:
            try:
                ef = EfficientFrontier(mu, cov, weight_bounds=(0, max_single_weight))
                ef.min_volatility()
                version_suffix = "_min_volatility_fallback"
            except solver_errors:
                return self._equal_weight_result(candidate_returns)

        weights = ef.clean_weights()
        perf_return, perf_vol, perf_sharpe = ef.portfolio_performance(risk_free_rate=risk_free_rate)

        return PortfolioAllocationResult(
            method="mean_variance",
            allocations={k: v for k, v in weights.items() if v > 0},
            expected_return=perf_return,
            expected_volatility=perf_vol,
            sharpe=perf_sharpe,
            model_version=_VERSION + version_suffix,
        )

    def _equal_weight_result(self, candidate_returns: dict[str, list[float]]) -> PortfolioAllocationResult:
        n = len(candidate_returns)
        weight = 1.0 / n
        return PortfolioAllocationResult(
            method="mean_variance",
            allocations={symbol: weight for symbol in candidate_returns},
            expected_return=None,
            expected_volatility=None,
            sharpe=None,
            model_version=_VERSION + "_equal_weight_fallback",
        )
