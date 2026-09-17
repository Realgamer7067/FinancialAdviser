"""docs/V2-RETHINK.md P1: run_backtest used to silently drop the FIRST
realized return of every holding period (dropping reb_date before computing
pct_change left nothing to compute that first day's return against). No test
exercised the actual engine end-to-end before this."""

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import run_backtest


@pytest.mark.asyncio
async def test_backtest_keeps_the_first_holding_period_return():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-02", periods=340)
    symbols = ["A", "B", "C"]

    prices = pd.DataFrame(
        {s: 100 * (1 + pd.Series(rng.normal(0.0005, 0.01, len(dates)), index=dates)).cumprod() for s in symbols},
        index=dates,
    )
    benchmark = prices["A"]

    # A single rebalance point (a huge freq step guarantees exactly one) --
    # isolates the fix to one holding period so the count is unambiguous.
    report = await run_backtest(
        prices,
        benchmark,
        rebalance_freq="10YS",
        lookback_days=252,
        top_k=2,
        holding_returns_window=60,
    )

    # The full window after the single rebalance date has len(dates) -
    # lookback_days rows; a correct engine keeps ALL but the very first row's
    # own leading pct_change() NaN -- i.e. (rows_after_rebalance - 1) returns,
    # not (rows_after_rebalance - 2) as the pre-fix "drop reb_date, then
    # pct_change" bug produced.
    # Mirrors engine.py's own rebalance-date selection so this test isn't
    # coupled to guessing which date "10YS" anchors to.
    candidate_dates = pd.date_range(dates[252], dates[-1], freq="10YS")
    reb_date_index = ([d for d in candidate_dates if d in dates] or [dates[252]])[0]
    expected_max_len = len(dates[dates >= reb_date_index]) - 1

    assert len(report.returns) == expected_max_len


@pytest.mark.asyncio
async def test_engine_reflects_whatever_price_convention_it_is_given():
    """V3 Phase 09 audit (item 3): engine.py does no split/dividend
    adjustment of its own -- it reports back exactly whatever return
    convention the input closes encode. This engine-level test proves that
    directly, without depending on yfinance: a "properly adjusted" (smooth,
    continuous) close series and a "raw, un-adjusted" close series that
    undergoes a real 2:1 split -- with no retroactive restatement of prior
    prices -- are IDENTICAL up to the split date, so both variants are
    guaranteed to rank/select the same symbol at the single rebalance date
    (which happens before the split). They then diverge sharply over the
    holding period: the raw series injects a fake ~-50% return on the split
    day that the adjusted series never sees. If a caller ever fed this
    engine un-adjusted closes, it would silently produce a total-return
    -shaped report riddled with fake drawdowns like this one -- exactly the
    silent mislabeling the module's docstring now calls out.
    """
    dates = pd.bdate_range("2020-01-02", periods=400)
    lookback_days = 252
    split_date = dates[300]  # well after the single rebalance at dates[252], before the series ends

    # WINNER trends up, losers trend down -- so WINNER is deterministically
    # the top-ranked (and, with top_k=1, only) candidate at the rebalance
    # date, in both variants (history up to the rebalance date is identical
    # between them; the split happens later).
    winner_adjusted = pd.Series(100 * (1.0006**np.arange(len(dates))), index=dates)
    loser_1 = pd.Series(100 * (0.9994**np.arange(len(dates))), index=dates)
    loser_2 = pd.Series(100 * (0.9993**np.arange(len(dates))), index=dates)

    winner_raw = winner_adjusted.copy()
    winner_raw.loc[winner_raw.index >= split_date] /= 2  # real 2:1 split, no retroactive restatement

    prices_adjusted = pd.DataFrame({"WINNER": winner_adjusted, "L1": loser_1, "L2": loser_2})
    prices_raw = pd.DataFrame({"WINNER": winner_raw, "L1": loser_1, "L2": loser_2})

    kwargs = dict(
        rebalance_freq="10YS",
        lookback_days=lookback_days,
        top_k=1,
        holding_returns_window=60,
        max_single_weight=1.0,  # single candidate -> unambiguous 100% allocation
    )
    report_adjusted = await run_backtest(prices_adjusted, winner_adjusted, **kwargs)
    report_raw = await run_backtest(prices_raw, winner_raw, **kwargs)

    # The adjusted (properly split/dividend-adjusted, per the engine's now
    # -documented convention) variant never sees anything close to a -50%
    # day -- it's a smooth uptrend throughout.
    assert report_adjusted.returns.min() > -0.05

    # The raw (un-adjusted) variant shows the fake split-day cliff verbatim
    # -- proving the engine passes the input convention through untouched
    # rather than silently correcting or flagging it.
    assert report_raw.returns.min() < -0.4
