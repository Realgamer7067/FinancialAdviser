"""Runs the walk-forward backtest (Sections 34-36) over the Nifty50 seed
universe against real historical prices and prints a report. See
app/backtesting/engine.py's docstring for the scope/limitation (technical +
portfolio-optimization only, not fundamentals-driven).

Usage: python scripts/run_backtest.py [period]   # period default "5y"
"""

import asyncio
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtesting.engine import run_backtest  # noqa: E402
from app.providers.nifty50_seed import NIFTY50_SEED  # noqa: E402
from app.services.price_history import fetch_price_history  # noqa: E402

NIFTY_INDEX_TICKER = "^NSEI"


async def main(period: str) -> None:
    symbols = sorted(s.symbol for s in NIFTY50_SEED)
    prices = await fetch_price_history(symbols, period=period)
    prices = prices.dropna(axis=1, thresh=int(len(prices) * 0.9))  # drop symbols with too many gaps
    print(f"Universe: {len(prices.columns)} symbols with usable history, {len(prices)} trading days")

    benchmark = yf.download(NIFTY_INDEX_TICKER, period=period, auto_adjust=True, progress=False)["Close"]
    benchmark = benchmark.iloc[:, 0] if hasattr(benchmark, "columns") else benchmark

    report = await run_backtest(prices, benchmark)
    stats = report.as_dict()

    print("\nBacktest report (walk-forward, monthly rebalance, technical + mean-variance):")
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key:30s} {value:.4f}")
        else:
            print(f"  {key:30s} {value}")
    print(
        "\nCAVEAT: universe is TODAY's Nifty50 constituents applied retroactively -- "
        "survivorship-biased upward, not a point-in-time-accurate historical universe. "
        "Also technical-only ranking (no fundamentals). See app/backtesting/engine.py "
        "docstring before quoting these numbers as a validated strategy result."
    )


if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "5y"
    asyncio.run(main(period))
