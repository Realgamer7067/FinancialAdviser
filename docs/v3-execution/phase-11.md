# Phase 11 — release rehearsal (fast pass)

Date: 2026-09-15. Coordinator dispatched 3 parallel subagents (packaging,
rehearsal, documentation reviewer) per this phase's own table. All 3
clean, no rate-limit issues. This is the last phase in the V3 execution
plan.

## Scope completed

- **Packaging worker**: added a real migration startup barrier
  (`backend/app/core/migration_barrier.py`) wired into both `main.py`
  startup and `worker.py`'s poll-loop entrypoint — resolves the expected
  Alembic head via `ScriptDirectory.get_current_head()` and compares
  against the DB's `alembic_version` via `MigrationContext`; fails loudly
  on mismatch or missing table instead of running against a stale schema.
  4 new tests against scratch SQLite. Found and fixed 2 real
  CWD-relative path bugs (`kronos_calibration.py`'s hardcoded cache path,
  `kronos_repo_path`'s default that only worked because `run.sh` happens
  to `cd` into `backend/` first). Added missing `.dockerignore` files for
  both services. Fixed `docker-compose.yml`'s worker having no
  `depends_on`/restart against backend's migration step.
- **Rehearsal worker**: attempted a genuine clean-start simulation
  (fresh clone/worktree, fresh venv, `pip install`) and found a real,
  serious gap — a plain `git clone` of committed HEAD only reaches
  Alembic migrations 0001-0002; all of V2/V3 (0003-0013) is still
  uncommitted. Also found requirements.txt has no documented Python
  version pin (bit a naive `python3.14` attempt — `torch==2.4.1` has no
  wheel for it; Python 3.12, as SETUP.md's own `uv` command implies,
  works cleanly). Proved Alembic's migration chain is genuinely
  Postgres-only (fails immediately on SQLite at revision 0001 —
  `pgcrypto`/`postgresql.UUID`), so used `Base.metadata.create_all` +
  real CRUD as the closest honest SQLite-level proxy for schema
  correctness — explicitly not a migration-ordering or Postgres-restore
  proof. Confirmed no feature-flag system exists for any V3 feature
  (only `demo_mode` exists); confirmed Kronos calibration already
  degrades gracefully by design.
- **Documentation reviewer**: ran every documented setup command for
  real. Fixed 2 stale claims in SETUP.md (a signup step removed in the
  single-user-mode commit; a "59 tests" count now 375+). Added: a "what's
  new since the original build" section, a Kronos vendor commit SHA
  (none was documented before), a rollback section (`alembic downgrade`,
  explicit about no feature-flag system existing), and expanded known
  gaps with real items found this session (Postgres-unavailable-in-dev,
  `/api/plans` per-symbol gap, research pipeline PDF-stub/no-full-loop).

## Files changed

New: `backend/app/core/migration_barrier.py`,
`backend/tests/test_migration_barrier.py`, `backend/.dockerignore`,
`frontend/.dockerignore`.

Changed: `backend/app/main.py`, `backend/app/worker.py` (barrier wired
in), `backend/app/backtesting/kronos_calibration.py` (path fix),
`backend/app/core/config.py` (path fix, dead-config note),
`docker-compose.yml` (worker depends_on/restart), `SETUP.md` (corrections
+ 2 new sections), `docs/v3-execution/STATE.md` (stale Alembic-head note
corrected: 0009 → 0013).

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 379 passed, 17 warnings
```

## Rollback

Additive/isolated: the migration barrier is a new startup check (revert
by removing the two call sites — reverts to pre-Phase-11 silent-schema-
mismatch behavior, strictly worse); the two path fixes are corrections
of previously-silent wrong defaults (reverting them reintroduces the
original latent bug); `.dockerignore` files and `docker-compose.yml`
change are build/deploy config only, no runtime code path affected; all
documentation changes are prose-only.

## Phase gate verdict

**Passed (conditional).** G18 (portability: clean migration/startup/
staging restore, documented rollback) — partially evidenced: migration
startup barrier is real and tested; SQLite-level schema correctness
proxy is real and tested; genuine Postgres restore/rollback rehearsal
and real `docker compose up` validation remain BLOCKED — no
docker/postgres binaries exist in this environment, consistent with
every other phase's disclosure of the same limitation. Real,
previously-undiscovered gap surfaced and disclosed, not fixed (a commit
decision belongs to the user): none of V2/V3's work is committed, so a
genuine clean clone does not reach current schema/feature state.

## Next ready task

None — this is the last phase (00-11) in the V3 execution plan. All 12
phase reports exist in `docs/v3-execution/`. Remaining real work is
addressing disclosed gaps at the user's discretion:
committing the substantial uncommitted V2/V3 work (a real decision, not
made here), obtaining PostgreSQL/docker for genuine concurrency and
restore proofs, a Gemini API key for live model measurement, real
Kronos HF weights for live accuracy measurement, and a reviewed
financial product catalogue/allocation policy for anything beyond
synthetic fixtures.
