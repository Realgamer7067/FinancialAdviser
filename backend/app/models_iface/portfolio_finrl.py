"""FinRL DRL PortfolioModel -- real train-once-ship-weights path (Section 12).

Why not a live-trained agent: real FinRL/Stable-Baselines3 PPO training takes
tens of minutes to hours even on a small (~50 stock) universe on CPU --
fundamentally incompatible with a synchronous request-path job, and there are
no pretrained FinRL checkpoints published anywhere to load instead (confirmed
during research for this build). The standard, honest pattern used here:
train once offline (`scripts/train_finrl_agent.py`), ship the checkpoint,
load it for pure inference only. If the checkpoint hasn't been trained yet,
this raises `NotImplementedModel` -- same safe fallback as before, never a
silent fake result (Section 43/74).

The checkpoint is trained on a FIXED universe (all Nifty50 seed symbols, see
the training script). At inference time this queries the full-universe
policy and subsets/renormalizes its weights down to whatever smaller
candidate set the caller actually wants an allocation for -- a legitimate
operation ("what would this policy's full-market view allocate across just
these names"), not an approximation dressed up as something else.

`model_version` always embeds the training timestep count and is treated
everywhere (admin/debug, any future UI) as "lightly trained, not
performance-validated" -- never presented as equivalent to the deterministic
mean-variance path, which remains the one actually driving recommendations.
"""

import asyncio
import json
from pathlib import Path

import numpy as np

from app.backtesting.portfolio_env import softmax
from app.core.config import DATA_DIR
from app.models_iface.base import NotImplementedModel, PortfolioAllocationResult, PortfolioModel
from app.services.price_history import fetch_price_history

CHECKPOINT_DIR = DATA_DIR / "models" / "finrl_ppo_v1"


class FinRLDRLPortfolioModel(PortfolioModel):
    _model = None
    _metadata: dict | None = None

    @staticmethod
    def is_trained() -> bool:
        return (CHECKPOINT_DIR / "model.zip").exists() and (CHECKPOINT_DIR / "metadata.json").exists()

    def _ensure_loaded(self):
        if FinRLDRLPortfolioModel._model is None:
            from stable_baselines3 import PPO  # optional heavy dep, only needed once trained

            FinRLDRLPortfolioModel._metadata = json.loads((CHECKPOINT_DIR / "metadata.json").read_text())
            FinRLDRLPortfolioModel._model = PPO.load(str(CHECKPOINT_DIR / "model.zip"))
        return FinRLDRLPortfolioModel._model, FinRLDRLPortfolioModel._metadata

    async def optimize(
        self,
        candidate_returns: dict[str, list[float]],
        risk_free_rate: float,
        max_single_weight: float,
    ) -> PortfolioAllocationResult:
        if not self.is_trained():
            raise NotImplementedModel(
                "FinRL checkpoint not found -- run scripts/train_finrl_agent.py to produce one."
            )

        model, metadata = await asyncio.to_thread(self._ensure_loaded)
        symbols: list[str] = metadata["symbols"]
        window: int = metadata["window"]

        candidates = set(candidate_returns.keys())
        unknown = candidates - set(symbols)
        if unknown:
            raise NotImplementedModel(f"FinRL agent wasn't trained on: {sorted(unknown)}")

        prices = await fetch_price_history(symbols, period="3mo")
        returns = prices[symbols].pct_change().dropna()
        if len(returns) < window:
            raise NotImplementedModel("Not enough recent price history to build a FinRL observation.")

        obs = returns.tail(window).to_numpy(dtype=np.float32).flatten()
        action, _ = await asyncio.to_thread(model.predict, obs, deterministic=True)
        full_weights = dict(zip(symbols, softmax(action)))

        candidate_weights = {s: full_weights[s] for s in candidates}
        total = sum(candidate_weights.values()) or 1.0
        capped = {s: min(w / total, max_single_weight) for s, w in candidate_weights.items()}
        cap_total = sum(capped.values()) or 1.0
        allocations = {s: round(w / cap_total, 4) for s, w in capped.items() if w / cap_total > 0.001}

        return PortfolioAllocationResult(
            method="finrl_drl",
            allocations=allocations,
            expected_return=None,
            expected_volatility=None,
            sharpe=None,
            model_version=f"finrl_ppo_v1_timesteps{metadata['timesteps']}_LIGHTLY_TRAINED_NOT_VALIDATED",
        )
