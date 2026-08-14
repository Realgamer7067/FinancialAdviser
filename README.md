# Indian AI Equity Research Platform (MVP)

AI-powered Indian equity research for beginner investors: structured onboarding, real
(Upstox) or demo market data, deterministic fundamentals/technicals, a Kronos time-series
forecast, FinBERT news sentiment, a mean-variance portfolio optimizer, and a Qwen-based
analyst council -- all feeding a deterministic scoring/risk-gate layer that can (and does)
say "no clear opportunity" instead of forcing a recommendation.

See `/home/realgamer7067/.claude/plans/master-build-prompt-floofy-glacier.md` (or your own
copy of the build plan) for the full architecture rationale and what's deliberately deferred
(backtesting, a real FinRL DRL agent, trading execution).

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

## What's real vs. what's a documented stub

Real in this MVP: Upstox market data + OAuth flow, Yahoo-Finance-backed fundamentals for a
curated Nifty50 seed universe, RSS news ingestion (Economic Times, RBI), deterministic
technical indicators, Kronos CPU forecasting, FinBERT sentiment, PyPortfolioOpt mean-variance
allocation, and the full Qwen planner/council/judge pipeline with deterministic scoring and a
risk gate that can output `NO_RECOMMENDATION`.

Explicitly stubbed, not faked: a FinRL deep-RL portfolio agent
(`app/models_iface/portfolio_finrl_stub.py` raises `NotImplementedModel` -- the mean-variance
optimizer is the real MVP path) and backtesting/walk-forward evaluation.
