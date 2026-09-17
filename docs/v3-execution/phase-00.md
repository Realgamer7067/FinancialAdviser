# Phase 00 — baseline, ownership map, contracts

Date: 2026-09-14. Executed serially by the coordinator (no subagents) — this
phase is read/inspect/record work over a small set of already-produced
documents; the guide's own rule ("do not spawn agents solely to read or
rewrite the same large document") applies directly, and there was no
independent-write-set task to delegate.

## Scope completed

1. Read `docs/V3-PHASEWISE-EXECUTION.md`, `docs/V3-IMPLEMENTATION-PLAN.md`
   (skimmed for phase-relevant sections per instruction, full detailed read
   deferred to the phase that needs each section), `docs/V2-IMPLEMENTATION-CHECK.md`.
2. Verified `git status` — working tree has the substantial uncommitted V2
   session's changes across `backend/app/**`, `frontend/src/**`, migrations,
   tests, and config. Nothing reset, nothing committed by this session.
3. Independently re-verified 4 of the 8 gaps listed in
   `V2-IMPLEMENTATION-CHECK.md` by reading the actual current source (not
   trusting the prior report blindly): all 4 spot-checked gaps are still
   present exactly as described —
   - `backend/app/api/portfolio.py:48-61` — `_load_latest_portfolio` has no
     join to the producing run, no newest-completed-run check.
   - `backend/app/pipelines/recommendation_pipeline.py:782-784` — final
     publication commit (`council_run.status = "done"`) has no
     `worker_token` fencing check at commit time.
   - `backend/app/pipelines/recommendation_pipeline.py:248-261`
     (`_get_cached_fundamentals`) — no source/mode filter.
   - `backend/app/api/stocks.py:39-46` — `latest_candle` API read has no
     source filter (the pipeline-side ingestion fix from the V2 session did
     not cover this read path).
   The remaining 4 gaps (research still fixed-council, Kronos/news still
   ahead of a redundant re-rank, SIP/holdings not unified, useJobPolling
   resume-clears-on-any-error) were not independently re-verified line-by-line
   this phase but are consistent with source inspected during the prior V2
   session; carried forward as-reported pending each owning phase's own
   verification.
4. Ran baseline checks (exact commands and results in `CONTRACTS.md` §C6):
   - Backend, doc's suggested first group: 36 passed.
   - Backend, doc's suggested second group: 75 passed.
   - Backend, full suite (`tests/`): **132 passed**, 13 warnings, ~20s. No
     stall reproduced in this environment (differs from the prior report's
     "some async tests stalled in the sandbox" note — recorded as
     non-reproduction, not as disproof of the original observation).
   - Frontend: `tsc --noEmit --incremental false` exit 0; `npm run build`
     succeeded, all 12 routes built.
5. Checked Alembic state: single linear head `0009`, no branches, matches
   the 9 migrations produced during the V2 session
   (`0001`..`0009`, initial schema through insider/promoter-holding split).
6. Checked PostgreSQL availability: **unavailable**. `pg_isready` → no
   response; `pg_ctl`/`postgres`/`initdb`/`docker` binaries all absent from
   PATH. Recorded in `CONTRACTS.md` §C6 as a blocking condition for the
   PostgreSQL-dependent gates only (G01/G02 concurrency proof), not a phase
   failure, per the guide's explicit handling rule.
7. Checked private-artifact exclusion: `.gitignore` already excludes
   `.env`, `data/cache/`, TrueData-covered paths (`.TD_API_Docs/`,
   `data/truedata_raw/`, `*truedata*`). No new sensitive artifacts were
   placed in the repository this phase. No database dump was supplied or
   found.
8. Wrote `docs/v3-execution/STATE.md` and `docs/v3-execution/CONTRACTS.md`
   (C1-C6: run-outcome, job-attempt/publication-ownership, data-identity,
   money/allocation, error/evidence-missingness, test-environment
   contracts). This file.

## Files/contracts changed

- New: `docs/v3-execution/STATE.md`, `docs/v3-execution/CONTRACTS.md`,
  `docs/v3-execution/phase-00.md`.
- No application code changed this phase.

## Tests

See `CONTRACTS.md` §C6 for exact commands/results. Summary: 132/132 backend
tests passed; frontend `tsc`/`build` both clean. No PostgreSQL, no live
provider, no browser checks performed (correctly out of Phase 00 scope; PG
recorded as blocked for later phases that need it).

## Review findings and resolution

Self-review only (no independent reviewer subagent used for a
read/inspection phase, matching the guide's serial-execution allowance).
Finding: the prior V2-IMPLEMENTATION-CHECK.md's gap list is accurate against
current source for every gap spot-checked; no gap in that list appears
already fixed. No new gap found beyond that list during this phase's
inspection depth.

## Rollback / feature-flag behavior

Not applicable — no code changed.

## Phase gate verdict

**Passed.** Baseline evidence recorded, ownership/contract documents exist
and are consistent with Phases 01/02's needs, no needed current V2 change was
identified as omitted from the carry-forward register, PostgreSQL
unavailability is recorded against only its dependent gates.

## Next ready task

Phase 01 (depends only on 00 — ready). Target the two P0 gaps confirmed in
step 3 above: portfolio stale-outcome (C1) and publication fencing (C2).
PostgreSQL-dependent interleaving tests (required-case #4, "simultaneous
claim") stay blocked until an instance is available; SQLite-provable fencing
logic and the exact-outcome resolver proceed now.
