# V3 execution state

Last updated: 2026-09-15 (all 11 phases conditional-pass; V3 execution
plan complete; docker-deployability follow-up done post-plan).

| Phase | Status | Depends on | Owning tasks / write sets | Notes |
|---|---|---|---|---|
| 00 | passed | none | coordinator (serial) | Baseline verified, contracts frozen, ledger created |
| 01 | passed (conditional) | 00 | coordinator (serial) | Logic-level G01/G02 done+tested; PostgreSQL interleaving portion blocked (no DB in this env) |
| 02 | passed (conditional) | 00; publication integration after 01 | 3 subagents (identity/snapshot/calendar) + coordinator integration | Candle history preservation, adjustment metadata, data manifest all done+tested; PostgreSQL "concurrent importer" case blocked (no DB in this env) |
| 03 | passed (conditional) | 02 | 2 subagents (financial-input/catalogue) + coordinator | Holdings/goals/commitments/catalogue done+tested; Form worker (frontend) deferred; no real reviewed catalogue supplied |
| 04 | passed (conditional) | 01/02 | 3 subagents (adapter/scheduler/benchmark) + coordinator | Gemini REST adapter + reservation scheduler done+tested at fixture level; no live credentials, no PostgreSQL for true concurrency proof |
| 05 | passed (conditional) | 01/03 | 3 subagents (all hit rate limit; 2 verified complete, 1 test file coordinator-written) | Allocation/cash-flow/policy engines done+tested; not yet wired to replace old entangled scoring path |
| 06 | passed (conditional) | 02; 04 | 3 subagents (all hit rate limit; 2 verified complete, 1 built from scratch by coordinator) | Retrieval (SSRF-safe fetch) + claim ledger done+tested at unit level; retrieval's actual network path untested |
| 07 | passed (conditional) | 01/04/06 | 3 subagents (workflow/verification/reuse), all clean, no rate-limit issues | State machine, evidence-integrated branch runner, assessment schema, artifact reuse all done+tested; no end-to-end orchestration loop yet |
| 08 | passed (conditional) | 03/05; 06/07 | coordinator (glue) + 3 subagents (planning UI/research UI/recovery), all clean | Holdings/goals/catalogue/research pages live; research API built; useJobPolling bug fixed; Phase 05 still not wired to any API |
| 09 | passed (conditional) | 02 | 2 subagents (forecast/backtest), both clean | Kronos wrapper validated 2 layers deep, calibration artifact schema hardened; backtest total-return-vs-price-return convention documented; no live held-out MAE/RMSE evaluation possible in this env |
| 10 | passed (conditional) | 05/07/08/09 | 3 subagents (financial/research/performance reviewers), all clean | Full G01-G19 gate matrix built; 2 real bugs found+fixed (Fact.support_status never persisted; fully_verifiable/numerical_check honesty caveats added); financial round-trip invariants hand-verified independently |
| 11 | passed (conditional) | 10 | 3 subagents (packaging/rehearsal/documentation), all clean | Real migration startup barrier added+tested; 2 real CWD-relative path bugs fixed; docker-compose worker depends_on fixed; SETUP.md corrected+expanded; Postgres restore/docker rehearsal itself genuinely blocked (no docker/postgres binaries in this environment) |

## Current integration point

- Backend: `backend/` at working tree HEAD (`e0d27ea`) plus substantial
  uncommitted V2 work (see `git status` in phase-00.md). Alembic head:
  `0013` as of Phase 11 (was stale at `0009` in this line since Phase 00 —
  corrected 2026-09-15, flagged by the Phase 11 packaging worker).
- Frontend: `frontend/` at working tree HEAD plus uncommitted V2 work.
  `tsc --noEmit` clean; `npm run build` succeeds.
- No commits made by this V3 execution session yet.

## Unresolved external inputs (not implementation tasks)

- **PostgreSQL instance** — needed for Phase 01 G01/G02 concurrency gate and
  Phase 02's concurrent-importer case. Not available in this environment
  (no server binary, no docker). Blocks those specific gates only.
- **Gemini keys / project inventory** — needed for Phase 04's live
  measurement (not its fixture/adapter implementation). Not requested yet;
  Phase 04 not started.
- **Original Postgres dump** — supplied 2026-09-15 (`pg_dumpall`, real data:
  31,553 market_candles rows across 50 instruments, 100 fundamentals rows,
  44 recommendations, at `alembic_version 0004`). Statically diffed against
  migrations `0005`-`0013`: all are additive `CREATE TABLE`s or
  backfill-then-`NOT NULL` column adds with correct server_defaults, one
  pre-deletion of true duplicates before a unique constraint (`0007`) — no
  migration found that would break against real pre-existing data. Still
  BLOCKED from an actual restore/upgrade run: no docker/postgres binary in
  this environment. `scripts/restore_postgres_backup.sh` + SETUP.md §14
  written so a real restore is one command once docker exists somewhere.
  NDA: this dump contains real TrueData-sourced rows — kept local-only,
  gitignored (`*.sql`, `backups/`), never referenced by any Dockerfile
  `COPY`, never committed.
