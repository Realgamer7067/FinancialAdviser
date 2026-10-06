# Setup & Usage Guide

This guide includes setup and historical development notes. Start with [README.md](README.md) for the current Financial Advisor portfolio workflow and [ARCHITECTURE.md](ARCHITECTURE.md) for current versus earlier modules.

## 1. What you need (and what you don't)

| Thing | Required? | Notes |
|---|---|---|
| Docker + Docker Compose | Recommended | Easiest path -- runs Postgres, backend, worker, frontend together |
| Python 3.11 + local Postgres | Alternative to Docker | For `./run.sh` (no-Docker path) |
| Node.js 20+ | Yes, for the frontend | `node --version` |
| Qwen API key (DashScope, OpenRouter, or self-hosted vLLM) | No | Without it, the council/planner steps are skipped and recommendations fall back to deterministic scoring only, with reduced confidence -- this is a documented degrade path (Section 50 of the build plan), not a crash |
| GPU | No | Kronos and FinBERT are sized to run on CPU |

Market data comes from Yahoo Finance -- no account, no API key, no KYC. `DEMO_MODE=true`
still exists for a fully offline/synthetic run; set it `false` to use real Yahoo Finance data.

The earlier demo-provider path can run without external accounts with `DEMO_MODE=true` and blank model keys. The newer `/api/v4` portfolio screens may start empty and need manual/CSV holdings and fictional profile facts for rehearsal. Demo mode does not make every broker, catalogue or research integration offline.

## 2. First run (Docker)

```bash
cd Project-EX2
cp .env.example .env
docker compose up --build
```

Wait for all four services to report healthy/ready (first build pulls Postgres, installs
Python deps including torch/transformers, and builds the Next.js app -- this can take
several minutes the first time).

Open:
- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
- Admin/debug: http://localhost:8000/admin/debug

Private mode: host ports 3000, 8000 and 5432 are bound to 127.0.0.1 only; PostgreSQL retains a loopback host port for local tools. Set a
non-default `POSTGRES_PASSWORD` in `.env` before `docker compose up` (it does not change
the password of an existing `postgres_data` volume -- rotate with `ALTER USER` or recreate
the volume). Verify from another machine that ports 3000/8000/5432 refuse connections
before importing real holdings.

## 3. First run (no Docker)

You need a Postgres instance reachable at the `DATABASE_URL` in `.env` (a local
`postgres` install, or point it at any reachable Postgres).

