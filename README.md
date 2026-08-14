# Indian AI Equity Research Platform (MVP)

AI-powered Indian equity research for beginner investors: structured onboarding, real
(Upstox) or demo market data, deterministic fundamentals/technicals, a Kronos time-series
forecast, FinBERT news sentiment, a mean-variance portfolio optimizer, and a Qwen-based
analyst council -- all feeding a deterministic scoring/risk-gate layer that can (and does)
say "no clear opportunity" instead of forcing a recommendation.

See `/home/realgamer7067/.claude/plans/master-build-prompt-floofy-glacier.md` (or your own
copy of the build plan) for the full architecture rationale. Trading execution is the one
thing still deliberately out of scope (Section 46, hard rule) -- Kronos, FinRL, and
backtesting are all real and verified now, see "What's real" below for each one's caveats.

## Stack

- **Backend**: FastAPI + SQLAlchemy (async) + Alembic + Postgres
- **Frontend**: Next.js 16 (App Router) + TypeScript + Tailwind
- **Models**: Qwen (via any OpenAI-compatible API) for planning/council; Kronos (CPU) for
  price forecasting; FinBERT (CPU) for news sentiment; PyPortfolioOpt for portfolio allocation
- **Worker**: plain asyncio poll loop against a `recommendation_jobs` table (no Celery/Redis)

## Quick start (Docker)

```bash
cp .env.example .env
# fill in UPSTOX_API_KEY/SECRET and QWEN_API_KEY if you have them --
# the app runs fine without them in DEMO_MODE=true (the default)
docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000
- Admin/debug: http://localhost:8000/admin/debug

## Quick start (local, no Docker)

```bash
./run.sh          # backend: venv + deps + alembic migrate + worker + API
cd frontend && npm install && npm run dev   # frontend, separate terminal
```

Requires a Postgres instance reachable at `DATABASE_URL` (see `.env.example`).

## Upstox auth

Upstox access tokens expire daily at 3:30 AM IST -- there is no silent refresh. Visit
`/admin/upstox/login` each day (in a real deployment) to re-authenticate; until then, or
whenever `DEMO_MODE=true` / no Upstox keys are set, the app transparently falls back to a
clearly-flagged demo/cached market data provider.

## Running tests

```bash
cd backend
pip install -r requirements.txt
pytest
```

## What's real vs. what's a documented limitation

Everything below has actually been run end-to-end against real data during development, not
just written and assumed to work -- see `SETUP.md` for how to reproduce each verification.

- **Market data**: real Upstox market data + OAuth flow, with a clearly-flagged demo/cached
  fallback. **Nifty50 universe** is synced from two live official sources (NSE's own
  constituent list + Upstox's instrument master) via `scripts/sync_instruments.py` -- all 50
  constituents, not a hand-typed subset (three of the original hand-typed ISINs were caught
  wrong by this cross-check, which is exactly why it isn't hand-maintained anymore).
- **Fundamentals**: Yahoo-Finance-backed, real (if provisional -- see SETUP.md).
- **News**: real RSS ingestion (Economic Times, RBI).
- **Technicals**: deterministic indicators, real.
- **Kronos**: real. The GitHub repo has no setup.py/pyproject.toml -- it is *not*
  pip-installable (an earlier requirements.txt pin claiming otherwise did nothing). It's
  cloned separately (Dockerfile / `run.sh`) and put on `PYTHONPATH`. Verified with a real
  autoregressive forecast against real candle data.
- **FinBERT**: real sentiment inference.
- **Portfolio allocation**: PyPortfolioOpt mean-variance is the real, working default. A
  **FinRL PPO agent** is also real now (not a stub) -- trained offline once
  (`scripts/train_finrl_agent.py`), checkpoint shipped in `data/models/finrl_ppo_v1/`, pure
  inference at runtime. It is explicitly labeled everywhere it surfaces (`model_version`,
  `/admin/debug`) as **lightly trained, not performance-validated** -- it is not used to drive
  live `Recommendation`/`PortfolioResult` rows, only available for direct/experimental use.
- **Backtesting** (Sections 34-36): real, `scripts/run_backtest.py`, walk-forward with no
  look-ahead, real Sharpe/Sortino/max-drawdown/hit-rate against real 5-year Nifty50 price
  history. Two honestly-stated limitations, not hidden: it's technical-only (fundamentals have
  no historical point-in-time source wired in yet), and it's **survivorship-biased** --
  the tradeable universe is *today's* Nifty50 applied retroactively, which is a real, known
  bias per Section 34's own "avoid survivorship bias" instruction, not yet corrected. Never
  quote its numbers without that caveat.
- **Council/scoring/risk-gate**: the full Qwen planner/council/judge pipeline, deterministic
  scoring outside the LLM, and a risk gate that can output `NO_RECOMMENDATION`, are real.
