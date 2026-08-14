"""FinRL DRL PortfolioModel -- intentionally NOT implemented in this MVP.

Real FinRL agent training (PPO/A2C/SAC via Stable-Baselines3) needs GPU-hours
of walk-forward training to be a real signal; on CPU-only hardware it would
either be too slow to run per-request or produce an undertrained agent while
the UI claims "FinRL integrated" -- exactly what Section 74 forbids. Use
`MeanVariancePortfolioModel` for the working MVP path.

To wire this in for real: train offline (see FinRL-Tutorials portfolio
allocation notebooks), save the trained policy under
`data/models/finrl_ppo_v1/`, and load it here instead of raising.
"""

from app.models_iface.base import NotImplementedModel, PortfolioAllocationResult, PortfolioModel


class FinRLDRLPortfolioModel(PortfolioModel):
    async def optimize(
        self,
        candidate_returns: dict[str, list[float]],
        risk_free_rate: float,
        max_single_weight: float,
    ) -> PortfolioAllocationResult:
        raise NotImplementedModel(
            "FinRL DRL portfolio agent is not wired in this MVP -- use MeanVariancePortfolioModel."
        )