```bash
cp .env.example .env   # edit DATABASE_URL if not using the default local Postgres
./run.sh                # installs backend deps, runs migrations, starts worker + API
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:3000, backend at http://localhost:8000.

## 4. Using the app as a user

> Current presentation path: Holdings → Financial profile → Goals/Risk → Plan new investment or Compare a change. The older recommendation flow below is retained but disabled by default with `LEGACY_PIPELINE_ENABLED=false`. See [the demo guide](docs/presentation/DEMO_AND_REVIEWER_QA.md) for a rehearsed final-review sequence.

This is the actual workflow the UI walks you through -- there is no chat interface
anywhere; everything is forms and cards (by design, see build plan Section 3).

This is a **single-user** app -- there is no signup/login. Multi-user auth (JWT/
login/signup) was deliberately ripped out (see commit `e0d27ea`): this is a
research/demo tool, not a deployed multi-tenant product, and auth added no value
here. The landing page (`/`) links straight to `/onboarding` against one seeded
implicit user.

1. **Onboarding** (`/onboarding`) -- fill in the
   financial-profile form (income, capital, horizon, objective, etc.) and answer the
   3 risk-questionnaire radio-button questions (portfolio-drop reaction, priority,
   loss tolerance). Submitting computes your risk profile **deterministically** --
   no AI involved in this step -- and shows you the result (e.g. "moderate, score
   58/100").
2. **Dashboard** (`/dashboard`) -- shows NSE market status, NIFTY level, your risk
   profile, and a "Run analysis" button.
3. **Run analysis** -- this does NOT block the browser. It creates a background job
   and the dashboard polls it every few seconds until it's done (typically well
   under a minute in demo mode; longer if Qwen/Kronos are wired in or the universe
   screening does real network calls). Behind the scenes this runs
   the full pipeline: screen the Nifty50 seed universe -> Kronos forecast -> news
   sentiment -> portfolio optimization -> Qwen council (if configured) ->
   deterministic scoring -> risk gate.
4. **Recommendations** (`/recommendations`) -- once the job is done, see ranked stock
   cards: 🟢 Strong Candidate / 🟢 Candidate / 🟡 Watchlist / ⚪ No Clear Opportunity.
   It is normal and expected to sometimes see "No Clear Opportunity" for everything --
   the system is built to say that rather than force a pick (Section 20, hard rule).
5. **Stock detail** (click any card) -- shows why it was selected, the risks, and an
   expandable "advanced analysis" section with the raw fundamentals/technicals/Kronos
   forecast/news sentiment behind the recommendation.
6. **Portfolio** (`/portfolio`) -- the suggested allocation across the final
   candidates from the mean-variance optimizer, with expected return/volatility/Sharpe.
7. **Settings** (`/settings`) -- view your profile; re-run onboarding to update it
   (creates a new versioned profile, doesn't overwrite history).

Also present since this session's V3 work (see section 13 below for details, not
part of the original numbered walkthrough): `/holdings` and `/goals` (portfolio/
goal tracking), `/catalogue` (financial-product catalogue), `/research` (deep
research sessions), `/planning` (SIP/goal planner), `/compare` (2-3 stock
comparison).

## 5. Wiring in real providers

### Market data (real Yahoo Finance instead of demo data)

Set `DEMO_MODE=false` in `.env` and restart the backend -- that's it, no account, no key.
`YFinanceMarketDataProvider` (`app/providers/yfinance_market_data.py`) is the same free,
unofficial, rate-limited source already used for fundamentals; not suitable for a licensed
production product, but fine for research/testing.

### Qwen (the analyst council)

Any OpenAI-compatible endpoint works. Put its base URL, API key, and model name in
`.env` as `QWEN_BASE_URL` / `QWEN_API_KEY` / `QWEN_MODEL`. Examples:
- **DashScope** (Alibaba's official Qwen API): `.env.example` already has the right
  `QWEN_BASE_URL` default -- just add your `QWEN_API_KEY`.
- **OpenRouter**: `QWEN_BASE_URL=https://openrouter.ai/api/v1`, use an OpenRouter key.
- **Self-hosted vLLM**: point `QWEN_BASE_URL` at your server's OpenAI-compatible
  endpoint (e.g. `http://localhost:8001/v1`); `QWEN_API_KEY` can be anything non-empty.

Without a key, the planner/council steps are skipped and every recommendation falls
back to the deterministic evidence/score/risk-gate path with a note that the judge
was unavailable -- it does not crash.

## 6. Admin/debug page

`http://localhost:8000/admin/debug` (also linked from `/admin` in the frontend) shows:
- whether demo mode / Qwen are configured
- data-source sync status
- the last 20 recommendation jobs and their status/errors

Useful first stop when something looks wrong. **Not authentication-protected in this
MVP** -- don't expose it on a public network as-is.

## 7. Running tests

```bash
cd backend
uv pip install -r requirements.txt
pytest
```

375 unit/integration tests as of the V3 session close (verified by an actual run --
`cd backend && .venv/bin/python -m pytest -q` -> `375 passed`), up from the 59 this
doc originally shipped with. Coverage now spans risk scoring, deterministic
sub-scores, final scoring/risk-gate logic, fundamental-ratio derivation, technical
indicators, backtest metrics, the mean-variance optimizer's solver-failure
fallbacks, plus the V3 additions in section 13 below (holdings/goals, the
allocation/planning engine, research/claim-verification, the model adapter, and
Kronos calibration). All 375 run against SQLite in-memory fixtures, so they pass
without a live Postgres instance.

