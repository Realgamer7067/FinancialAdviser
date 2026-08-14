"""Gymnasium portfolio-allocation environment used only to train the FinRL
PPO agent offline (see scripts/train_finrl_agent.py). Deliberately simple
(single-step-ahead contextual allocation over a rolling window, long-only,
fully invested, no transaction costs) -- this is a documented MVP training
setup, not a claim of a validated trading strategy (Section 74)."""

import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:  # pragma: no cover -- only needed for training/inference, not the core app
    gym = None
    spaces = None


class PortfolioAllocationEnv(gym.Env if gym else object):
    """Observation: the trailing `window` daily returns for every symbol,
    flattened (window * n_assets). Action: n_assets raw scores, softmax'd
    into long-only weights summing to 1. Reward: that day's realized
    portfolio log return. Episodes are `episode_length` trading days long,
    starting at a random point in the historical returns so training sees a
    variety of market regimes."""

    metadata = {"render_modes": []}

    def __init__(self, returns: pd.DataFrame, window: int = 20, episode_length: int = 60, seed: int | None = None):
        if gym is None:
            raise ImportError("gymnasium is required for PortfolioAllocationEnv")
        super().__init__()
        self.symbols = list(returns.columns)
        self.returns = returns.to_numpy(dtype=np.float32)
        self.n_assets = len(self.symbols)
        self.window = window
        self.episode_length = episode_length
        self._rng = np.random.default_rng(seed)

        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(self.window * self.n_assets,), dtype=np.float32
        )
        self.action_space = spaces.Box(low=-5.0, high=5.0, shape=(self.n_assets,), dtype=np.float32)

        self._t = 0  # index into self.returns of the current (not-yet-realized) day

    def _obs(self) -> np.ndarray:
        window_slice = self.returns[self._t - self.window : self._t]
        return window_slice.flatten()

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        max_start = len(self.returns) - self.episode_length - 1
        self._t = int(self._rng.integers(self.window, max(self.window + 1, max_start)))
        self._steps_taken = 0
        return self._obs(), {}

    def step(self, action: np.ndarray):
        weights = softmax(action)
        day_returns = self.returns[self._t]
        portfolio_return = float(np.dot(weights, day_returns))
        reward = float(np.log1p(np.clip(portfolio_return, -0.99, None)))

        self._t += 1
        self._steps_taken += 1
        terminated = False
        truncated = self._steps_taken >= self.episode_length or self._t >= len(self.returns) - 1
        obs = self._obs() if not truncated else np.zeros(self.observation_space.shape, dtype=np.float32)
        return obs, reward, terminated, truncated, {"weights": weights}


def softmax(x: np.ndarray) -> np.ndarray:
    shifted = x - np.max(x)
    exp = np.exp(shifted)
    return exp / exp.sum()
