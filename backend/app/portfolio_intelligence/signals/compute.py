"""Deterministic per-security signals from stored daily history (no model, no AI).

Every number DESCRIBES the past ("above its 200-day average", "fell 18% from its 52-week high"); none is a
forecast or a recommendation. Closes passed in must already be audited/adjusted (market/adjust.py).

Families (so a later allocator cannot double-count correlated checks):
- trend:     close vs its 200-day average, and 12-1 month momentum (they are highly correlated: ONE vote)
- risk:      realized volatility ONLY. Distance below the 52-week high is shown but is NOT part of the vote: measured on the
             live universe it correlates 0.87 with the 200-day trend and 0.76 with momentum, so counting it would double-count trend
- liquidity: median 20-day traded value and circuit-locked days: a GATE on tradability, never a vote
- forecast:  model forecasts (Kronos), stored elsewhere and counted 0 until proven out of sample

All thresholds in this module are unreviewed placeholders (POLICY_VERSION) and are named so they can be reviewed."""

import math
from datetime import date

import numpy as np

from app.portfolio_intelligence.risk.volatility import annualized_vol, max_drawdown

METHOD_VERSION = "signals-v1"
POLICY_VERSION = "signals-policy-p0-unreviewed"

MIN_CLOSES = 253            # 252 returns + the base close; the same bar the Risk page uses for volatility
SMA_DAYS = 200
MOM_LOOKBACK, MOM_SKIP = 252, 21   # 12-1: from 252 sessions ago to 21 sessions ago (skips the last month)
VOL_SHORT, VOL_LONG = 60, 252
LIQUIDITY_WINDOW = 20
LIQUIDITY_FLOOR_RUPEES = 10_000_000.0   # placeholder: median traded value under Rs 1 crore a day is "thin"
STALE_DAYS = 5                          # last candle this many calendar days behind the last session


def _returns(closes: np.ndarray) -> list[float]:
    return (closes[1:] / closes[:-1] - 1.0).tolist()


def compute_metrics(dates: list[date], closes: list[float], highs: list[float], lows: list[float], volumes: list[float | None],
                    *, expected_last_session: date, unreliable_dates: list[date] | None = None) -> dict:
    """-> flat dict of metrics + `quality` (ok | insufficient_data | stale | unreliable_window) + `reasons`.
    A metric that lacks its minimum history is None, never an approximation."""
    n = len(closes)
    out: dict = {"history_len": n, "last_candle_date": dates[-1] if dates else None, "reasons": []}
    keys = ("sma200_ratio", "trend_state", "mom_12_1", "mom_6_1", "vol_60", "vol_252", "vol_ratio", "drawdown_current", "max_dd_1y",
            "week52_pos", "liquidity_value", "circuit_days_20")
    out.update({k: None for k in keys})
    if n == 0:
        out.update(quality="insufficient_data", reasons=["no history"])
        return out
    c = np.asarray(closes, dtype=float)
    if not np.all(np.isfinite(c)) or np.any(c <= 0):
        out.update(quality="insufficient_data", reasons=["history contains non-positive or non-finite closes"])
        return out

    if n >= SMA_DAYS:
        sma = float(c[-SMA_DAYS:].mean())
        out["sma200_ratio"] = c[-1] / sma - 1.0
        out["trend_state"] = "above" if c[-1] > sma else "below"
    if n >= MOM_LOOKBACK + 1:
        out["mom_12_1"] = float(c[-1 - MOM_SKIP] / c[-1 - MOM_LOOKBACK] - 1.0)
    if n >= 127:
        out["mom_6_1"] = float(c[-1 - MOM_SKIP] / c[-127] - 1.0)
    if n >= VOL_SHORT + 1:
        out["vol_60"] = annualized_vol(_returns(c[-(VOL_SHORT + 1):]))
    if n >= MIN_CLOSES:
        window = c[-(VOL_LONG + 1):]
        out["vol_252"] = annualized_vol(_returns(window))
        out["max_dd_1y"] = max_drawdown(_returns(window))
        hi, lo = float(c[-252:].max()), float(c[-252:].min())
        out["drawdown_current"] = float(c[-1] / hi - 1.0)
        out["week52_pos"] = float((c[-1] - lo) / (hi - lo)) if hi > lo else None
        if out["vol_60"] is not None and out["vol_252"]:
            out["vol_ratio"] = out["vol_60"] / out["vol_252"]
    if n >= LIQUIDITY_WINDOW and all(v is not None for v in volumes[-LIQUIDITY_WINDOW:]):
        traded = [float(c[-i]) * float(volumes[-i]) for i in range(1, LIQUIDITY_WINDOW + 1)]
        out["liquidity_value"] = float(np.median(traded))
        # a day with high == low and trades is a circuit-locked day: its return is not a free-market move and it
        # flattens realized volatility
        out["circuit_days_20"] = sum(1 for i in range(1, LIQUIDITY_WINDOW + 1) if highs[-i] == lows[-i] and (volumes[-i] or 0) > 0)

    if n < MIN_CLOSES:
        out["quality"] = "insufficient_data"
        out["reasons"].append(f"only {n} sessions of history (need {MIN_CLOSES} for the 1-year measures)")
    elif (expected_last_session - dates[-1]).days > STALE_DAYS:
        out["quality"] = "stale"
        out["reasons"].append(f"newest price is {dates[-1]}, behind the last session {expected_last_session}")
    elif unreliable_dates and any(d >= dates[-MIN_CLOSES] for d in unreliable_dates):
        out["quality"] = "unreliable_window"
        out["reasons"].append("an unadjusted corporate action falls inside the 1-year lookback")
    else:
        out["quality"] = "ok"
    return out