## 8. Kronos setup (not pip-installable)

The Kronos GitHub repo (shiyu-coder/Kronos) has no `setup.py`/`pyproject.toml` --
`pip install git+https://...` installs nothing usable. `run.sh` and the Dockerfile
both `git clone` it instead:

```bash
git clone --depth 1 https://github.com/shiyu-coder/Kronos.git backend/vendor/kronos
```

`app/models_iface/kronos.py` finds it via `KRONOS_REPO_PATH` (defaults to
`backend/vendor/kronos`; the Dockerfile clones to `/opt/kronos` and sets this env var
to match). If this env var points somewhere without a clone, Kronos forecasts fail
*safely* (returns `None`, pipeline continues without that signal, Section 50) rather
than crash -- but you'll be running without real forecasts. This was verified for
real during development: it produces genuine autoregressive forecasts, not a stub.

**Known packaging gap (V3 Phase 11):** neither command above pins a commit SHA --
both track whatever `master`'s tip is at clone time, so a clean setup done today and
one done next month can silently pull different Kronos code with no version signal
anywhere. `requirements.txt` pins every *pip* dependency with `==`; this is the one
vendored (non-pip) dependency that doesn't get the same treatment. Not fixed here
(changing the clone command is untestable in this environment -- no docker, and a
`--depth 1` shallow clone can't simply `git checkout` an arbitrary older SHA without
also changing the fetch depth, which needs a real build to verify doesn't break).
For reference, the commit actually present in this dev environment's
`backend/vendor/kronos` as of 2026-09-15 is `67b630e67f6a18c9e9be918d9b4337c960db1e9a`
(`master`, 2026-04-13, "Merge pull request #243 ... fix/batch-dimension-training") --
a real, working checkout, not a guess, but not a claim that it's the "right" version
to pin, just the one this environment happens to have.

## 9. Nifty50 universe sync

The 50-stock universe (`app/providers/nifty50_seed.py`) loads from
`data/processed/nifty50_instruments.json`, generated by:

```bash
cd backend
python scripts/sync_instruments.py
```

This cross-references NSE's official Nifty50 constituent list against Upstox's
instrument master (both fetched live) -- re-run it periodically, since NSE rebalances
Nifty50 semi-annually (Jan 31 / Jul 31 cutoffs). The JSON output is committed as a
shipped snapshot, so a fresh clone works without running this first; there's also a
small hand-typed fallback if the JSON file is ever missing.

## 10. FinRL: training and using the DRL portfolio agent

A real FinRL PPO checkpoint is shipped in `data/models/finrl_ppo_v1/` (trained once
offline, ~30k timesteps -- fast on CPU, a few minutes). It is explicitly **lightly
trained and not performance-validated** -- everywhere it surfaces (`model_version`,
`/admin/debug`'s `finrl_checkpoint_trained` field) says so. It is *not* used to drive
live recommendations; `MeanVariancePortfolioModel` (PyPortfolioOpt) is the real
default that actually produces `Recommendation`/`PortfolioResult` rows.

To retrain (e.g. with more timesteps for a more seriously trained agent):

```bash
cd backend
python scripts/train_finrl_agent.py   # edit TIMESTEPS in the script to train longer
```

To use `FinRLDRLPortfolioModel` directly (`app/models_iface/portfolio_finrl.py`), it
takes the same `PortfolioModel.optimize(candidate_returns, ...)` interface as the
mean-variance model -- it runs the trained policy's full-universe allocation and
subsets/renormalizes it down to whichever candidate symbols you pass in (must be a
subset of the training universe, recorded in the checkpoint's `metadata.json`).

## 11. Backtesting

```bash
cd backend
python scripts/run_backtest.py 5y   # or any yfinance period string, e.g. "2y", "10y"
```

Walk-forward, monthly rebalance, real 5-year Nifty50 price history, no look-ahead.
Read `app/backtesting/engine.py`'s docstring before trusting the numbers it prints --
it has two real, stated limitations: it's technical-only (no historical
point-in-time fundamentals source is wired in), and it's **survivorship-biased**
(uses today's Nifty50 membership retroactively, which Section 34 explicitly calls
out as something to avoid and this build hasn't fully corrected).

## 12. Known remaining gaps

- **Fundamentals backtesting**: not possible yet without a point-in-time historical
  fundamentals source (yfinance `.info` is snapshot-only).
- **Survivorship bias** in the backtester (see above) -- needs NSE's historical
  semi-annual constituent lists to fix properly, not just today's list.
- **Trading execution** is out of scope by design (Section 46, hard rule) -- this is
  a research/recommendation platform, not an order-placement system.
- **Admin/debug endpoint has no auth** (`/admin/debug`, `backend/app/api/admin.py`)
  -- still true after the V3 session. Fine for local single-user use; don't expose
  it on a public network as-is (see section 6 above).
- **No point-in-time historical fundamentals** -- still true (see "Fundamentals
  backtesting" above); nothing added this session changes this.
- **`/api/plans` (section 13 below) has no per-symbol/issuer-concentration check**
  -- `validate_constraints` runs at the asset-class level only; `HoldingPosition`
  has no asset-class classification yet, so nothing auto-derives per-symbol
  exposure from your actual holdings. Documented in the code, not silently
  assumed correct.
- **Research/claim-verification (section 13) is real but partial**: PDF source
  extraction is stubbed (raises a clear error, no PDF library wired in); there's
  no single end-to-end orchestration loop gluing session/checklist/branches/
  contradiction-check/synthesis/verification/publish together yet -- each stage
  is tested in isolation; `numerical_check` confirms a cited number exists in its
  source, not that a formula using it recomputes correctly.
- **Gemini adapter (section 13) is implemented but unmeasured live** -- no Gemini
  API key/project has been available in any session so far, so cost/latency and
  real-response behavior are unverified against a live endpoint.
- **PostgreSQL was unavailable in every session's dev environment**, including
  this documentation pass -- migrations and multi-worker concurrency behavior are
  verified by code review and SQLite-backed tests, not by a live `alembic upgrade
  head` run against Postgres. If you hit something different against a real
  Postgres instance, that's a real gap in this verification, not a contradiction
  to assume away.

## 13. What's new since the original build (V3 session)

A large V3 work session (Phases 00-10, tracked in
`docs/v3-execution/STATE.md` -- read that file for the full phase-by-phase
ledger, gate matrix, and every open item) added several features on top of the
MVP described above. None of it requires anything beyond `DEMO_MODE=true` +
SQLite-for-tests to exercise at the code/test level; a few pieces need real
external inputs to go from "implemented and tested" to "verified live":

- **Holdings, goals, and a financial-product catalogue** (`/holdings`, `/goals`,
  `/catalogue` in the frontend; `app/api/financial_inputs.py`,
  `app/api/catalogue.py` in the backend) -- track what you actually hold and what
  you're saving toward, against a catalogue of financial-product types. Works
  out of the box; the catalogue itself is explicitly synthetic/educational
  fixtures, not a reviewed real product list (see the gap above and each
  endpoint's own docstrings).
- **A research pipeline** (`/research`; `app/api/research.py`,
  `app/council/` research-workflow additions) -- structured deep-research
  sessions with a claim ledger, source retrieval, and verification checks
  (`fully_verifiable`, `numerical_check`). Works out of the box for retrieval
  against real RSS/web sources; PDF sources are not supported yet (stubbed,
  raises a clear error rather than silently skipping). No live key needed --
  this path doesn't require Qwen/Gemini to run, though synthesis quality
  benefits from one being configured.
- **A provider-neutral model adapter with a Gemini option**
  (`app/models_iface/model_adapter.py`) -- Qwen remains the default/verified
  baseline; Gemini (`GEMINI_API_KEY`, `GEMINI_BASE_URL`, plus
  `GEMINI_FLASH_LITE_MODEL` / `GEMINI_FLASH_MODEL`) is a selectable alternative
  behind the same interface. **Needs a real Gemini API key to do anything live**
  -- as of this writing it has never been exercised against a live endpoint in
  any session, only fixture-level. Note these `GEMINI_*` variables aren't yet in
  `.env.example`; add them to your `.env` by hand if you want to try it.
- **A planning/allocation API** (`POST /api/plans`, `GET /api/plans/scenarios` --
  `app/api/plans.py`) -- rupee-denominated allocation across educational
  scenarios with constraint validation. Works out of the box with SQLite/
  DEMO_MODE. Known narrowing: constraints are checked at the asset-class level
  only, not per-symbol/issuer (see the gap above).
- **A Kronos calibration harness** (`app/backtesting/kronos_calibration.py`) --
  builds a confidence-calibration table (direction-agreement buckets vs.
  Kronos-vs-naive-baseline hit rate) from walk-forward samples, so forecast
  confidence isn't a guess. It's a library used by the backtester, not a
  standalone script. **Needs real HF-downloaded Kronos weights and, for a
  meaningful table, real held-out price history** to produce a real table; with
  no weights available it degrades to `None`/uncalibrated rather than fabricating
  a confidence number, per this project's "never guess" rule.

Bottom line for a new user: everything above runs and is tested with zero
external accounts (SQLite tests, DEMO_MODE). Going from "tested" to "verified
against live external services" needs a Gemini key (Gemini adapter), a real
Postgres instance (concurrency gates, migrations against Postgres), and/or real
Kronos/HF weights (calibration table, live forecasts) -- none of which were
available in any V3 session, which is why those specific claims stay marked
unverified rather than "done."

## 14. Rollback

There is no feature-flag system in this codebase (despite that language
appearing in the V3 planning docs as an intended future mechanism) -- rollback
here means the two things actually possible with what's in the repo:

**Database schema.** Migrations are plain Alembic, one linear chain
(`backend/alembic/versions/`, currently `0001` through `0013`). To undo the most
recently applied migration:

```bash
cd backend
alembic downgrade -1
```

Or to a specific known-good revision:

```bash
alembic downgrade <revision_id>   # e.g. alembic downgrade 0009
```

Check `alembic history` and `alembic current` first to confirm what's actually
applied before downgrading -- don't infer the applied revision from the
filenames alone. Each migration's own `downgrade()` function is what actually
runs; if a given migration's `downgrade()` is a no-op or partial (check the file
itself), the schema downgrade may not be fully reversible -- this hasn't been
audited migration-by-migration as part of this documentation pass, and no
migration has been rehearsed downgrading against a live Postgres instance in
this environment (Postgres was unavailable, see the gap above).

**Application code.** There's no runtime toggle for the V3 features in section
13 -- rolling one back means a `git revert` of the commit(s) that introduced it,
then redeploying. Since this session's V3 work is still uncommitted at the time
of this review (see `git status`), the practical rollback for anything in
section 13 right now is simply not committing/deploying it, or `git checkout`
of the pre-V3 commit (`e0d27ea`) for the backend/frontend trees. Once V3 work is
committed, use `git revert <sha>` for the specific commit(s), not a blanket
`git reset --hard`, so history and any already-published data stay intact.

**What's out of scope for rollback.** There's no data-migration-safe way to
"disable" a new API route short of not deploying it -- routes in
`backend/app/main.py` are registered unconditionally. If you need to take a
route out of service without a full redeploy, the only option today is
commenting out its `app.include_router(...)` line and redeploying, which is a
code change, not a flag flip. This is an honest gap, not a documented feature.

**Restoring from a real Postgres dump.** If you have a `pg_dump`/`pg_dumpall`
SQL file (e.g. from a previous deployment), use
`scripts/restore_postgres_backup.sh /path/to/backup.sql` -- it brings up the
`postgres` compose service, streams the dump into it via `psql` (a bind-mount/
stream, never a Dockerfile `COPY`, so the dump is never baked into an image),
then runs `alembic upgrade head` to bring the restored schema current with
whatever's ahead of the dump's own `alembic_version`. Read the script's own
header comment before running it -- it lists the manual checks (row counts,
foreign keys, extensions) a restore rehearsal should still include by hand.

**NDA note:** never commit or push a real database dump. This project's own
dumps can contain TrueData-sourced rows (`market_candles.source = 'truedata'`)
and Postgres role password hashes -- `*.sql` and `backups/` are gitignored at
the repo root specifically for this. Keep any dump file local-only.


## Angel One (read-only) connection

1. In `.env` set `ANGEL_API_KEY` (from your SmartAPI app) and `ANGEL_FINGERPRINT_KEY`
   (`openssl rand -hex 32`, keep a backup).
2. Run migrations (`alembic upgrade head`) and start API and worker (`run.sh` does both). Local processes share the session in `~/.local/state/pie`. Current Docker Compose mounts that host directory read-only into both services at `/angel-session`; the local-only-worker limitation from the initial integration no longer applies.
3. In your own terminal: `.venv/bin/python -m app.portfolio_intelligence.sources.angel.setup connect`
   (from `backend/`; no activation required, works in bash and fish). Enter client code, PIN and the current TOTP when
   prompted. Nothing secret is printed or stored except the session tokens, which expire at
   midnight IST. `.venv/bin/python -m app.portfolio_intelligence.sources.angel.setup disconnect` clears the session; imported holdings stay.
4. Open Holdings, press "Sync now". A sync that finds unreadable rows or a >1% mismatch
   with Angel's own total is stored as *partial* and does not replace your last complete
   import.

To check the session, run `.venv/bin/python -m app.portfolio_intelligence.sources.angel.setup status` from `backend/`.

If you prefer activation, fish uses `source .venv/bin/activate.fish`; bash uses `source .venv/bin/activate`. Use the project environment for dependency installation: `uv pip install --python .venv/bin/python -r requirements.txt`. Installing into system Python does not install packages into this virtual environment.

## Running everything in Docker (private, this machine only)

`docker compose up -d --build` starts Postgres, the API (with the after-close scheduler), the worker and the frontend,
all bound to 127.0.0.1. Things to know:

- `.env` must have `POSTGRES_PASSWORD`, and `DATABASE_URL` / `SYNC_DATABASE_URL` must use the SAME password (the compose
  file builds its own URLs from `POSTGRES_PASSWORD`; the host-side tools read the two URLs). A volume created earlier keeps
  its old role password until you rotate it: `docker exec project-ex2-postgres-1 psql -U postgres -c "ALTER USER postgres PASSWORD '<new>'"`.
- The Angel session written by the host CLI (`setup connect`, see above) lives in `~/.local/state/pie`; compose mounts it
  read-only into the API and worker at `/angel-session`. Reconnect on the host each day (sessions end at midnight IST); the
  containers pick the new session up without a restart. Keep the VPN on, since the containers share the host's network route.
- The old Nifty recommendation pipeline is OFF (`LEGACY_PIPELINE_ENABLED=false`): the worker only runs portfolio jobs and
  the old dashboard's "Run Analysis" is refused with an explanation. Set it to `true` in `.env` to use the old flow.
- Watchlist: open Watchlist, press "Load it now" once to download Angel's public stock list, then add stocks. Prices
  refresh every 30s while the market is open and a session is connected.
