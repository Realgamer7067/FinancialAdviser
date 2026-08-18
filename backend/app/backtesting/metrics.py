"""Deterministic backtest performance metrics (Section 34). Plain math over a
realized-return series -- no model involved, nothing to fabricate."""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def annualized_return(returns: pd.Series, periods_per_year: int) -> float:
    if len(returns) == 0:
        return 0.0
    cumulative = (1 + returns).prod()
    years = len(returns) / periods_per_year
    return float(cumulative ** (1 / years) - 1) if years > 0 else 0.0


def annualized_volatility(returns: pd.Series, periods_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float, periods_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    std = excess.std()
    if std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, risk_free_rate: float, periods_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    # Standard downside-deviation formula: RMS of min(excess, 0) over the FULL
    # series (not std() of just the negative subset, which understates risk
    # and -- with a single downside period -- divides by a NaN std(ddof=1)).
    downside_deviation = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2)))
    if not downside_deviation:
        return 0.0
    return float(excess.mean() / downside_deviation * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    return float(drawdown.min())


def hit_rate(returns: pd.Series) -> float:
    """Fraction of periods with a positive return."""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).mean())


class BacktestReport:
    def __init__(self, returns: pd.Series, benchmark_returns: pd.Series, risk_free_rate: float, periods_per_year: int = TRADING_DAYS_PER_YEAR):
        self.returns = returns
        self.benchmark_returns = benchmark_returns
        self.periods_per_year = periods_per_year
        self.risk_free_rate = risk_free_rate

    def as_dict(self) -> dict:
        return {
            "periods": len(self.returns),
            "annualized_return": annualized_return(self.returns, self.periods_per_year),
            "annualized_volatility": annualized_volatility(self.returns, self.periods_per_year),
            "sharpe": sharpe_ratio(self.returns, self.risk_free_rate, self.periods_per_year),
            "sortino": sortino_ratio(self.returns, self.risk_free_rate, self.periods_per_year),
            "max_drawdown": max_drawdown(self.returns),
            "hit_rate": hit_rate(self.returns),
            "benchmark_annualized_return": annualized_return(self.benchmark_returns, self.periods_per_year),
            "benchmark_max_drawdown": max_drawdown(self.benchmark_returns),
        }
