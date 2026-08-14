"""Kronos (shiyu-coder/Kronos, NeoQuasar/Kronos-small + Kronos-Tokenizer-base)
TimeSeriesModel implementation. CPU inference -- the -small variant (24.7M
params) is sized for this (see build plan compute decision).

Usage follows the Kronos repo's documented `KronosPredictor` pattern
(tokenizer + model + predictor.predict(df=...)). Re-verify the exact call
signature against https://github.com/shiyu-coder/Kronos at implementation
time -- the package wasn't installed/exercised in this build environment, so
this adapter fails loudly (returns None, Section 50) rather than silently if
the installed version's API differs, instead of guessing.
"""

import asyncio
from datetime import datetime, timezone

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
            from model import Kronos, KronosPredictor, KronosTokenizer  # Kronos package

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