def percentile_in(reference: np.ndarray, x: float | None) -> float | None:
    """Where x falls among the reference values (0-100), WITHOUT x joining the reference: the share of reference
    values strictly below x plus half the ties. A name outside the reference set is placed against it and never shifts it."""
    if x is None or reference.size == 0 or not math.isfinite(x):
        return None
    below = float((reference < x).sum())
    equal = float((reference == x).sum())
    return 100.0 * (below + 0.5 * equal) / reference.size


def rank_against_reference(rows: list[dict], reference_mask: list[bool], fields: tuple[str, ...] = ("mom_12_1", "vol_252")) -> None:
    """Adds `<field>_rank` and `rank_universe_size` to each row in place. The reference is the rows flagged in
    `reference_mask` that have a value for the field (fresh, adjusted-clean, liquid, classified)."""
    for f in fields:
        ref = np.array([r[f] for r, m in zip(rows, reference_mask) if m and r.get(f) is not None], dtype=float)
        for r in rows:
            r[f"{f}_rank"] = percentile_in(ref, r.get(f)) if r.get("quality") == "ok" else None
        for r in rows:
            r["rank_universe_size"] = int(ref.size) if f == fields[0] else r.get("rank_universe_size")


def liquidity_flag(value: float | None) -> str:
    if value is None:
        return "unknown"
    return "ok" if value >= LIQUIDITY_FLOOR_RUPEES else "thin"


# --- families: descriptive states, never advice --------------------------------------------------------------------------

def trend_family(row: dict) -> dict:
    """positive: above its 200-day average AND 12-1 momentum rank >= 50; negative: below AND rank < 50; otherwise mixed."""
    state, rank = row.get("trend_state"), row.get("mom_12_1_rank")
    if row.get("quality") != "ok" or state is None or rank is None:
        return {"state": "unavailable", "vote": 0, "text": "not enough clean history"}
    if state == "above" and rank >= 50:
        return {"state": "positive", "vote": 1, "text": "above its 200-day average and in the stronger half for 12-1 month momentum"}
    if state == "below" and rank < 50:
        return {"state": "negative", "vote": -1, "text": "below its 200-day average and in the weaker half for 12-1 month momentum"}
    return {"state": "mixed", "vote": 0, "text": f"{'above' if state == 'above' else 'below'} its 200-day average but {'weaker' if state == 'above' else 'stronger'} than half its peers on 12-1 month momentum"}


def risk_family(row: dict) -> dict:
    """positive: realized volatility in the calmer half of its peers; negative: in the most volatile fifth; otherwise mixed.
    Volatility alone (Spearman vs trend 0.29, vs momentum 0.15 on the live universe)."""
    rank = row.get("vol_252_rank")
    if row.get("quality") != "ok" or rank is None:
        return {"state": "unavailable", "vote": 0, "text": "not enough clean history"}
    if rank >= 80:
        return {"state": "negative", "vote": -1, "text": "among the more volatile of its peers over the last year"}
    if rank <= 50:
        return {"state": "positive", "vote": 1, "text": "calmer than half of its peers over the last year"}
    return {"state": "mixed", "vote": 0, "text": "volatility is in the middle range for its peers"}


def liquidity_gate(row: dict) -> dict:
    f = liquidity_flag(row.get("liquidity_value"))
    note = {"ok": "trades enough rupees a day to enter or leave a small position", "thin": "thinly traded: a small order can move the price",
            "unknown": "volume history unavailable"}[f]
    locked = row.get("circuit_days_20") or 0
    if locked:
        note += f"; {locked} of the last 20 sessions were circuit-locked (price did not move freely)"
    return {"state": f, "text": note}


def summarize(row: dict, forecast: dict | None = None) -> dict:
    """Independent families for display and for a later allocator. The forecast family is shown but always counts 0."""
    t, r = trend_family(row), risk_family(row)
    return {"policy_version": POLICY_VERSION, "trend": t, "risk": r, "liquidity": liquidity_gate(row),
            "forecast": ({"state": forecast["direction"], "vote": 0, "text": "model forecast, counted 0 until it has proven itself out of sample"}
                         if forecast else {"state": "none", "vote": 0, "text": "no model forecast stored"}),
            "net_vote": t["vote"] + r["vote"]}
