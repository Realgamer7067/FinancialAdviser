# Phase 02 — data identity and report snapshots

Date: 2026-09-14. Delegated to 3 parallel subagents (Identity worker,
Snapshot worker, Calendar worker) per the guide's own subagent assignment
table for this phase, plus coordinator integration (migration, pipeline/API
wiring, source registry, final verification). Contract frozen (CONTRACTS.md
C3a/C7 additions) before dispatch, per §2.4's dependency-aware concurrency
rule — the three workers needed to agree on how `MarketCandle`'s new columns
and the manifest's natural-identity fields relate before starting.

## Scope completed

**Identity worker — candle history preservation (own: `market.py`,
`recommendation_pipeline.py`'s candle functions, `api/stocks.py`/`portfolio.py`
candle reads, new tests).**
- `MarketCandle` gained `import_batch_id`/`superseded_at`; the old plain
  `UniqueConstraint` was replaced with a partial unique index scoped to
  `superseded_at IS NULL`.
- `_persist_candles` now diffs incoming candles against current rows by
  timestamp and only supersedes+reinserts what's new or actually changed —
  a byte-identical re-import is a true no-op (idempotent), and a refresh
  with real changes marks old rows `superseded_at` instead of deleting them.
- All three read paths (pipeline cache read, `api/stocks.py`, `api/portfolio.py`)
  filter `superseded_at IS NULL`.
- 4 new tests in `test_candle_history.py`.

