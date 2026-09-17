# Architecture map

A reader's map of the current module layout, post-V3. For *why* each piece
exists and how it was built/verified, see `docs/v3-execution/` (a
phase-by-phase execution ledger, STATE.md + CONTRACTS.md + one report per
phase) -- this file is the short version a new contributor reads first,
not a replacement for that longer record.

## Backend (`backend/app/`)

| Directory | What's in it |
|---|---|
| `api/` | FastAPI routers -- one file per resource (onboarding, dashboard, recommendations, stocks, portfolio, plans, jobs, holdings/goals/commitments, catalogue, research, education, admin) |
| `models/` | SQLAlchemy tables |
| `models_iface/` | LLM/Kronos/FinBERT/portfolio-optimizer wrapper interfaces |
| `providers/` | Market data, fundamentals, news -- real (Yahoo/RSS) and demo implementations behind the same interface |
| `pipelines/` | `recommendation_pipeline.py` (screen -> Kronos -> news -> fundamentals/technicals -> portfolio -> council -> score -> risk gate), plus job progress tracking and atomic publication fencing |
| `council/` | Qwen/Gemini analyst-role orchestration and prompts |
| `scoring/` | Deterministic sub-score and final-score computation |
| `risk/` | Risk gate (hard/soft thresholds -> recommendation tier) |
| `backtesting/` | Walk-forward technical+portfolio backtest, and a separate Kronos-specific calibration harness |
| `services/` | Everything that doesn't fit the above: allocation/cash-flow/capacity engines, evidence ledger + retrieval (research pipeline's claim verification), research workflow/orchestrator, model quota scheduler, catalogue, manifest recording, web search |
| `education/` | Safer-alternatives advisory content (qualitative, no fake precise numbers) |

## Frontend (`frontend/src/`)

Next.js App Router, one directory per route under `app/`. `lib/` holds the
typed API client, shared hooks (`useApiData`, `useJobPolling`), and pure
client-side computation (`indicators.ts` for chart overlays). `components/`
is split into route-agnostic `ui/` primitives and `charts/`.

## Two things that look like duplication and aren't (yet) resolved

Found during a pre-commit cleanup pass (2026-09-17), documented rather than
silently merged or silently left unexplained:

1. **Two planning surfaces.** `api/planning.py` (+ `services/
   financial_planning.py`) is the original stateless SIP-growth/goal
   -back-calculation calculator, live behind the frontend's `/planning`
   page. `api/plans.py` (+ `services/allocation_engine.py`/
   `cash_flow_engine.py`, built in V3 Phase 05) is a richer, holdings
   -aware target-gap allocation planner -- and has **no frontend page at
   all** yet. They're not really duplicates: one is a universal calculator
   that needs no holdings data, the other is the more advanced planner
   V3 was built toward. Left as two separate, real things rather than
   forced together; `/api/plans` needs a UI before it's reachable by a
   user at all.
2. **Two portfolio-optimization call sites.** The recommendation
   pipeline's own per-stock `portfolio_score` still calls
   `models_iface/portfolio_mvo.py::MeanVariancePortfolioModel` directly
   (the original path). `services/allocation_engine.py` is a separate,
   newer implementation of essentially the same mean-variance idea, used
   only by the standalone `/api/plans` endpoint above. `docs/v3-execution/
   STATE.md` flagged this exact gap during Phase 05 ("not yet wired to
   replace the old entangled scoring path") -- confirmed still true, not
   quietly resolved along the way. Unifying them is a real, deliberate
   choice for later (which one becomes the one true implementation), not
   something to collapse without deciding that first.
