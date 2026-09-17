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
            if symbol is None:
                return PortfolioAllocationResult(
                    method="no_candidates",
                    allocations={},
                    unallocated_cash=1.0,
                    expected_return=None,
                    expected_volatility=None,
                    sharpe=None,
                    model_version=_VERSION,
                )
            # A single candidate must still respect the concentration cap --
            # 100% in one name is exactly the kind of violation the cap
            # exists to prevent (Section 20). The rest is explicit cash. No
            # covariance/solver is involved with only one asset, so this
            # isn't really "mean_variance" either -- label it honestly, same
            # reasoning as the equal-weight fallback below.
            weight = min(1.0, max_single_weight)
            return PortfolioAllocationResult(
                method="single_candidate",
                allocations={symbol: weight},
                unallocated_cash=1.0 - weight,
                expected_return=None,
                expected_volatility=None,
                sharpe=None,
                model_version=_VERSION,
            )
        return await asyncio.to_thread(self._optimize_sync, candidate_returns, risk_free_rate, max_single_weight)

    def _optimize_sync(
        self, candidate_returns: dict[str, list[float] | pd.Series], risk_free_rate: float, max_single_weight: float
    ) -> PortfolioAllocationResult:
        # Candidates' return series can differ -- e.g. a symbol backed by a
        # shorter cache vs. another pulled fresh with a longer history window,
        # or a mid-window gap (stale cache day, trading halt) that isn't
        # shared by every candidate. A plain positional truncation to the
        # shortest length used to assume "all series end today, so trimming
        # the front stays aligned" -- true only when there's no INTERNAL gap,
        # which isn't guaranteed. When callers pass a date-indexed Series
        # (recommendation_pipeline.py does), align by actual trading date --
        # an inner join on the DatetimeIndex only ever compares genuinely
        # overlapping days (docs/V2-RETHINK.md P1). Plain lists carry no date
        # info, so they keep the old "trim to shortest, keep the tail" rule.
        if all(isinstance(v, pd.Series) and isinstance(v.index, pd.DatetimeIndex) for v in candidate_returns.values()):
            prices_like = pd.concat(candidate_returns, axis=1, join="inner")
        else:
            min_len = min(len(v) for v in candidate_returns.values())
            aligned_returns = {k: (v.tail(min_len) if isinstance(v, pd.Series) else v[-min_len:]) for k, v in candidate_returns.items()}
            prices_like = pd.DataFrame({k: pd.Series(v).reset_index(drop=True) for k, v in aligned_returns.items()})
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
                return self._equal_weight_result(candidate_returns, max_single_weight)

        # weight_bounds=(0, max_single_weight) already constrains the solver
        # itself, so no post-hoc capping is needed on this path -- only the
        # fallback paths below construct weights by hand.
        weights = ef.clean_weights()
        allocations = {k: v for k, v in weights.items() if v > 0}
        perf_return, perf_vol, perf_sharpe = ef.portfolio_performance(risk_free_rate=risk_free_rate)

        # `method` used to be hardcoded "mean_variance" on every path,
        # including the min_volatility fallback -- only `model_version`
        # carried the real distinction. A caller reading just `method` (the
        # frontend does) couldn't tell max_sharpe genuinely succeeded from a
        # degraded fallback. Honest per-path label now (found 2026-09-16
        # reviewing why the portfolio page always said "mean variance" even
        # when expected_return/volatility/sharpe were legitimately null).
        method = "mean_variance" if not version_suffix else "mean_variance_min_volatility_fallback"

        return PortfolioAllocationResult(
            method=method,
            allocations=allocations,
            unallocated_cash=max(0.0, 1.0 - sum(allocations.values())),
            expected_return=perf_return,
            expected_volatility=perf_vol,
            sharpe=perf_sharpe,
            model_version=_VERSION + version_suffix,
        )

    def _equal_weight_result(
        self, candidate_returns: dict[str, list[float]], max_single_weight: float
    ) -> PortfolioAllocationResult:
        n = len(candidate_returns)
        # An equal 1/n split can itself exceed the cap (e.g. 3 candidates,
        # 25% cap: 1/3 > 0.25) -- every candidate here is symmetric, so
        # capping each at min(1/n, max_single_weight) and leaving the
        # remainder as explicit cash is correct without needing an iterative
        # water-filling redistribution (Section 20: never violate the cap,
        # never silently drop the shortfall).
        weight = min(1.0 / n, max_single_weight)
        allocations = {symbol: weight for symbol in candidate_returns}
        return PortfolioAllocationResult(
            method="equal_weight_fallback",
            allocations=allocations,
            unallocated_cash=max(0.0, 1.0 - sum(allocations.values())),
            expected_return=None,
            expected_volatility=None,
            sharpe=None,
            model_version=_VERSION + "_equal_weight_fallback",
        )