- **Reviewed financial product catalogue / allocation policy** — needed for
  Phase 03/05 beyond synthetic fixtures. Not requested yet.

## Next ready task

All 11 phases (00-11) now have a status. This was the last phase in the
V3 execution plan — no next phase exists. Remaining real work is
addressing the disclosed gaps carried forward below, at the user's
discretion, not further phase execution.

## Docker-deployability follow-up (2026-09-15, post-plan, user request)

Not a numbered V3 phase — done at explicit user request after Phase 11
closed, since Phase 11's packaging worker only got as far as static
config review (no docker binary in this environment). Coordinator work,
no subagents (small, single-thread, config-only change set):

- `backend/Dockerfile`: pinned the Kronos vendor clone to an exact commit
  SHA (`67b630e67f6a18c9e9be918d9b4337c960db1e9a`, read directly from
  `vendor/kronos/.git` — not guessed) instead of an unpinned `git clone
  --depth 1` of master; real shallow-fetch-by-SHA pattern (`git init` +
  `remote add` + `fetch --depth 1 origin <sha>` + `checkout FETCH_HEAD`).
  Added a real `HEALTHCHECK` hitting the existing `/health` endpoint
  (`app/main.py:83`).
- `docker-compose.yml`: added a matching `healthcheck:` block to the
  `backend` service; upgraded `worker`'s and `frontend`'s `depends_on:
  backend` from `service_started` to `service_healthy` — closes the race
  Phase 11 only narrowed (a genuinely healthy API/migration step, not
  just "the process started, might immediately exit on a schema
  mismatch"). Corrected a stale comment (said "next.config.js's rewrite
  proxy" — the real mechanism is the Route Handler proxy at
  `frontend/src/app/api/[...path]/route.ts`).
