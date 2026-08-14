"""Deterministic technical-indicator engine (Section 9). Produces evidence,
never a verdict -- the council/scoring layer decides what the numbers mean."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pandas_ta_classic as ta

from app.providers.base import Candle


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        [{"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles]
    )
    return df.sort_values("timestamp").reset_index(drop=True)


def _last_or_none(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    value = series.iloc[-1]
    return float(value) if pd.notna(value) else None


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    running_max = close.cummax()
    drawdown = (close - running_max) / running_max
    return float(drawdown.min())


def _trend_label(sma_50: float | None, sma_200: float | None) -> str | None:
    if sma_50 is None or sma_200 is None:
        return None
    if sma_50 > sma_200 * 1.01:
        return "bullish"
    if sma_50 < sma_200 * 0.99:
        return "bearish"
    return "neutral"


def compute_technical_features(
    candles: list[Candle], timeframe: str, benchmark_candles: list[Candle] | None = None
) -> dict | None:
    """Returns a dict matching the TechnicalFeatures model columns, or None if
    there isn't even enough history to compute anything. Any single indicator
    that can't be computed is left None -- UNKNOWN, never guessed (Section 8/9)."""

    if len(candles) < 2:
        return None  # not enough history for any indicator -- don't return a partial/truthy dict

    df = _candles_to_df(candles)
    close = df["close"]

    sma_20 = _last_or_none(ta.sma(close, length=20))
    sma_50 = _last_or_none(ta.sma(close, length=50))
    sma_200 = _last_or_none(ta.sma(close, length=200))
    ema_12 = _last_or_none(ta.ema(close, length=12))
    ema_26 = _last_or_none(ta.ema(close, length=26))
    rsi_14 = _last_or_none(ta.rsi(close, length=14))

    macd_df = ta.macd(close)
    macd = macd_hist = macd_signal = None
    if macd_df is not None and not macd_df.empty:
        macd = _last_or_none(macd_df.iloc[:, 0])
        macd_hist = _last_or_none(macd_df.iloc[:, 1])
        macd_signal = _last_or_none(macd_df.iloc[:, 2])

    bb_df = ta.bbands(close, length=20)
    bb_upper = bb_lower = None
    if bb_df is not None and not bb_df.empty:
        bb_lower = _last_or_none(bb_df.iloc[:, 0])
        bb_upper = _last_or_none(bb_df.iloc[:, 2])

    atr_14 = _last_or_none(ta.atr(df["high"], df["low"], df["close"], length=14))

    adx_14 = None
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx_df is not None and not adx_df.empty:
        adx_14 = _last_or_none(adx_df.iloc[:, 0])

    daily_returns = close.pct_change().dropna()
    volatility_30d = None
    if len(daily_returns) >= 5:
        window = daily_returns.tail(30)
        volatility_30d = float(window.std() * np.sqrt(252))

    drawdown_1y = _max_drawdown(close.tail(252))

    beta = None
    if benchmark_candles and len(benchmark_candles) >= 30:
        bench_df = _candles_to_df(benchmark_candles)
        bench_returns = bench_df["close"].pct_change().dropna()
        n = min(len(daily_returns), len(bench_returns))
        if n >= 20:
            stock_r = daily_returns.tail(n).reset_index(drop=True)
            bench_r = bench_returns.tail(n).reset_index(drop=True)
            cov = np.cov(stock_r, bench_r)[0][1]
            var = np.var(bench_r)
            beta = float(cov / var) if var > 0 else None

    return {
        "timeframe": timeframe,
        "as_of": datetime.now(timezone.utc),
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "rsi_14": rsi_14,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "atr_14": atr_14,
        "adx_14": adx_14,
        "volatility_30d": volatility_30d,
        "drawdown_1y": drawdown_1y,
        "beta": beta,
        "trend": _trend_label(sma_50, sma_200),
        "computed_at": datetime.now(timezone.utc),
    }
