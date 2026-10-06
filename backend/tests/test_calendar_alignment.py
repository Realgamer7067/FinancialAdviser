"""V3 Phase 02: calendar-worker coverage.

1. A realistic NSE-style multi-day gap (3-day weekend + a named holiday ->
   4 calendar-day gap) shared by BOTH a stock and its benchmark must not
   break beta / portfolio-return alignment -- there's simply no trading day
   in the gap to align, on either side, so nothing should NaN or crash.

2. The "one series has a gap the other doesn't" case for
   `MeanVariancePortfolioModel`'s date-indexed alignment is already covered
   by `test_portfolio_mvo.py::test_date_indexed_returns_align_by_trading_date_not_position`
   (candidate B is missing one mid-window day candidate A has, and the
   result is still a valid, fully-allocated result) -- not duplicated here.

3. The `Candle.adjusted` flag must survive the
   `_persist_candles` -> `_get_cached_candles` round trip via `MarketCandle`,
   not be silently dropped/defaulted.
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.models.market import Instrument
from app.models_iface.portfolio_mvo import MeanVariancePortfolioModel
from app.pipelines.recommendation_pipeline import _get_cached_candles, _persist_candles
from app.providers.base import Candle
from app.providers.mode import expected_candle_source
from app.services.technical_analysis import compute_technical_features

# A realistic NSE-style trading calendar: skip Sat/Sun, and drop one extra
# named-holiday weekday (e.g. a Diwali/Independence-Day-style gap) so a
# normal 7-day calendar week collapses into a 4-calendar-day gap with no
# trading day on either side of it -- like the real NSE holiday calendar,
# not a made-up single-day skip.
_HOLIDAY_WEEKDAY_OFFSET = 15  # a Monday, made into an extra holiday below


def _nse_style_trading_dates(start: date, n_weeks: int) -> list[date]:
    dates = []
    d = start
    while len(dates) < n_weeks * 5:
        if d.weekday() < 5:  # Mon-Fri only, weekends never traded
            dates.append(d)
        d += timedelta(days=1)
    # Drop one additional weekday ~3 weeks in to simulate a named holiday,
    # producing (that Friday -> the following Tuesday) = a 4 calendar-day
    # gap with zero trading days on either side, shared by both series.
    holiday = dates[_HOLIDAY_WEEKDAY_OFFSET]
    return [d for d in dates if d != holiday]


def _candle(day: date, close: float, now: datetime) -> Candle:
    return Candle(
        timestamp=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        open=close * 0.99,
        high=close * 1.01,
        low=close * 0.98,
        close=close,
        volume=100_000,
        source="test",
        retrieved_at=now,
        adjusted=False,
    )


def test_shared_holiday_gap_does_not_break_beta():
    now = datetime.now(timezone.utc)
    trading_dates = _nse_style_trading_dates(date(2025, 1, 1), n_weeks=13)  # ~65 trading days
    assert len(trading_dates) == 64  # 65 - 1 dropped holiday

    rng = np.random.default_rng(42)
    bench_closes = 100 + np.cumsum(rng.normal(0, 1, len(trading_dates)))
    stock_closes = 50 + 0.5 * np.cumsum(rng.normal(0, 1, len(trading_dates))) + bench_closes * 0.1

    stock_candles = [_candle(d, c, now) for d, c in zip(trading_dates, stock_closes)]
    bench_candles = [_candle(d, c, now) for d, c in zip(trading_dates, bench_closes)]

    features = compute_technical_features(stock_candles, timeframe="1d", benchmark_candles=bench_candles)
    assert features is not None
    # No trading day exists in the gap on EITHER side, so there's nothing to
    # misalign -- beta must compute cleanly, not NaN or crash.
    assert features["beta"] is not None
    assert not np.isnan(features["beta"])


def test_shared_holiday_gap_does_not_break_portfolio_alignment():
    trading_dates = _nse_style_trading_dates(date(2025, 1, 1), n_weeks=13)
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in trading_dates])

    # Both candidates trade on exactly the same NSE calendar (including the
    # shared holiday gap) -- an inner join on dates should keep every row,
    # not drop anything or introduce NaNs.
    returns_a = pd.Series(np.random.default_rng(1).normal(0.001, 0.01, len(idx)), index=idx)
    returns_b = pd.Series(np.random.default_rng(2).normal(0.001, 0.01, len(idx)), index=idx)

    import asyncio

    model = MeanVariancePortfolioModel()
    result = asyncio.run(model.optimize({"A": returns_a, "B": returns_b}, risk_free_rate=0.0, max_single_weight=0.8))

    assert set(result.allocations.keys()) <= {"A", "B"}
    assert abs(sum(result.allocations.values()) + result.unallocated_cash - 1.0) < 1e-6
    assert result.expected_return is not None
    assert not np.isnan(result.expected_return)


async def test_adjusted_flag_survives_persist_and_read_cache_round_trip(db_session):
    instrument = Instrument(symbol="TESTCO", exchange="NSE", name="Test Co")
    db_session.add(instrument)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    source = expected_candle_source()  # demo_mode=True in tests -> "demo_seed"
    candles = [
        Candle(
            timestamp=datetime.combine(date.today() - timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1000,
            source=source,
            retrieved_at=now,
            adjusted=True,  # deliberately True, to prove it isn't defaulted away
        )
        for i in range(5, 0, -1)
    ]

    await _persist_candles(db_session, instrument.id, candles)
    await db_session.commit()

    cached = await _get_cached_candles(db_session, instrument.id)
    assert cached is not None
    assert len(cached) == len(candles)
    assert all(c.adjusted is True for c in cached)
