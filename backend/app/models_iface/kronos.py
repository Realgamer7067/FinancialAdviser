"""Kronos (shiyu-coder/Kronos, NeoQuasar/Kronos-small + Kronos-Tokenizer-base)
TimeSeriesModel implementation. CPU inference -- the -small variant (24.7M
params) is sized for this (see build plan compute decision).

The Kronos GitHub repo has no setup.py/pyproject.toml -- it is NOT
pip-installable (an earlier version of this project incorrectly pinned
`git+https://github.com/shiyu-coder/Kronos.git` in requirements.txt, which
installs nothing usable). It must be `git clone`d and put on `sys.path`
instead -- see `settings.kronos_repo_path` (set by the Dockerfile / run.sh).
Usage follows the repo's documented `KronosPredictor` pattern (tokenizer +
model + predictor.predict(df=..., x_timestamp=..., y_timestamp=...,
pred_len=..., T=1.0, top_p=0.9, sample_count=1)) -- confirmed against the
repo README and both Hugging Face model cards, and verified against a real
clone + real forecast during development.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.models_iface.base import TimeSeriesForecast, TimeSeriesModel
from app.providers.base import Candle

_HORIZON_TO_BARS = {"7d": 7, "30d": 30, "90d": 90}


class KronosModel(TimeSeriesModel):
    _predictor = None  # lazy-loaded singleton (Section 40)

    def __init__(self):
        self._model_version = f"{settings.kronos_model_id}+{settings.kronos_tokenizer_id}"

    def _ensure_loaded(self):
        if KronosModel._predictor is None:
            repo_path = str(Path(settings.kronos_repo_path).resolve())
            if repo_path not in sys.path:
                sys.path.insert(0, repo_path)
            from model import Kronos, KronosPredictor, KronosTokenizer  # Kronos package (not pip-installed)

            tokenizer = KronosTokenizer.from_pretrained(settings.kronos_tokenizer_id)
            model = Kronos.from_pretrained(settings.kronos_model_id)
            KronosModel._predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
        return KronosModel._predictor

    async def forecast(self, symbol: str, candles: list[Candle], horizon: str) -> TimeSeriesForecast | None:
        bars = _HORIZON_TO_BARS.get(horizon)
        if bars is None or len(candles) < 30:
            return None  # insufficient history -- don't guess (Section 50)

        try:
            result = await asyncio.to_thread(self._run, candles, bars)
        except Exception:
            # Model unavailable / package API mismatch -- caller must treat this
            # as a missing signal, not crash the whole pipeline (Section 50).
            return None

        last_close = candles[-1].close
        predicted_close = result
        predicted_return = (predicted_close - last_close) / last_close
        if predicted_return > 0.01:
            direction = "bullish"
        elif predicted_return < -0.01:
            direction = "bearish"
        else:
            direction = "neutral"

        return TimeSeriesForecast(
            forecast_horizon=horizon,
            direction=direction,
            predicted_return=predicted_return,
            confidence=0.5,  # placeholder until calibrated against backtest error (Section 36)
            input_timeframe=f"{len(candles)}_daily_bars",
            model_name="Kronos",
            model_version=self._model_version,
        )

    def _run(self, candles: list[Candle], bars: int) -> float:
        predictor = self._ensure_loaded()
        df = pd.DataFrame(
            [{"open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles]
        )
        x_timestamp = pd.Series([c.timestamp for c in candles])
        last_ts = candles[-1].timestamp
        y_timestamp = pd.Series(
            [last_ts + (i + 1) * (last_ts - candles[-2].timestamp) for i in range(bars)]
        )
        pred_df = predictor.predict(
            df=df, x_timestamp=x_timestamp, y_timestamp=y_timestamp, pred_len=bars, T=1.0, top_p=0.9, sample_count=1
        )
        return float(pred_df["close"].iloc[-1])