**Calendar worker — adjustment metadata + holiday-gap proof (own:
`providers/base.py`, `yfinance_market_data.py`, `demo_market_data.py`,
`technical_analysis.py` review, new tests).**
- New required field `Candle.adjusted: bool` — no default, every provider
  states it explicitly. yfinance path is `True` (confirmed: `.history()`
  defaults to `auto_adjust=True`, no override in this codebase's call).
  Demo path is `False` (synthetic, no real corporate actions).
- `MarketCandle.adjusted` column added (additive-only edit, coordinated with
  the identity worker's concurrent changes to the same file/functions).
- Confirmed (didn't re-litigate) the existing V2-session date-based
  alignment in `portfolio_mvo.py`/`technical_analysis.py` already handles
  one-series-has-a-gap-the-other-doesn't correctly. Added new coverage for
  a realistic shared multi-day NSE-style holiday gap (both series missing
  the same days) not previously tested, plus an adjustment-flag round-trip
  test. New file `test_calendar_alignment.py`.

**Snapshot worker — data-manifest primitive (own: new `models/manifest.py`,
`services/manifest.py`, new tests; explicitly did not touch pipeline/API).**
- `DataManifestEntry` model + `record_manifest_entry`/`get_manifest_entry`/
  `is_legacy` service, built exactly to the frozen contract (natural-identity
  fields, not row-id foreign keys — avoids invasive pipeline threading
  changes). 5 new tests in `test_data_manifest.py`.

**Coordinator integration (this pass).**
- Resolved the fork the snapshot worker flagged (unique constraint vs.
  call-discipline): added `UniqueConstraint(council_run_id, instrument_id)`
  to `DataManifestEntry` — the pipeline calls `record_manifest_entry` exactly
  once per candidate per run, so this is a real invariant, and it makes
  `get_manifest_entry`'s `scalar_one_or_none()` safe against accidental
  duplicates rather than silently ambiguous.
- One combined migration `0010` for all three workers' DDL (candle
  supersession columns + partial index, `adjusted` column with `TRUE`
  backfill, new `data_manifest_entries` table). Verified via
  `alembic upgrade head --sql` (offline SQL generation — no live DB).
- Wired `record_manifest_entry` into `_evaluate_candidate`
  (`recommendation_pipeline.py`) — one call per candidate, right after its
  `CandidateScore` is added, using the already-in-scope `candles`,
  `fundamentals`, `technicals`, `kronos_data` parameters. Fixed a real
  omission found while wiring this: `TimeSeriesForecast`/`_kronos_forecast`'s
  returned dict never carried `generated_at` (only the DB row did) — added it
  explicitly so the manifest's `kronos_generated_at` isn't silently always
  `None`.
- Wired `get_manifest_entry` into `api/stocks.py`'s `GET /{symbol}`:
  resolves the newest `Recommendation` first, looks up its manifest entry,
  and pins fundamentals/technicals/kronos(30d) reads to its exact
  natural-identity values when found; falls back to "most recent" and sets
  the new `StockDetail.evidence_is_legacy: bool` flag when not (predates the
  manifest system). `latest_price`/`price_as_of` deliberately stay
  independently live — current market price is supposed to be fresh; it's
  the *scored evidence* that must match what the recommendation actually saw.
  `kronos_horizons` (7d/90d, display-only) stay "most recent" — the
  manifest only tracks the 30d forecast scoring used.
- Closed one more C3 gap noticed while in `api/stocks.py`:
  `GET /{symbol}/history` had no `source`/`superseded_at` filter at all
  (a third, previously-unflagged instance of the same read-path bug class).
- Frontend: `StockDetail.evidence_is_legacy` threaded through
  `frontend/src/lib/types.ts` and rendered as a visible warning note on the
  stock detail page when true.
- Small permitted-source registry: `docs/v3-execution/source-registry.md`
  (Phase 02 instruction 6) — every row traces to an already-wired provider,
  nothing speculative added.

## Files/contracts changed

New: `backend/app/models/manifest.py`, `backend/app/services/manifest.py`,
`backend/alembic/versions/0010_phase02_data_identity_and_manifest.py`,
`backend/tests/test_candle_history.py`, `backend/tests/test_calendar_alignment.py`,
`backend/tests/test_data_manifest.py`, `backend/tests/test_manifest_bound_stock_detail.py`,
`docs/v3-execution/source-registry.md`.

Changed: `backend/app/models/market.py`, `backend/app/models/__init__.py`,
`backend/app/providers/base.py`, `backend/app/providers/yfinance_market_data.py`,
`backend/app/providers/demo_market_data.py`, `backend/app/pipelines/recommendation_pipeline.py`,
`backend/app/api/stocks.py`, `backend/app/api/portfolio.py`,
`backend/app/schemas/stock.py`, `backend/tests/test_technical_analysis.py`,
`backend/tests/test_kronos_model.py`, `backend/tests/test_stock_history.py`,
`frontend/src/lib/types.ts`, `frontend/src/app/stocks/[symbol]/page.tsx`.

Migration: `0010` (down_revision `0009`). Verified via offline SQL
generation only — no live PostgreSQL to actually apply it against (see
CONTRACTS.md C6).

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 154 passed, 13 warnings, ~20s (2026-09-14), run 3x consecutively, stable
```
New coverage: candle supersession/idempotency (4), calendar/adjustment (3+),
manifest primitive round-trip (5), manifest-bound stock-detail behavior (3 —
including a regression test verified to fail against the pre-integration
code via `git stash`, confirming it catches the real vintage-mixing bug, not
a tautology).

Frontend: `tsc --noEmit` exit 0; `npm run build` succeeds, all 12 routes.

**Not run — PostgreSQL.** Required cases "concurrent importer" and any real
multi-transaction interleaving of the candle-supersede logic remain
unproven under real locking (same blocker as Phase 01, recorded in
CONTRACTS.md C6). The idempotency/supersession logic itself is proven
correct at the SQLite/single-transaction level.

## Review findings and resolution

Self-review during integration (coordinator pass, not a separate reviewer
subagent — the three workers' outputs needed synthesis into one coherent
migration/wiring before a meaningful review target existed). Found and fixed
during integration, not just at the end:
1. The snapshot worker's flagged fork (unique constraint decision) — resolved
   as described above.
2. `_kronos_forecast`'s dict never carrying `generated_at` — would have made
   `kronos_generated_at` silently always `None` in every manifest entry;
   fixed at the source.
3. A third, previously-unflagged instance of the missing source/supersede
   filter (`/{symbol}/history`) — found while wiring the manifest into the
   neighboring `/{symbol}` endpoint in the same file.
4. Test fixture `source` mismatches in `test_stock_history.py` (used
   `"test_fixture"`, didn't match `expected_candle_source()`'s `"demo_seed"`
   under the test harness's forced `demo_mode=True`) — same class of fixture
   drift as Phase 01, fixed the same way.

## Rollback / feature-flag behavior

Migration `0010` has a tested-offline `downgrade()`. Known limitation,
documented in the migration's own docstring: downgrading after real
supersession has occurred (superseded rows now sharing a natural key with
their replacement) could conflict with re-creating the old plain unique
constraint if superseded duplicates exist — an inherent, acceptable
limitation of un-doing a soft-delete migration, not a bug. Application-level
changes (pipeline/API wiring) revert cleanly via plain code revert; no data
migration entangled beyond the schema migration itself.

## Phase gate verdict

**Conditional pass**, same shape as Phase 01: G08/G09's logic-level
requirements (identity fields, idempotent ingestion, history preservation,
immutable manifest binding actual report reads, no fake retrospective
manifest, source registry, catalogue/financial-snapshot identity contracts
frozen for Phase 03) are implemented and tested. The PostgreSQL-concurrency
portion ("concurrent importer" required case) is explicitly **blocked**, not
claimed passed, per the same environment constraint as Phase 01.

## Next ready task

Phase 03 (holdings, goals, commitments, product catalogue) — depends on
Phase 02's contracts, which are now frozen (C3a data identity, C7 manifest).
Phase 04 (Gemini adapter/scheduler) is also newly ready in parallel (depends
on 01/02's task-artifact contracts, both now satisfied) — per the guide's
scheduling table, Phase 03 and Phase 04 are a legitimate parallel track pair
for the next dispatch.
