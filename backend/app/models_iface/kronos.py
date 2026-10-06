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

`predictor.predict(..., sample_count=N)` averages the N draws internally
before returning (vendor/kronos/model/kronos.py:465-467: `preds =
np.mean(preds, axis=1)`) -- it hands back one mean path, never the N
individual paths. To get a real distribution of outcomes (and therefore a
real confidence/agreement signal instead of a hardcoded placeholder), this
wrapper calls `predict()` `settings.kronos_sample_count` times independently,
each with its own deterministic seed, and derives direction/return/agreement
from that sample set (docs/V2-RETHINK.md section 2a).
"""

import asyncio
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.backtesting.kronos_calibration import lookup_confidence
from app.core.config import settings
from app.models_iface.base import TimeSeriesForecast, TimeSeriesModel
from app.providers.base import Candle

_HORIZON_TO_BARS = {"7d": 7, "30d": 30, "90d": 90}
_NEUTRAL_BAND = 0.01  # +/-1% median return still counts as neutral


class KronosModel(TimeSeriesModel):
    _predictor = None  # lazy-loaded singleton (Section 40)
    _T = 1.0
    _top_p = 0.9

    def __init__(self):
        sc = settings.kronos_sample_count
        # Sampling settings are part of model identity (docs/V2-RETHINK.md
        # section 5 caching convention) -- changing sample_count/T/top_p
        # invalidates any calibration table keyed on the old version.
        self._model_version = (
            f"{settings.kronos_model_id}+{settings.kronos_tokenizer_id}"
            f"+sc{sc}+T{self._T}+p{self._top_p}"
        )

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
        try:
            return await self.forecast_strict(symbol, candles, horizon)
        except Exception:
            # Model unavailable / package API mismatch -- caller must treat this
            # as a missing signal, not crash the whole pipeline (Section 50).
            return None

    async def forecast_strict(self, symbol: str, candles: list[Candle], horizon: str) -> TimeSeriesForecast | None:
        """Same as forecast() but lets model/package/weights errors propagate. A silent None for a missing vendor
        path or missing weights is indistinguishable from "no signal" forever, so callers that need to know WHY
        (the nightly forecast job) use this. Returns None only for an unknown horizon or too little history."""
        bars = _HORIZON_TO_BARS.get(horizon)
        if bars is None or len(candles) < 30:
            return None  # insufficient history -- don't guess (Section 50)

        sample_closes = await asyncio.to_thread(self._run, symbol, candles, bars, horizon)

        last_close = candles[-1].close
        sample_returns = np.array([(c - last_close) / last_close for c in sample_closes])
        predicted_return = float(np.median(sample_returns))
        p10 = float(np.percentile(sample_returns, 10))
        p90 = float(np.percentile(sample_returns, 90))

        median_sign = 1 if predicted_return > 0 else (-1 if predicted_return < 0 else 0)
        if median_sign == 0:
            direction_agreement = float(np.mean(sample_returns == 0))
        else:
            direction_agreement = float(np.mean(np.sign(sample_returns) == median_sign))

        if predicted_return > _NEUTRAL_BAND:
            direction = "bullish"
        elif predicted_return < -_NEUTRAL_BAND:
            direction = "bearish"
        else:
            direction = "neutral"

        try:
            confidence = lookup_confidence(
                model_version=self._model_version, horizon=horizon, direction_agreement=direction_agreement
            )
        except Exception:
            # A corrupt/unexpected calibration artifact must degrade to
            # "uncalibrated" (None), never crash the forecast call or fabricate
            # a confidence (Section 50) -- lookup_confidence already guards
            # its own known malformed-input shapes, this is a last-resort
            # backstop for anything it doesn't.
            confidence = None

        return TimeSeriesForecast(
            forecast_horizon=horizon,
            direction=direction,
            predicted_return=predicted_return,
            predicted_return_p10=p10,
            predicted_return_p90=p90,
            direction_agreement=direction_agreement,
            sample_count=len(sample_closes),
            confidence=confidence,  # None until a calibration table exists (Section 50: never guess)
            input_timeframe=f"{len(candles)}_daily_bars",
            model_name="Kronos",
            model_version=self._model_version,
        )

    def _run(self, symbol: str, candles: list[Candle], bars: int, horizon: str) -> list[float]:
        predictor = self._ensure_loaded()
        df = pd.DataFrame(
            [{"open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles]
        )
        x_timestamp = pd.Series([c.timestamp for c in candles])
        last_ts = candles[-1].timestamp
        y_timestamp = pd.Series(
            [last_ts + (i + 1) * (last_ts - candles[-2].timestamp) for i in range(bars)]
        )

        import torch

        closes: list[float] = []
        for sample_index in range(settings.kronos_sample_count):
            seed_material = f"{symbol}|{horizon}|{last_ts.isoformat()}|{sample_index}|{self._model_version}"
            seed = int(hashlib.sha256(seed_material.encode()).hexdigest(), 16) % (2**32)
            torch.manual_seed(seed)
            pred_df = predictor.predict(
                df=df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=bars,
                T=self._T,
                top_p=self._top_p,
                sample_count=1,
            )
            closes.append(float(pred_df["close"].iloc[-1]))
        return closes
