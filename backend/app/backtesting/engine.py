"""Walk-forward backtest (Sections 34-36). Strictly no look-ahead: at each
rebalance date, ranking/allocation use only price data up to and including
that date; realized returns come from the actual subsequent trading days.

Scope/limitations, stated plainly rather than hidden:

- This backtests the *technical + portfolio-optimization* half of the
  pipeline only. Fundamentals here are current-snapshot-only (yfinance
  `.info` has no historical point-in-time API), so a fundamentals-driven
  historical score can't be reconstructed without survivorship/look-ahead
  bias -- rather than fake it, this backtest ranks candidates by a
  price-only technical score (SMA/RSI/MACD -- no ATR/ADX/Bollinger, which
  need intraday high/low we don't have from daily close-only history) and
  leaves fundamental backtesting as a real future milestone once a
  point-in-time fundamentals source is wired in.
- SURVIVORSHIP BIAS (real, not fully corrected): the tradeable universe here
  is *today's* Nifty50 constituents (`app/providers/nifty50_seed.py`)
  applied retroactively across the whole backtest period. A stock has to
  have performed well to still be in today's Nifty50 -- so results are
  optimistically biased versus what a real point-in-time Nifty50 membership
  history would show. Section 34 calls this out as something to avoid;
  fixing it properly needs NSE's historical (not just current) semi-annual
  constituent lists, which weren't sourced for this build. Report this
  caveat alongside any number this module produces -- never state a Sharpe/
  return figure from here without it.
"""

import asyncio

import pandas as pd
import pandas_ta_classic as ta

from app.backtesting.metrics import BacktestReport
from app.models_iface.portfolio_mvo import MeanVariancePortfolioModel
from app.scoring.evidence import TechnicalEvidence
from app.scoring.subscores import technical_score

DEFAULT_LOOKBACK_DAYS = 252  # ~1 trading year of history required before the first rebalance
DEFAULT_HOLDING_RETURNS_WINDOW = 60  # trailing days fed to the portfolio optimizer at each rebalance
DEFAULT_TOP_K = 6


def _technical_evidence_from_prices(close: pd.Series) -> TechnicalEvidence | None:
    if len(close) < 60:
        return None
    sma_50 = ta.sma(close, length=50)
    sma_200 = ta.sma(close, length=200) if len(close) >= 200 else None
    rsi_14 = ta.rsi(close, length=14)
    macd_df = ta.macd(close)

    sma_50_last = float(sma_50.iloc[-1]) if sma_50 is not None and pd.notna(sma_50.iloc[-1]) else None
    sma_200_last = float(sma_200.iloc[-1]) if sma_200 is not None and pd.notna(sma_200.iloc[-1]) else None
    trend = None
    if sma_50_last is not None and sma_200_last is not None:
        if sma_50_last > sma_200_last * 1.01:
            trend = "bullish"
        elif sma_50_last < sma_200_last * 0.99:
            trend = "bearish"
        else:
            trend = "neutral"

    rsi_last = float(rsi_14.iloc[-1]) if rsi_14 is not None and pd.notna(rsi_14.iloc[-1]) else None
    macd_hist_last = None
    if macd_df is not None and not macd_df.empty and pd.notna(macd_df.iloc[-1, 1]):
        macd_hist_last = float(macd_df.iloc[-1, 1])

    daily_returns = close.pct_change().dropna()
    volatility_30d = float(daily_returns.tail(30).std() * (252**0.5)) if len(daily_returns) >= 5 else None

    return TechnicalEvidence(
        rsi_14=rsi_last, trend=trend, volatility_30d=volatility_30d, drawdown_1y=None, macd_hist=macd_hist_last
    )


async def run_backtest(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    rebalance_freq: str = "MS",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    top_k: int = DEFAULT_TOP_K,
    holding_returns_window: int = DEFAULT_HOLDING_RETURNS_WINDOW,
    risk_free_rate: float = 0.07,
    max_single_weight: float = 0.25,
) -> BacktestReport:
    prices = prices.sort_index().dropna(how="all")
    rebalance_dates = pd.date_range(prices.index[lookback_days], prices.index[-1], freq=rebalance_freq)
    rebalance_dates = [d for d in rebalance_dates if d in prices.index] or [prices.index[lookback_days]]

    portfolio_model = MeanVariancePortfolioModel()
    period_returns: list[pd.Series] = []

    for i, reb_date in enumerate(rebalance_dates):
        hold_until = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else prices.index[-1]
        history = prices.loc[:reb_date]  # strictly no look-ahead past reb_date

        scores = {}
        for symbol in prices.columns:
            close = history[symbol].dropna()
            evidence = _technical_evidence_from_prices(close)
            score = technical_score(evidence)
            if score is not None:
                scores[symbol] = score
        if not scores:
            continue

        top_symbols = sorted(scores, key=scores.get, reverse=True)[:top_k]
        candidate_returns = {}
        for symbol in top_symbols:
            returns = history[symbol].dropna().pct_change().dropna().tail(holding_returns_window)
            if len(returns) >= 10:
                candidate_returns[symbol] = returns.tolist()
        if not candidate_returns:
            continue

        allocation = await portfolio_model.optimize(candidate_returns, risk_free_rate, max_single_weight)
        if not allocation.allocations:
            continue

        holding_period = prices.loc[reb_date:hold_until].iloc[1:]  # returns realized AFTER the rebalance date
        if holding_period.empty:
            continue
        holding_returns = holding_period[list(allocation.allocations.keys())].pct_change().dropna()
        weights = pd.Series(allocation.allocations)
        period_returns.append(holding_returns.mul(weights, axis=1).sum(axis=1))

    strategy_returns = pd.concat(period_returns).sort_index() if period_returns else pd.Series(dtype=float)
    benchmark_returns = benchmark_prices.loc[strategy_returns.index.min() :].pct_change().dropna() if len(strategy_returns) else pd.Series(dtype=float)

    return BacktestReport(strategy_returns, benchmark_returns, risk_free_rate)
