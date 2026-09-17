"""Kronos-specific calibration harness (docs/V2-RETHINK.md section 2a).

This is deliberately NOT part of `engine.py`, which backtests the technical +
portfolio-optimization half of the pipeline and has no Kronos-related code.
Kronos needs full OHLCV history (not the close-only panel `engine.py` works
with) and answers a different question: "when Kronos's sampled forecasts
agreed with each other at rate X, how often was the direction actually
right?" That empirical hit-rate table is what `KronosModel` looks up at
inference time to populate `confidence` -- until a table exists for a given
`(model_version, horizon)`, `confidence` stays `None` (Section 50: never
guess).

SURVIVORSHIP BIAS (same caveat as `engine.py`, not fixed here either): this
harness walks *today's* Nifty50 constituents backward across history, so a
symbol has to have survived to be in the sample. Report this caveat alongside
any calibration number this module produces.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import DATA_DIR

# V3 Phase 11 (packaging path reconciliation): this used to be a hardcoded
# `Path("./data/cache/kronos_calibration")`, resolved relative to the
# process's CWD -- inconsistent with every other data root in the codebase,
# which goes through `settings`/`DATA_DIR` (env-overridable, resolved to the
# repo root or the container's /app/data, not wherever the process happened
# to be launched from). A worker started from the repo root instead of
# `backend/` would have silently looked in the wrong directory.
_CALIBRATION_ROOT = DATA_DIR / "cache" / "kronos_calibration"

# direction_agreement is bucketed into coarse bands before lookup/storage --
# storing a table entry per exact float would never accumulate enough samples
# per bucket to be a meaningful empirical hit rate.
_AGREEMENT_BUCKETS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def _bucket(direction_agreement: float) -> str:
    da = max(0.5, min(1.0, direction_agreement))
    for edge in _AGREEMENT_BUCKETS:
        if da <= edge:
            return f"<={edge}"
    return "<=1.0"


def _table_path(model_version: str, horizon: str) -> Path:
    safe_version = model_version.replace("/", "_")
    return _CALIBRATION_ROOT / safe_version / f"{horizon}.json"


def lookup_confidence(model_version: str, horizon: str, direction_agreement: float) -> float | None:
    """Returns the empirical historical hit rate for this (model_version,
    horizon, direction_agreement bucket), or None if no calibration table has
    been produced yet for this exact model_version/horizon -- never a guessed
    placeholder."""
    path = _table_path(model_version, horizon)
    if not path.exists():
        return None
    try:
        table = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    bucket = _bucket(direction_agreement)
    entry = table.get(bucket)
    if entry is None or entry.get("sample_size", 0) == 0:
        return None
    hit_rate = entry.get("hit_rate")
    if not isinstance(hit_rate, (int, float)) or isinstance(hit_rate, bool):
        # Malformed/incomplete artifact (missing, null, or non-numeric
        # hit_rate despite a nonzero sample_size) -- fail closed, never
        # fabricate a confidence value (Section 50).
        return None
    return float(hit_rate)


class CalibrationSample:
    """One (origin_date, symbol, horizon) observation collected while walking
    history forward, before it's aggregated into the stored bucketed table."""

    def __init__(self, direction_agreement: float, kronos_correct: bool, naive_correct: bool):
        self.direction_agreement = direction_agreement
        self.kronos_correct = kronos_correct
        self.naive_correct = naive_correct


def build_calibration_table(samples: list[CalibrationSample]) -> dict:
    """Aggregates raw walk-forward samples into the bucketed hit-rate table
    that `lookup_confidence` reads. Reports the naive (zero-change) baseline
    hit rate alongside Kronos's, per docs/V2-RETHINK.md section 9's gate:
    Kronos's error must be reported relative to a baseline, not in isolation."""
    table: dict[str, dict] = {}
    for edge in _AGREEMENT_BUCKETS:
        bucket_key = f"<={edge}"
        bucket_samples = [s for s in samples if _bucket(s.direction_agreement) == bucket_key]
        if not bucket_samples:
            table[bucket_key] = {"sample_size": 0, "hit_rate": None, "naive_baseline_hit_rate": None}
            continue
        kronos_hits = sum(1 for s in bucket_samples if s.kronos_correct)
        naive_hits = sum(1 for s in bucket_samples if s.naive_correct)
        table[bucket_key] = {
            "sample_size": len(bucket_samples),
            "hit_rate": kronos_hits / len(bucket_samples),
            "naive_baseline_hit_rate": naive_hits / len(bucket_samples),
        }
    return table


def save_calibration_table(model_version: str, horizon: str, table: dict) -> Path:
    path = _table_path(model_version, horizon)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=2))
    return path


async def run_walk_forward_calibration(
    ohlcv_by_symbol: dict[str, pd.DataFrame],
    forecast_fn,
    horizon: str,
    bars: int,
    lookback_days: int = 252,
    step_days: int = 5,
) -> list[CalibrationSample]:
    """Walks each symbol's OHLCV history forward with strict no-look-ahead
    slicing (same pattern as `engine.py:99`'s `history = prices.loc[:reb_date]`),
    calling `forecast_fn(history_df, bars)` at each origin date and comparing
    against the realized close `bars` trading days later and against a naive
    zero-change baseline.

    `forecast_fn` is injected (not `KronosModel._run` directly) so this harness
    stays testable without real HF weights, matching the existing mocking
    pattern used in `test_pipeline_smoke.py`. It must return
    `(direction_agreement: float, predicted_return: float)`.
    """
    samples: list[CalibrationSample] = []
    for symbol, df in ohlcv_by_symbol.items():
        df = df.sort_index()
        if len(df) < lookback_days + bars + 1:
            continue
        origins = range(lookback_days, len(df) - bars, step_days)
        for i in origins:
            history = df.iloc[: i + 1]  # strictly no look-ahead past the origin row
            direction_agreement, predicted_return = forecast_fn(history, bars)
            last_close = float(history["close"].iloc[-1])
            realized_close = float(df["close"].iloc[i + bars])
            realized_return = (realized_close - last_close) / last_close

            predicted_sign = np.sign(predicted_return)
            realized_sign = np.sign(realized_return)
            kronos_correct = bool(predicted_sign == realized_sign and predicted_sign != 0)
            naive_correct = bool(realized_sign == 0)  # naive baseline always predicts zero change

            samples.append(CalibrationSample(direction_agreement, kronos_correct, naive_correct))
    return samples
