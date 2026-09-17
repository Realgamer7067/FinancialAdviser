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
            adjusted=False,
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


def test_beta_aligns_by_trading_date_not_row_position():
    # docs/V2-RETHINK.md P1: stock and benchmark histories can have different
    # missing sessions -- truncating both to equal length and zipping by
    # position (instead of by actual date) can pair up returns from
    # different days entirely, corrupting beta. Here the stock has one EXTRA
    # early session the benchmark lacks; a position-based tail-alignment
    # would shift every later pairing by one day and destroy the otherwise
    # perfect 1:1 correlation, but date-based alignment must still see beta
    # close to 1.0 since it drops the one non-overlapping day and correctly
    # pairs every remaining date.
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    def _candle(day_offset: int, close: float) -> Candle:
        return Candle(
            timestamp=start + timedelta(days=day_offset),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=100_000,
            source="test",
            retrieved_at=now,
            adjusted=False,
        )

    n = 60
    bench_closes = [100 + i * 0.7 + (i % 5) * 0.3 for i in range(n)]
    stock_closes = [50 + i * 0.35 + (i % 5) * 0.15 for i in range(n)]  # moves in lockstep with bench

    stock_candles = [_candle(0, stock_closes[0] * 0.999)] + [_candle(i, c) for i, c in enumerate(stock_closes)]
    bench_candles = [_candle(i, c) for i, c in enumerate(bench_closes)]

    features = compute_technical_features(stock_candles, timeframe="1d", benchmark_candles=bench_candles)
    assert features["beta"] is not None
    assert 0.8 < features["beta"] < 1.3


def test_insufficient_history_returns_none():
    candles = _make_candles([100.0])
    assert compute_technical_features(candles, timeframe="1d") is None


def test_flat_series_has_low_volatility():
    closes = [100.0] * 260
    candles = _make_candles(closes)
    features = compute_technical_features(candles, timeframe="1d")
    assert features["volatility_30d"] is not None
    assert features["volatility_30d"] < 0.01
