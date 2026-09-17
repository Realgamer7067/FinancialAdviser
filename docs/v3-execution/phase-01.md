# Phase 01 — stale outcomes and worker publication correctness

Date: 2026-09-14. Executed serially by the coordinator (no subagents spawned
— both tasks required context already held from Phase 00's verification and
touched overlapping conceptual ground (the same exact-run-outcome pattern
applied to two endpoints, plus a fencing fix tightly coupled to the pipeline
code just inspected); delegating would have meant re-deriving that context in
a fresh agent for no net benefit, matching the guide's serial-execution
allowance in §2.4/§3).

## Scope completed

**Task 1 — exact-run outcome resolver for portfolio (C1).**
- `backend/app/api/portfolio.py`: replaced `_load_latest_portfolio` (picked
  the newest `PortfolioRecommendation` row with no link back to the run that
  produced it) with `_resolve_latest_portfolio`, which finds the newest
  **completed** `CouncilRun` first, then looks for a `PortfolioRecommendation`
  bound to that exact run. Three outcomes are now distinguishable: no run has
  ever completed (404), the newest completed run produced no allocation
  (200, `has_allocation: false`, `reason` set, empty allocations/cash=1.0),
  and a real current allocation (200, `has_allocation: true`).
- `POST /allocate` uses the same resolver; a stale/absent current allocation
  now 404s with the reason instead of silently allocating rupees against an
  old run's weights.
- Same-file C3 fix folded in (same read-path class of bug, cheap to close
  while already in the file): `/allocate`'s last-price lookup now filters
  `MarketCandle.source` by the current DEMO_MODE, via a new shared
  `app/providers/mode.py` (also used to refactor the pipeline's own
  duplicate copy and to close the identical gap in `api/stocks.py`'s
  candle/fundamentals reads, verified open in Phase 00 step 3).
- Frontend: `PortfolioOut` type gained `has_allocation`/`reason`;
  `frontend/src/app/portfolio/page.tsx` renders an explicit empty state
  instead of assuming `portfolio.allocations` is always populated.

**Task 2 — publication ownership fencing (C2).**
- New `backend/app/pipelines/publication.py`: `verify_ownership(db, job_id,
  worker_token)` performs a single atomic conditional `UPDATE ... WHERE id =
  :job_id AND worker_token = :token` and raises `StalePublicationError` if
  zero rows matched. One SQL statement has no client-side read-then-write
  gap, closing the "read-compare-unconditional-write" pattern flagged in
  Phase 00.
- `backend/app/pipelines/recommendation_pipeline.py`: `verify_ownership` is
  now called immediately before the pipeline's single final `await
  db.commit()` — inside the SAME long-lived, mostly-uncommitted transaction
  the whole run's `CouncilRun`/`Recommendation`/`PortfolioRecommendation`
  rows belong to (per that function's own docstring). If the check fails,
  nothing below it — including everything added earlier in the same
  transaction — is committed.
- `backend/app/worker.py`: `_process_job` catches `StalePublicationError`
  specifically and drops the attempt (rollback, log, return) rather than
  recording it as a job failure — a superseded attempt isn't a failure, the
  newer attempt owns the outcome.

## Files/contracts changed

- New: `backend/app/pipelines/publication.py`, `backend/app/providers/mode.py`,
  `backend/tests/test_publication.py`.
- Changed: `backend/app/api/portfolio.py`, `backend/app/api/stocks.py`,
  `backend/app/pipelines/recommendation_pipeline.py`, `backend/app/worker.py`,
  `frontend/src/lib/types.ts`, `frontend/src/app/portfolio/page.tsx`.
- Changed tests: `backend/tests/test_portfolio_allocation.py` (fixture source
  fix + new stale-outcome regression test).
- No migrations required this phase (no new persisted columns).

## Tests

From `backend/`:
```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 139 passed, 13 warnings, ~20s (2026-09-14)
```
New/changed coverage: `test_portfolio_allocation.py::test_newer_empty_run_supersedes_older_populated_portfolio`
(verified it fails against the pre-fix code via `git stash`, confirming it
catches the real regression, not a tautology); `test_publication.py` (6
tests: match/mismatch/reclaim-after-start/no-op-for-unfenced-path/lease-
renewal/no-partial-write-on-failure).

From `frontend/`: `tsc --noEmit --incremental false` exit 0.

**Not run — PostgreSQL interleaving:** environment has no PostgreSQL
instance (confirmed in Phase 00). The "simultaneous claim," "lease expires
during long work," "old worker resumes," "crash before publication," "retry
after publication acknowledgement lost" required cases are proven at the
SQLite/unit level (the atomic-UPDATE mechanism itself, and one full-pipeline
mismatched-token scenario at the code-inspection level — see below) but
**not** under real concurrent transactions. This gate is blocked, not
passed, per CONTRACTS.md C6.

**One unresolved test anomaly, disclosed rather than hidden:** an attempted
full end-to-end pipeline test (`run_recommendation_pipeline` with a
mismatched `job_id`+`worker_token` pair, exercising the real screening/
council/portfolio path start-to-finish) hit a `sqlalchemy.orm.exc.
StaleDataError` on the `council_runs` UPDATE during the final autoflush, a
symptom not reproduced by an isolated repro of the same `verify_ownership`
call against a minimal schema (which behaved correctly — rowcount 0, no
autoflush error). The full-pipeline version of the test was removed rather
than shipped flaky or silently skipped; `verify_ownership` itself is
covered by 6 passing focused tests and the pipeline's call site was verified
correct by direct code inspection (same transaction, immediately before the
only commit). This anomaly should be investigated by whichever phase next
touches the pipeline's session-lifecycle in depth — it may be a genuine
SQLite/aiosqlite autoflush-ordering quirk specific to combining a `job_id`+
mismatched-token run with the rest of the pipeline's object graph, not
necessarily a real bug, but it was not run down further here.

## Review findings and resolution

Self-review (serial execution, no separate reviewer subagent — see note
above on why this phase wasn't delegated). One real defect found and fixed
during implementation, not just at the end: the FinRL-style renormalization
bug class from the prior V2 session's portfolio work was re-checked here and
confirmed NOT present in the C1 changes (the resolver doesn't touch
allocation math, only which run's allocation is selected).

## Rollback / feature-flag behavior

No migration, so no schema rollback needed. Behavior change is a pure logic
fix; reverting `backend/app/api/portfolio.py`, `recommendation_pipeline.py`,
`worker.py` and deleting `publication.py`/`mode.py` restores prior behavior
exactly (git revert of this phase's diff is sufficient — no data migration
entangled).

## Phase gate verdict

**Conditional pass.** G01/G02's logic-level requirements (exact-run outcome
resolution, atomic-conditional-write fencing, superseded-attempt handling)
are implemented and tested. The PostgreSQL-interleaving portion of the gate
is explicitly **blocked** pending a PostgreSQL instance — not claimed as
passed. Per the guide's own rule ("independent Phase 02 work may continue,
concurrency-dependent release cannot"), this does not block starting Phase
02's independent work, only this gate's own final release-readiness claim.

## Next ready task

Phase 02 (depends on 00; publication integration after 01 — satisfied) is
next-ready: canonical data identity and immutable snapshots. Phase 02's own
instructions largely restate/extend the C3 source/mode isolation work already
started here (pipeline + both API read paths now fixed); its real remaining
scope is the immutable-manifest binding (report → exact data/feature
versions) and the dated-return/session-alignment/missingness rules beyond
what Phase 01 touched.
