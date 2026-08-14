"""Shared real historical-price fetch for offline dev-time processes
(FinRL training, backtesting) -- these run outside the live request pipeline
and shouldn't depend on DEMO_MODE's synthetic candles (Section 34: backtests
must use real data, not fabricated). Yahoo Finance, via `yfinance`, gives us
free multi-symbol historical daily closes with no auth -- same provisional
MVP tradeoff already made for fundamentals (see app/providers/fundamentals.py)."""

import asyncio

import pandas as pd
import yfinance as yf


def _download_sync(tickers: list[str], period: str) -> pd.DataFrame:
    raw = yf.download(tickers, period=period, auto_adjust=True, progress=False, threads=True)
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        # yfinance collapses to a single-level column set when len(tickers) == 1
        closes = raw[["Close"]]
        closes.columns = tickers
    return closes.dropna(how="all")


async def fetch_price_history(symbols: list[str], period: str = "2y") -> pd.DataFrame:
    """Returns a wide DataFrame (date index, one column per symbol) of daily
    close prices. Columns with no data at all are dropped -- callers must
    handle a possibly-smaller symbol set than requested (Section 8: never
    fill in missing data)."""
    tickers = [f"{s}.NS" for s in symbols]
    df = await asyncio.to_thread(_download_sync, tickers, period)
    df.columns = [c.replace(".NS", "") for c in df.columns]
    return df
