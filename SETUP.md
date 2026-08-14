# Setup & Usage Guide

This walks through actually running the platform and using it end to end, not just
listing commands. See `README.md` for the one-paragraph quickstart and architecture
summary; this doc is the longer version.

## 1. What you need (and what you don't)

| Thing | Required? | Notes |
|---|---|---|
| Docker + Docker Compose | Recommended | Easiest path -- runs Postgres, backend, worker, frontend together |
| Python 3.11 + local Postgres | Alternative to Docker | For `./run.sh` (no-Docker path) |
| Node.js 20+ | Yes, for the frontend | `node --version` |
| Upstox account + API app | No | Without it, the app runs in `DEMO_MODE` with clearly-flagged synthetic market data |
| Qwen API key (DashScope, OpenRouter, or self-hosted vLLM) | No | Without it, the council/planner steps are skipped and recommendations fall back to deterministic scoring only, with reduced confidence -- this is a documented degrade path (Section 50 of the build plan), not a crash |
| GPU | No | Kronos and FinBERT are sized to run on CPU |

You can get a fully working app with **zero external accounts** by leaving `.env`'s
`DEMO_MODE=true` and the Upstox/Qwen keys blank.

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

This is the actual workflow the UI walks you through -- there is no chat interface
anywhere; everything is forms and cards (by design, see build plan Section 3).

1. **Sign up** at `/signup` -- email/password/name. You're logged in immediately.
2. **Onboarding** (`/onboarding`, redirected here automatically) -- fill in the
   financial-profile form (income, capital, horizon, objective, etc.) and answer the
   3 risk-questionnaire radio-button questions (portfolio-drop reaction, priority,
   loss tolerance). Submitting computes your risk profile **deterministically** --
   no AI involved in this step -- and shows you the result (e.g. "moderate, score
   58/100").
3. **Dashboard** (`/dashboard`) -- shows NSE market status, NIFTY level, your risk
   profile, and a "Run analysis" button.
4. **Run analysis** -- this does NOT block the browser. It creates a background job
   and the dashboard polls it every few seconds until it's done (typically well
   under a minute in demo mode; longer if Qwen/Kronos/real Upstox data are wired in
   and the universe screening does real network calls). Behind the scenes this runs
   the full pipeline: screen the Nifty50 seed universe -> Kronos forecast -> news
   sentiment -> portfolio optimization -> Qwen council (if configured) ->
   deterministic scoring -> risk gate.
5. **Recommendations** (`/recommendations`) -- once the job is done, see ranked stock
   cards: 🟢 Strong Candidate / 🟢 Candidate / 🟡 Watchlist / ⚪ No Clear Opportunity.
   It is normal and expected to sometimes see "No Clear Opportunity" for everything --
   the system is built to say that rather than force a pick (Section 20, hard rule).
6. **Stock detail** (click any card) -- shows why it was selected, the risks, and an
   expandable "advanced analysis" section with the raw fundamentals/technicals/Kronos
   forecast/news sentiment behind the recommendation.
7. **Portfolio** (`/portfolio`) -- the suggested allocation across the final
   candidates from the mean-variance optimizer, with expected return/volatility/Sharpe.
8. **Settings** (`/settings`) -- view your profile; re-run onboarding to update it
   (creates a new versioned profile, doesn't overwrite history).

## 5. Wiring in real providers

### Upstox (real market data instead of demo data)

1. Register an app at https://upstox.com/developer/ -- get an API key + secret.
2. Put them in `.env` as `UPSTOX_API_KEY` / `UPSTOX_API_SECRET`, set `DEMO_MODE=false`.
3. Restart the backend.
4. Visit `http://localhost:8000/admin/upstox/login` and complete the Upstox login flow.
5. **Important**: Upstox access tokens expire daily at 3:30 AM IST with no silent
   refresh. You need to revisit that login URL each day for live data; until you do
   (or if it's expired), the app automatically and visibly falls back to demo/cached
   data rather than pretending stale data is live.

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
- whether demo mode / Upstox / Qwen are configured
- data-source sync status and Upstox token expiry
- the last 20 recommendation jobs and their status/errors

Useful first stop when something looks wrong. **Not authentication-protected in this
MVP** -- don't expose it on a public network as-is.

## 7. Running tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

63 unit/integration tests cover risk scoring, deterministic sub-scores, the final
scoring/risk-gate logic, fundamental-ratio derivation, technical indicators, backtest
metrics, the mean-variance optimizer's solver-failure fallbacks, and a mocked Upstox
HTTP integration test.

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
