# Phase 03 — typed holdings, goals, commitments and product catalogue

Date: 2026-09-14. Delegated to 2 parallel subagents (Financial-input worker,
Catalogue worker) per the guide's own subagent assignment table. The third
listed role (Form worker — frontend forms against frozen fixtures) was
deliberately deferred: this pass is backend-only, matching the guide's own
note that fixture-based UI work is a separately-timed track, not a
requirement to build in lockstep with every backend phase. Dispatched
alongside Phase 04's 3 workers (5 total subagents running concurrently) since
the two phases touch fully disjoint files — a deliberate deviation from the
suggested 4-slot (coordinator+3) guideline, justified by genuine file-set
independence, matching the guide's own "increase only for truly independent
work" allowance.

## Scope completed

**Financial-input worker (own: `models/holdings.py`, `models/goals.py`,
`models/commitments.py`, `api/financial_inputs.py`, new tests).**
- `HoldingsSnapshot`/`HoldingPosition` — immutable, append-only; a new
  import/edit creates a new snapshot rather than mutating an old one.
- `Goal`/`GoalEarmark` — soft-supersession on edit (same pattern as
  `MarketCandle` from Phase 02: `version`/`superseded_at`); earmark-sum
  invariant ("cannot allocate the same rupee to several goals") enforced by
  a real summing query at write time, not a denormalized total.
- `RecurringCommitment` — `budget_interpretation` required explicit at the
  API layer (422 if missing), matching V3's "must be explicit, never
  assumed" requirement.
- 9 API endpoints: holdings import preview/confirm (idempotent — same
  idempotency key returns the existing snapshot, no duplicate) + latest;
  goals create/edit/list/earmark; commitments create/list.
- **All money fields use `Numeric`/`Decimal`, never `Float`** — a deliberate
  departure from this codebase's existing Float-for-money convention
  elsewhere, per V3 section 10.1's explicit requirement. Verified: FastAPI/
  Pydantic 2.x round-trips `Decimal` correctly; a SQLite-only cosmetic
  artifact (trailing-zero padding, e.g. `4000.00` reads back as
  `4000.0000000000`) does not lose precision — tests compare by `Decimal`
  value, not string.
- 15 new tests across 3 files.

**Catalogue worker (own: `models/catalogue.py`, `services/catalogue.py`,
`services/catalogue_fixtures.py`, `api/catalogue.py`, new tests).**
- `ProductCatalogEntry` with the full V3 4.2 identity contract (external
  IDs, parent-exposure grouping for plan variants, support-level gate
  fields). Every fixture row `is_synthetic=True`, `source_ids=
  ["synthetic_fixture_v1"]` — no real reviewed product catalogue exists yet
  (recorded as an unresolved external input since Phase 00).
- `resolve_support_level()` independently re-derives the actual support
  level from populated fields rather than trusting the stored column —
  filtering (`GET /api/catalogue?support_level=`) uses the derived value.
- 7 synthetic seed entries spanning different product families, deliberately
  including incomplete ones so the gate has something real to downgrade.

**Coordinator integration (this pass).**
- One combined migration `0011` for both Phase 03 and Phase 04's 8 new
  tables (see phase-04.md for the scheduler half). Verified via
  `alembic upgrade head --sql`.
- **Fixed a real policy-gap the catalogue worker flagged in its own report**:
  `resolve_support_level()`'s terms-completeness check alone let a
  fully-populated `hybrid_fund` entry resolve to `instrument_planning`,
  contradicting V3 4.1's explicit "Hold existing positions; new selection in
  V3.1" scope for that family. Added a `_POLICY_CEILING` table (currently
  one entry: `hybrid_fund -> holdings_only`) applied as a `min()` against
  the terms-derived level — policy caps can only lower the result, never
  raise it past what terms alone justify. Updated the now-stale test
  assertion and fixture comment that predated the fix; added a dedicated
  regression test proving the ceiling holds even with every term populated
  (the exact case that broke before).
- Confirmed `models/__init__.py` and `main.py` router registration merged
  cleanly across both parallel workers with no conflicts.

## Files/contracts changed

New: `backend/app/models/holdings.py`, `goals.py`, `commitments.py`,
`catalogue.py`, `backend/app/api/financial_inputs.py`, `catalogue.py`,
`backend/app/services/catalogue.py`, `catalogue_fixtures.py`,
`backend/alembic/versions/0011_phase03_phase04_financial_inputs_catalogue_scheduler.py`
(shared with Phase 04), `backend/tests/test_holdings_api.py`,
`test_goals_api.py`, `test_commitments_api.py`, `test_catalogue.py`.

Changed: `backend/app/models/__init__.py`, `backend/app/main.py`.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 227 passed, 15 warnings, ~23s (2026-09-14), run 3x consecutively, stable
```
New coverage: holdings import/preview/idempotency/duplicate-detection,
goal earmark-sum enforcement (valid partial + rejected over-budget),
goal versioning, commitment `budget_interpretation` enforcement (18 tests
across the 3 financial-input files), catalogue support-level derivation
including the policy-ceiling fix (9 tests).

## Review findings and resolution

One real gap found and fixed during integration (the hybrid_fund policy
ceiling, described above) — found because the catalogue worker's own report
explicitly flagged it rather than silently shipping the narrower
implementation as complete. No other cross-worker conflicts found; both
workers' shared-file edits (`models/__init__.py`, `main.py`) merged cleanly.

## Rollback / feature-flag behavior

Migration `0011` (shared with Phase 04) has a tested-offline `downgrade()`.
Application-level changes revert via plain code revert; no data migration
entangled beyond the schema migration itself, since no production data
exists in any of these new tables yet.

## Phase gate verdict

**Conditional pass.** G05/G06's input-behavior requirements (typed,
validated, immutable/versioned holdings and goals; explicit budget
interpretation; support-level gating with re-derivation, not blind trust of
a stored value) are implemented and tested. Explicitly incomplete, flagged
rather than hidden:
- No real CSV file-upload parser (accepts pre-structured JSON rows only) —
  a stated follow-up, not a regression.
- Goal-edit earmark carry-forward is not automatic (orphaned earmarks on the
  old goal version aren't copied to the new one) — needs a product-policy
  decision (copy verbatim vs. re-validate against a possibly-changed target)
  out of this task's scope.
- Form worker (frontend) deferred entirely this pass.
- No real reviewed product catalogue — every entry is explicitly synthetic,
  as designed; this blocks personalized real-product planning until a
  reviewed catalogue is supplied (recorded in STATE.md, not a defect).

## Next ready task

Phase 05 (deterministic allocation and SIP engine) now has its Phase 03
dependency's contracts available (typed holdings/goals/commitments,
Decimal-based money, catalogue support-level gate) — though it still needs
an approved numeric allocation policy (`config/allocation_policy.yaml`,
reviewed sign-off) which has not been supplied; per the external-input
handling table, Phase 05 can proceed on user-selected educational scenarios
in the meantime, not personalized production allocations.
