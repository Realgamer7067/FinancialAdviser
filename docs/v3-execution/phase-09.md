# Phase 09 — forecast validation (fast pass)

Date: 2026-09-15. Coordinator first closed Phase 05's disclosed API-wiring
gap directly, then dispatched 2 parallel subagents (forecast, backtest) per
this phase's own table. Both clean, no rate-limit issues.

## Scope completed (Phase 05 API wiring, coordinator)

- New `backend/app/api/plans.py`: `POST /api/plans` (computes allocation via
  `target_gap_allocation` + `rounding_and_fallback` + `validate_constraints`
  against `allocation_policy_config()`), `GET /api/plans/scenarios`.
- Deliberately narrow: works at asset-class level only.
  `validate_constraints` is called with no `per_symbol_weights` rather than
  faking a per-symbol/issuer-concentration check with no real data behind
  it — `HoldingPosition` has no asset-class classification yet, so
  `current_exposure` is caller-supplied, not auto-derived from Phase 03
  holdings.
- New `backend/tests/test_plans_api.py`, 5 tests. Found and fixed my own
  test-design bug: `new_cash > 0` always grows `total_planning_wealth`, so
  by pigeonhole at least one asset class's target must exceed its current
  amount — "every class already funded" is representable only with
  `new_cash="0"`. Renamed the test to match (`_zero_new_cash_`, not
  `_already_at_target_`) — a correctness feature of the math, not a bug in
  `allocation_engine.py`.
- `backend/app/main.py` updated to register the `plans` router.

## Scope completed (Phase 09, 2 subagents)

- **Forecast worker**: validated `KronosModel` two layers deep (stubbed the
  predictor itself, not just `_run`) — proved 8 independent sampled calls
  per forecast, correct horizon-to-bars mapping, real percentile math on
  the sample set. Found and fixed 2 real bugs:
  - `kronos.py`'s `forecast()` had the `lookup_confidence()` call sitting
    outside the existing `except Exception` guard around the sampling
    loop — added a dedicated try/except backstop so a corrupt/unexpected
    calibration artifact degrades `confidence` to `None` instead of
    crashing the whole forecast call.
  - `kronos_calibration.py`'s `lookup_confidence` had an unguarded
    `float(entry["hit_rate"])` cast that would `TypeError`/`KeyError` or
    silently coerce a wrong type on malformed data — now validates
    `isinstance(hit_rate, (int, float)) and not isinstance(hit_rate, bool)`
    before casting, failing closed to `None` (Section 50: never guess).
- **Backtest reviewer**: found and documented a real, previously
  undisclosed gap — `engine.py` returns approximate TOTAL return, not price
  return, because upstream `yfinance` calls use `auto_adjust=True`. Added
  `test_engine_reflects_whatever_price_convention_it_is_given`
  (`test_backtest_engine.py`), which proves the distinction with a
  synthetic 2:1-split scenario (adjusted vs. raw closes, identical up to
  the split, diverge sharply after) rather than asserting on a claim.
  Also added a contract test pinning `BacktestReport.as_dict()`'s key set
  (no fee/cost field) so a future silent field addition gets caught.
- No live held-out MAE/RMSE evaluation was possible in this environment —
  no real HF weights, no PostgreSQL for a persisted calibration run.

## Files changed

Changed: `backend/app/models_iface/kronos.py` (try/except backstop around
`lookup_confidence`), `backend/app/backtesting/kronos_calibration.py`
(guarded `hit_rate` cast), `backend/app/backtesting/engine.py` (docstring
now states the total-return-vs-price-return convention explicitly),
`backend/app/main.py` (plans router registered).

New: `backend/app/api/plans.py`, `backend/tests/test_plans_api.py`,
2 new tests appended to `backend/tests/test_backtest_engine.py`.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 367 passed, 15 warnings
```

## Rollback

Each change is additive/isolated: `plans.py` is a new router (unregister
in `main.py` to disable); the two `kronos*.py` fixes are pure
fail-closed guards (removing them reverts to the pre-Phase-09 crash/
type-error behavior, strictly worse); `engine.py`'s change is docstring +
tests only, no runtime behavior changed.

## Phase gate verdict

**Passed (conditional).** Kronos wrapper validated 2 layers deep,
calibration artifact schema hardened against malformed input. Backtest
return-convention gap disclosed and regression-tested. Real limitation
carried forward: no live held-out accuracy measurement possible in this
environment (no real model weights, no PostgreSQL).

## Next ready task

Phase 10 (independent acceptance) now has all its dependencies
(05/07/08/09) at conditional-pass. Not yet started — awaiting explicit
go-ahead, since it's an audit/gate pass over everything built, not new
feature work.
