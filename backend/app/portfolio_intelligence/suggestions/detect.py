"""Change detection on audited, adjusted closes. Pure; the SAME function feeds the read API and the nightly worker.

Everything is a state machine REPLAYED over the stored history, so the current state needs no stored memory and a state only
clears after it crosses back by a margin (hysteresis). The margins were MEASURED on 587 real stocks (5 years of adjusted history),
because a plain crossing of the 200-day average changes state a median 7.5 times a year, which would be noise:

  trend      margin 3% + 3 closes of dwell : median 1.7 state changes a year (p90 2.7)
  drawdown   enter <= -20%, clear above -15%: median 1.3 entries a year (p90 2.5)
  deep       enter <= -30%, clear above -25%: median 0.8 entries a year (p90 1.8)
  volatility 60d/252d >= 1.5, clear below 1.3: median 0 entries a year (p90 0.3)

These are descriptions of the past, not forecasts. The raw crossing count is returned beside the rule's own so a reader can see how
often the plain rule cries wolf. All thresholds are unreviewed placeholders (POLICY_VERSION)."""

from datetime import date

import numpy as np
import pandas as pd

POLICY_VERSION = "suggest-policy-p0-unreviewed"
METHOD_VERSION = "suggest-v1"

SMA_DAYS = 200
TREND_MARGIN = 0.03
TREND_DWELL = 3
FRESH_SESSIONS = 10            # a change this recent is "recent"; older is simply the current state
DD_ENTER, DD_CLEAR = -0.20, -0.15
DEEP_ENTER, DEEP_CLEAR = -0.30, -0.25
VOL_ENTER, VOL_CLEAR = 1.5, 1.3
YEAR = 252
MIN_SESSIONS = SMA_DAYS + YEAR + 1   # enough that every measure below has its full lookback


def trend_machine(dates: list[date], closes: np.ndarray) -> dict:
    """Above/below the 200-day average with a margin and a dwell. `since` is the date the CURRENT state was confirmed; `changed`
    is True when that was a change inside the history (not just the first reading)."""
    n = len(closes)
    sma = pd.Series(closes).rolling(SMA_DAYS).mean().to_numpy()
    state, since, changed, changes, previous = None, None, False, [], None
    run_hi = run_lo = 0
    for i in range(SMA_DAYS - 1, n):
        hi, lo = closes[i] > sma[i] * (1 + TREND_MARGIN), closes[i] < sma[i] * (1 - TREND_MARGIN)
        run_hi = run_hi + 1 if hi else 0
        run_lo = run_lo + 1 if lo else 0
        new = "above" if run_hi >= TREND_DWELL else "below" if run_lo >= TREND_DWELL else None
        if new is not None and new != state:
            changed = state is not None
            if changed:
                changes.append(i)
                previous = state
            state, since = new, dates[i]
    last = n - 1
    sign = np.sign(closes[SMA_DAYS - 1:] - sma[SMA_DAYS - 1:])
    window = sign[-YEAR:]
    raw = int((np.diff(window[window != 0]) != 0).sum()) if len(window) else 0
    return {"state": state, "previous": previous if changed else None, "since": since, "changed": changed, "sessions_since": (last - dates.index(since)) if since in dates else None,
            "changes_1y": sum(1 for c in changes if c > last - YEAR), "raw_crossings_1y": raw,
            "ratio_to_average": float(closes[-1] / sma[-1] - 1) if not np.isnan(sma[-1]) else None}


def band_machine(dates: list[date], values: np.ndarray, *, enter: float, clear: float, below: bool, start: int) -> dict:
    """A latch: on when the value reaches `enter` (<= if below else >=), off only after it passes `clear`. Returns the current state,
    the date it switched on, and how many times it switched on in the last year."""
    on, since, entries = False, None, []
    for i in range(start, len(values)):
        v = values[i]
        if np.isnan(v):
            continue
        if not on and ((v <= enter) if below else (v >= enter)):
            on, since = True, dates[i]
            entries.append(i)
        elif on and ((v > clear) if below else (v < clear)):
            on, since = False, None
    last = len(values) - 1
    return {"on": on, "since": since if on else None, "sessions_since": (last - dates.index(since)) if on and since in dates else None,
            "entries_1y": sum(1 for e in entries if e > last - YEAR), "value": None if np.isnan(values[-1]) else float(values[-1])}


def analyze(dates: list[date], closes: list[float]) -> dict:
    """-> {status, trend, drawdown, deep_drawdown, volatility}. `insufficient_data` below MIN_SESSIONS: no number is invented."""
    if len(closes) < MIN_SESSIONS or len(closes) != len(dates):
        return {"status": "insufficient_data", "sessions": len(closes)}
    c = np.asarray(closes, dtype=float)
    if not np.all(np.isfinite(c)) or np.any(c <= 0):
        return {"status": "insufficient_data", "sessions": len(closes), "reason": "non-positive or non-finite close"}
    s = pd.Series(c)
    dd = (s / s.rolling(YEAR, min_periods=YEAR).max() - 1.0).to_numpy()
    r = s.pct_change()
    ratio = (r.rolling(60).std() / r.rolling(YEAR).std()).to_numpy()
    start = YEAR
    return {"status": "ok", "sessions": len(c), "last_date": dates[-1], "trend": trend_machine(dates, c),
            "drawdown": band_machine(dates, dd, enter=DD_ENTER, clear=DD_CLEAR, below=True, start=start),
            "deep_drawdown": band_machine(dates, dd, enter=DEEP_ENTER, clear=DEEP_CLEAR, below=True, start=start),
            "volatility": band_machine(dates, ratio, enter=VOL_ENTER, clear=VOL_CLEAR, below=False, start=start)}