- `.env.example`: added the missing `GEMINI_*` vars (flagged but not
  fixed by Phase 11's documentation reviewer — `GEMINI_BASE_URL`,
  `GEMINI_API_KEY`, `GEMINI_FLASH_LITE_MODEL`, `GEMINI_FLASH_MODEL`,
  matching `app/core/config.py`'s actual field names).
- Validated: `docker-compose.yml` parses as valid YAML (4 services
  present, checked with PyYAML — no docker binary here to actually
  build/run it). Backend test suite unaffected (config/build files only,
  no application code changed) — still 379 passed.
- Still genuinely blocked, same as every phase: no docker/postgres
  binaries in this environment, so none of this has been run through a
  real `docker compose up` — static review + YAML validation only. First
  real docker build should be treated as the actual first test of this
  config, not assumed working from review alone.

## Rate-limit lesson (session-level, not phase-specific)

Batching 6 subagents in one dispatch (Phase 05 + Phase 06 together) hit
this session's rate limit; all 6 terminated with a 429 mid-task. Phase 07's
follow-up dispatch (exactly 3 subagents, matching that phase's own table)
completed with zero issues — confirms 3-subagent batches are the right
size for this session's rate budget; stick to that even when two phases
seem file-independent enough to parallelize together.

## Known unresolved items carried forward

- PostgreSQL unavailable — blocks the concurrency portion of Phase 01/02's
  gates and now also Phase 04's daily-spend-cap atomicity proof, the same
  way each time.
- One test anomaly (StaleDataError in a full-pipeline mismatched-token
  scenario, not reproduced in isolation) flagged in `phase-01.md`,
  unresolved, not blocking (the underlying mechanism is proven correct by
  6 passing isolated tests + code inspection).
- Gemini keys/project inventory still not requested — needed only for
  Phase 04's live measurement, not its adapter/scheduler implementation.
  Also unresolved: which real Gemini REST surface to target
  (`generateContent` vs. a newer "Interactions API" — see phase-04.md) —
  needs re-verification once a live key exists.
- Reviewed financial product catalogue / allocation policy still not
  supplied — Phase 03 (done) used explicitly-synthetic fixtures; Phase 05
  will need the same treatment (user-selected educational scenarios, not
  personalized production allocations) until a reviewed policy exists.
- Phase 03's "Form worker" (frontend holdings/goals forms) deferred —
  backend contracts exist and are tested; no frontend consumes them yet.
- Phase 03's goal-edit earmark carry-forward needs a product-policy
  decision (out of scope, flagged not fixed).
- Phase 04's `ModelCallReservation` daily-spend-cap enforcement is a soft
  (check-then-insert) guarantee, not atomic — flagged, not silently treated
  as hard.
- Phase 05's allocation/cash-flow/policy engines are not yet wired to
  replace the old entangled `portfolio_score`-in-scoring path in
  `subscores.py`/`final_score.py`/`recommendation_pipeline.py`.
- Phase 06's `retrieval.py` actual network fetch/redirect/streaming path is
  untested (SSRF pre-checks and text extraction ARE tested for real) —
  needs a local test server or lower-level httpcore mock; `respx`'s usual
  transport mocking doesn't cleanly intercept the custom pinned backend.
- Phase 06's PDF extraction is stubbed (raises a clear error) — no PDF
  library installable in this environment (no working `pip`); `pypdf`
  would be the natural dependency once approved/installable.
- Phase 07: no end-to-end orchestration loop yet glues
  session/checklist/branches/contradiction-check/synthesis/verification/
  publish into one real research call — each piece is unit-tested in
  isolation only.
- Phase 07: branch-level cancellation isn't wired (only session-level is);
  `run_branch` doesn't check session state before executing.
- Closed 2026-09-15 (fast pass): Phase 05's engine now has a real API
  (`POST /api/plans`, `GET /api/plans/scenarios`) — 5 new tests. Known
  narrowing: works at the asset-class level only; no per-symbol
  stock-cap/issuer-concentration check runs (HoldingPosition has no
  asset-class classification yet, so current_exposure is caller-supplied,
  not auto-derived from Phase 03 holdings) — `validate_constraints` is
  called with no per_symbol_weights rather than faking a check with no real
  data behind it.
- Phase 09 closed 2026-09-15: Kronos wrapper hardened (calibration lookup
  can no longer crash `forecast()` or accept malformed hit_rate); backtest
  total-return-vs-price-return convention now documented + regression
  -tested. No live held-out MAE/RMSE Kronos accuracy measurement possible
  in this environment (no real HF weights, no PostgreSQL) — still an open
  external-input gap, not a code defect.
- Phase 10 closed 2026-09-15: full G01-G19 gate matrix in
  `phase-10-gate-matrix.md`. Fixed: `Fact.support_status` now actually
  persisted by `verify_fact` (was silently stuck at "unknown" forever).
  Disclosed via new docstring caveats, not fixed (real feature scope):
  `fully_verifiable` proves internal consistency (fact traces to its own
  extraction passage) not independent multi-source corroboration;
  `numerical_check` proves a numeric input exists, not that the formula
  recomputes correctly (no per-formula recompute registry exists yet).
  `api/plans.py` still doesn't wire `issuer_concentration_limit` — no
  asset-class/per-symbol data flows from holdings into the planning API
  yet, same root cause as the existing per-symbol-constraint gap below.
- Full suite at 375 passed as of Phase 10 close (`backend/ pytest tests/`).
- Phase 11 closed 2026-09-15: new `backend/app/core/migration_barrier.py`
  wired into both `main.py` startup and `worker.py`'s poll-loop entrypoint
  — fails loudly on an `alembic_version` mismatch or missing table instead
  of silently running against a stale/unmigrated schema, tested against
  scratch SQLite (4 new tests). Fixed 2 real CWD-relative path bugs found
  by the packaging worker: `kronos_calibration.py`'s hardcoded
  `Path("./data/cache/...")` (now `DATA_DIR`-anchored) and
  `kronos_repo_path`'s default (`"./vendor/kronos"`, only ever correct
  because `run.sh` happens to `cd` into `backend/` first — from repo root
  it silently resolved to nothing and Kronos degraded to `None` with no
  error, never surfaced before this audit). Added missing
  `backend/.dockerignore`/`frontend/.dockerignore` (neither existed
  despite both Dockerfiles doing `COPY . .`). Fixed `docker-compose.yml`'s
  worker service having no `depends_on`/restart policy against backend's
  migration step — untested against real `compose up` (no docker binary
  here), YAML-valid only. SETUP.md corrected (stale signup step from
  pre-single-user-mode, stale "59 tests" claim) and expanded (V3 session
  changes section, Kronos vendor commit SHA, rollback section via
  `alembic downgrade`, expanded known-gaps list).
- Real, disclosed Phase 11 blocker: this environment has no
  docker/postgres/pg_ctl/initdb binaries at all — the actual "restore into
  separate staging Postgres, rehearse rollback against it" instruction
  (V3 Phase 11 instruction 4) is not possible here. Closest honest proxy
  run instead: `Base.metadata.create_all` against a fresh SQLite file +
  real CRUD round-trip on 3 newer V3 models — proves ORM schema-level
  correctness only, NOT Alembic migration-ordering correctness (Alembic's
  own chain is genuinely Postgres-only from revision `0001` onward —
  `pgcrypto`/`postgresql.UUID`, confirmed by attempting `alembic upgrade
  head` against SQLite and watching it fail immediately) and NOT a
  Postgres restore/rollback proof.
- Real, disclosed Phase 11 finding: a plain `git clone` of this repo's
  committed HEAD only contains Alembic migrations 0001-0002 — all of
  V2/V3's migrations (0003-0013) are still uncommitted working-tree files.
  A genuinely new teammate cloning today would not reach current schema
  state. This has been true and disclosed since Phase 00 ("no commits made
  by this V3 execution session yet" — still true); flagged again here
  since Phase 11's clean-start rehearsal is the first task to actually
  attempt a clone and hit it directly. No commits were made to address
  this (out of this audit's scope — committing is the user's call).
- Full suite at 379 passed as of Phase 11 close (`backend/ pytest tests/`).
