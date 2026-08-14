from datetime import datetime, timedelta, timezone

from app.providers.base import Candle
from app.services.technical_analysis import compute_technical_features


def _make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(days=i),
            open=c * 0.99,
            high=c * 1.01,
            low=c * 0.98,
            close=c,
            volume=100_000,
            source="test",
            retrieved_at=now,
        )
        for i, c in enumerate(closes)
    ]


def test_uptrend_series_detected_as_bullish():
    closes = [100 + i * 1.5 for i in range(260)]  # steady climb, > 200 bars for sma_200
    candles = _make_candles(closes)
    features = compute_technical_features(candles, timeframe="1d")
    assert features["trend"] == "bullish"
    assert features["sma_20"] is not None
    assert features["rsi_14"] is not None and features["rsi_14"] > 50


def test_downtrend_series_detected_as_bearish():
    closes = [500 - i * 1.5 for i in range(260)]
    candles = _make_candles(closes)
    features = compute_technical_features(candles, timeframe="1d")
    assert features["trend"] == "bearish"
    assert features["rsi_14"] is not None and features["rsi_14"] < 50


def test_insufficient_history_returns_none():
    candles = _make_candles([100.0])
    assert compute_technical_features(candles, timeframe="1d") is None


def test_flat_series_has_low_volatility():
    closes = [100.0] * 260
    candles = _make_candles(closes)
    features = compute_technical_features(candles, timeframe="1d")
    assert features["volatility_30d"] is not None
    assert features["volatility_30d"] < 0.01
