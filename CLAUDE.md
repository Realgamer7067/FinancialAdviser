# Project: Indian AI Equity Research Platform (MVP)

AI-driven stock research tool for Indian retail investors, Nifty50 universe. **Not** a
trading system -- execution is deliberately out of scope (hard rule, build-plan Section 46).

## Stack
- Backend: FastAPI + SQLAlchemy async + Alembic + Postgres
- Frontend: Next.js 16 (App Router) + TypeScript + Tailwind
- Worker: plain asyncio poll loop on `recommendation_jobs` table, no Celery/Redis
- Models: Qwen (OpenAI-compatible API) for council/planner, Kronos (CPU, cloned vendor
  repo, NOT pip-installable) for price forecast, FinBERT (CPU) for news sentiment,
  PyPortfolioOpt for allocation, FinRL PPO (experimental, shipped checkpoint, not used live)

## Core flow (`backend/app/pipelines/recommendation_pipeline.py`, ~800 lines)
Screen Nifty50 seed universe -> Kronos forecast -> FinBERT news sentiment ->
fundamentals/technicals -> portfolio optimization -> Qwen council -> deterministic
scoring -> risk gate -> persisted `Recommendation` rows.

Design principle enforced throughout: **deterministic code > specialist ML > LLM
reasoning**. Screening/scoring/risk-gate = plain Python. Kronos/FinBERT/PyPortfolioOpt =
evidence producers. Qwen only synthesizes evidence handed to it, never invents a score.

## Council (`backend/app/council/orchestrator.py`)
Planner runs once per run. Then 5 analyst roles (bull, bear, fundamental, quant, risk)
run **concurrently** via `asyncio.gather` per candidate, feeding a sequential judge.
All structured-JSON, pydantic-validated, versioned. Missing role = absent from dict,
not a crash -- degrades gracefully (confidence/data_quality drop instead).

## Scoring (`backend/app/scoring/final_score.py`)
`compute_final_score`: weighted average of available sub-scores (fundamental/technical/
kronos/news/portfolio/risk). `data_quality` = fraction of sub-scores present.
`model_agreement` = majority vote across directional signals (fundamental/technical/
kronos/news). `confidence` = 0.5*agreement + 0.5*data_quality -> band high/medium/low.

## Risk gate (`backend/app/risk/gate.py`)
Hard gates force `NO_RECOMMENDATION`: low confidence band, data_quality < 0.4,
risk_fit_score below floor (floor raised dynamically if `market_regime` flagged
high-volatility). Else thresholds map score to STRONG_CANDIDATE / CANDIDATE /
WATCHLIST / NO_RECOMMENDATION. System designed to say "no opportunity" rather than
force a pick.

## Data/providers
- Market data: real Yahoo Finance, no key needed; `DEMO_MODE=true` (default) gives
  offline synthetic fallback.
- Nifty50 universe: synced from NSE constituent list + Upstox instrument master
  (`backend/scripts/sync_instruments.py`), cross-check caught 3 wrong hand-typed ISINs.
- News: real RSS (Economic Times, RBI).
- Fundamentals: Yahoo-backed, provisional.

## Backtesting (`backend/app/backtesting/engine.py`)
Walk-forward, monthly rebalance, real 5yr Nifty50 history, no look-ahead. Two honest
limitations: technical-only (no point-in-time historical fundamentals source), and
survivorship-biased (uses today's Nifty50 membership retroactively). Never quote
numbers without that caveat.

## FinRL PPO
Trained offline once (~30k timesteps, `backend/scripts/train_finrl_agent.py`),
checkpoint in `data/models/finrl_ppo_v1/`. Explicitly labeled "lightly trained, not
performance-validated" everywhere it surfaces. Not wired into live recommendations --
MVO (`app/models_iface/portfolio_mvo.py`) is the real default.

## Frontend routes
`/onboarding` (deterministic risk profile, no AI), `/dashboard` (market status +
run-analysis job trigger, polls), `/recommendations` (ranked cards w/ tier badges),
`/stocks/[symbol]` (detail + advanced analysis expand), `/portfolio` (MVO allocation +
Sharpe), `/safer-alternatives` (advisory content), `/settings`, `/admin` (debug page,
**unauthenticated** -- not for public exposure).

## Backend module map
`api/` (auth, onboarding, dashboard, recommendations, stocks, portfolio, jobs,
education, admin) - `models/` (SQLAlchemy tables) - `models_iface/` (LLM, Kronos,
FinBERT, portfolio MVO/FinRL wrappers) - `providers/` (market data, fundamentals,
news, factory) - `pipelines/` - `council/` - `scoring/` - `risk/` - `education/`
(safer-alternatives content) - `backtesting/`.

## Tests
59 tests: risk scoring, sub-scores, final scoring/risk-gate, fundamental ratios,
technical indicators, backtest metrics, MVO solver-failure fallbacks, auth,
orchestrator, pipeline smoke test. `cd backend && pytest`.

## Known gaps (stated openly in docs, not hidden)
- No point-in-time historical fundamentals -> backtest can't include fundamentals.
- Backtester survivorship bias, needs historical semi-annual Nifty50 constituent
  lists to fix.
- Trading execution intentionally excluded (hard rule).
- Admin/debug endpoint has no auth.

## Reference docs
- `README.md` -- quickstart, stack, "what's real vs. documented limitation".
- `SETUP.md` -- full setup/usage walkthrough, provider wiring, known gaps in detail.
- `/home/realgamer7067/.claude/plans/master-build-prompt-floofy-glacier.md` -- full
  architecture rationale / numbered build-plan sections referenced throughout code
  comments (e.g. "Section 20", "Section 50").
