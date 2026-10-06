"""Kronos forecast aggregation math (docs/V2-RETHINK.md section 2a). Never
exercises real inference/HF weights -- `_run` is monkeypatched, matching the
existing pattern used to fake Kronos out in test_pipeline_smoke.py."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import torch

from app.core.config import settings
from app.models_iface.kronos import KronosModel
from app.providers.base import Candle


def _candles(n=40, last_close=100.0):
    now = datetime.now(timezone.utc)
    return [
        Candle(
            timestamp=now - timedelta(days=n - i),
            open=last_close,
            high=last_close,
            low=last_close,
            close=last_close,
            volume=1000,
            source="test",
            retrieved_at=now,
            adjusted=False,
        )
        for i in range(n)
    ]


async def test_forecast_aggregates_samples_into_median_and_percentile_band(monkeypatch):
    # 8 sampled terminal closes -> returns of -5%, -3%, -1%, 1%, 2%, 3%, 4%, 6%
    sample_closes = [95, 97, 99, 101, 102, 103, 104, 106]
    monkeypatch.setattr(KronosModel, "_run", lambda self, symbol, candles, bars, horizon: sample_closes)

    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(last_close=100.0), "30d")

    assert forecast is not None
    assert forecast.sample_count == 8
    # median of the 8 returns (-5,-3,-1,1,2,3,4,6) -> midpoint of 1% and 2%
    assert forecast.predicted_return == pytest.approx(0.015, abs=1e-6)
    assert forecast.predicted_return_p10 < forecast.predicted_return < forecast.predicted_return_p90
    # median sign is positive; 5 of 8 samples (1,2,3,4,6) are also positive
    assert forecast.direction_agreement == pytest.approx(5 / 8)
    assert forecast.direction == "bullish"
    # no calibration table exists for this made-up model_version -- must be
    # None, never a guessed placeholder (Section 50).
    assert forecast.confidence is None


async def test_forecast_neutral_band_is_wider_than_a_single_bar_move(monkeypatch):
    sample_closes = [100.3, 100.5, 100.2, 100.4, 100.1, 100.6, 100.2, 100.3]  # all < 1% move
    monkeypatch.setattr(KronosModel, "_run", lambda self, symbol, candles, bars, horizon: sample_closes)

    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(last_close=100.0), "30d")

    assert forecast is not None
    assert forecast.direction == "neutral"


async def test_forecast_returns_none_on_insufficient_history():
    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(n=10), "30d")
    assert forecast is None


async def test_forecast_returns_none_when_run_raises(monkeypatch):
    def _boom(self, symbol, candles, bars, horizon):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(KronosModel, "_run", _boom)
    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(), "30d")
    assert forecast is None


async def test_forecast_returns_none_for_exactly_29_candles():
    # boundary check: 30 is the documented minimum (Section 50) -- one short
    # of it must still return None, not silently proceed.
    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(n=29), "30d")
    assert forecast is None


async def test_forecast_returns_none_for_unknown_horizon():
    # a horizon string absent from _HORIZON_TO_BARS must also short-circuit
    # to None rather than crashing on a missing bars value.
    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(), "1d")
    assert forecast is None


class _FakePredictor:
    """Stands in for the real vendor `KronosPredictor` one layer below `_run`.
    Returns a deterministic terminal close derived from the call index so the
    test can prove each of the `sample_count` calls is independent (not the
    same draw reused) and that the DataFrame handed in reflects the real
    candle/bars data, not a bypassed stub."""

    def __init__(self, closes_by_call):
        self.closes_by_call = closes_by_call
        self.calls = []

    def predict(self, *, df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count):
        self.calls.append(
            {
                "df": df,
                "x_timestamp": x_timestamp,
                "y_timestamp": y_timestamp,
                "pred_len": pred_len,
                "T": T,
                "top_p": top_p,
                "sample_count": sample_count,
            }
        )
        close = self.closes_by_call[len(self.calls) - 1]
        return pd.DataFrame({"close": [close]})


async def test_forecast_via_stubbed_predictor_calls_it_sample_count_times(monkeypatch, tmp_path):
    # hermetic: this model_version is the REAL settings-derived one (unlike
    # the other tests here, which use a made-up version via _run stubs), so
    # pin the calibration root to an empty tmp dir -- otherwise this test
    # would silently start exercising a different code path the day a real
    # calibration artifact lands in the repo for this exact model_version.
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    """Exercises _ensure_loaded -> predictor.predict, one layer deeper than the
    other tests in this file, which all monkeypatch `_run` directly. Proves
    the wrapper actually performs `settings.kronos_sample_count` independent
    predictor invocations (not a single call whose result is reused), that the
    horizon->bars mapping reaches `predict(pred_len=...)`, that the terminal
    close (`df["close"].iloc[-1]`) is extracted per call, and that the
    percentile/direction_agreement math downstream is computed from those real
    per-call outputs."""
    last_close = 100.0
    # 8 distinct terminal closes -> returns of -5,-3,-1,1,2,3,4,6 % (matches
    # the existing _run-level test's fixture so the aggregation math can be
    # cross-checked against a known-good expectation).
    closes_by_call = [95.0, 97.0, 99.0, 101.0, 102.0, 103.0, 104.0, 106.0]
    assert len(closes_by_call) == settings.kronos_sample_count

    fake_predictor = _FakePredictor(closes_by_call)
    monkeypatch.setattr(KronosModel, "_ensure_loaded", lambda self: fake_predictor)

    model = KronosModel()
    candles = _candles(last_close=last_close)
    forecast = await model.forecast("TESTCO", candles, "30d")

    assert forecast is not None
    # the predictor was invoked once per configured sample, independently --
    # not once with the result reused settings.kronos_sample_count times.
    assert len(fake_predictor.calls) == settings.kronos_sample_count == 8
    # each call requested a single internal sample -- the wrapper does its own
    # outer-loop sampling instead of delegating averaging to the vendor call.
    assert all(call["sample_count"] == 1 for call in fake_predictor.calls)
    # horizon "30d" -> _HORIZON_TO_BARS["30d"] == 30 must reach predict(pred_len=...)
    assert all(call["pred_len"] == 30 for call in fake_predictor.calls)
    assert all(len(call["y_timestamp"]) == 30 for call in fake_predictor.calls)
    # the input df handed to predict reflects the real candle history, not a
    # bypassed/empty stub.
    assert len(fake_predictor.calls[0]["df"]) == len(candles)

    assert forecast.sample_count == 8
    assert forecast.predicted_return == pytest.approx(0.015, abs=1e-6)
    assert forecast.predicted_return_p10 < forecast.predicted_return < forecast.predicted_return_p90
    assert forecast.direction_agreement == pytest.approx(5 / 8)
    assert forecast.direction == "bullish"
    # no calibration table exists in the pinned-empty tmp_path root -- must be
    # None, never a guessed placeholder (Section 50), same as the _run-level test.
    assert forecast.confidence is None


async def test_forecast_via_stubbed_predictor_uses_independent_seeds_per_call(monkeypatch, tmp_path):
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    """If the wrapper collapsed its per-sample loop into a single call (or
    reused one seed), every recorded call would be indistinguishable. Assert
    the captured seed material differs run-to-run by checking torch.manual_seed
    was invoked with a distinct value each of the 8 times."""
    seeds_seen = []
    real_manual_seed = torch.manual_seed

    def _spy_manual_seed(seed):
        seeds_seen.append(seed)
        return real_manual_seed(seed)

    monkeypatch.setattr(torch, "manual_seed", _spy_manual_seed)

    fake_predictor = _FakePredictor([100.0 + i for i in range(settings.kronos_sample_count)])
    monkeypatch.setattr(KronosModel, "_ensure_loaded", lambda self: fake_predictor)

    model = KronosModel()
    forecast = await model.forecast("TESTCO", _candles(), "30d")

    assert forecast is not None
    assert len(seeds_seen) == settings.kronos_sample_count
    assert len(set(seeds_seen)) == settings.kronos_sample_count  # all distinct


async def test_forecast_handles_duplicated_final_session_timestamp(monkeypatch, tmp_path):
    """`_run` derives the y_timestamp step from `last_ts - candles[-2].timestamp`
    (kronos.py:127). A duplicated/missing-session gap right at the end of the
    history (e.g. a data provider re-emitting the same trading day) collapses
    that delta to zero, which would produce a degenerate (all-identical)
    future timestamp series. This must not crash the wrapper -- either it
    still produces a forecast (delta-zero timestamps tolerated by the
    predictor stub) or the call chain surfaces as a handled exception ->
    None, per the existing `except Exception: return None` contract in
    `forecast()`. Either outcome is acceptable; a raised, uncaught exception
    is not."""
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    candles = _candles(last_close=100.0)
    candles[-1] = Candle(
        timestamp=candles[-2].timestamp,  # duplicated session -- zero gap to the prior bar
        open=candles[-1].open,
        high=candles[-1].high,
        low=candles[-1].low,
        close=candles[-1].close,
        volume=candles[-1].volume,
        source=candles[-1].source,
        retrieved_at=candles[-1].retrieved_at,
        adjusted=candles[-1].adjusted,
    )

    fake_predictor = _FakePredictor([100.0 + i for i in range(settings.kronos_sample_count)])
    monkeypatch.setattr(KronosModel, "_ensure_loaded", lambda self: fake_predictor)

    model = KronosModel()
    forecast = await model.forecast("TESTCO", candles, "30d")

    # doesn't crash -- either degrades gracefully to None or still produces a
    # forecast from the (degenerate but non-crashing) timestamp series.
    assert forecast is None or forecast.sample_count == settings.kronos_sample_count
