"""Trains the FinRL portfolio-allocation PPO agent offline, once, and ships
the checkpoint -- see app/models_iface/portfolio_finrl.py's docstring for why
this can't train live in the request path (CPU-only, tens of minutes+ per
run). The `TIMESTEPS` below is deliberately light (a few minutes on CPU) --
this produces a REAL trained checkpoint, not a fabricated one, but it is NOT
a performance-validated trading strategy. Every place this checkpoint's
output surfaces (admin/debug, model_version string) says so explicitly.
Increase TIMESTEPS and re-run for a more seriously trained agent -- there's
nothing else to change.

Usage: python scripts/train_finrl_agent.py
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtesting.portfolio_env import PortfolioAllocationEnv  # noqa: E402
from app.core.config import DATA_DIR  # noqa: E402
from app.providers.nifty50_seed import NIFTY50_SEED  # noqa: E402
from app.services.price_history import fetch_price_history  # noqa: E402

TIMESTEPS = 30_000  # light/fast, CPU, a few minutes -- see module docstring
WINDOW = 20
EPISODE_LENGTH = 60
PRICE_HISTORY_PERIOD = "2y"
OUTPUT_DIR = DATA_DIR / "models" / "finrl_ppo_v1"


async def _load_returns():
    symbols = sorted(s.symbol for s in NIFTY50_SEED)
    prices = await fetch_price_history(symbols, period=PRICE_HISTORY_PERIOD)
    usable_symbols = [s for s in symbols if s in prices.columns and prices[s].notna().sum() > WINDOW + EPISODE_LENGTH]
    dropped = sorted(set(symbols) - set(usable_symbols))
    if dropped:
        print(f"Dropping {len(dropped)} symbols with insufficient price history: {dropped}")
    prices = prices[usable_symbols].dropna()
    returns = prices.pct_change().dropna()
    return returns


def main() -> None:
    from stable_baselines3 import PPO  # deferred -- optional heavy dependency

    returns = asyncio.run(_load_returns())
    print(f"Training universe: {len(returns.columns)} symbols, {len(returns)} trading days")

    env = PortfolioAllocationEnv(returns, window=WINDOW, episode_length=EPISODE_LENGTH, seed=42)
    model = PPO("MlpPolicy", env, verbose=1, seed=42)
    model.learn(total_timesteps=TIMESTEPS)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_DIR / "model.zip"))

    metadata = {
        "symbols": list(returns.columns),
        "window": WINDOW,
        "episode_length": EPISODE_LENGTH,
        "timesteps": TIMESTEPS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "price_history_period": PRICE_HISTORY_PERIOD,
        "note": "Lightly trained for demonstration -- not performance-validated. See scripts/train_finrl_agent.py.",
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Saved checkpoint + metadata to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
