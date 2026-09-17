# Phase 08 — integrated frontend journeys (fast pass)

Date: 2026-09-14. Coordinator wrote the Phase 07 orchestration glue
(`services/research_orchestrator.py`, 2 tests) directly, then dispatched 3
parallel subagents (Planning UI, Research UI, Recovery/accessibility) per
this phase's own table. All 3 completed cleanly, no rate-limit issues.
Deliberately compressed process this round per explicit user request for
speed — shorter task packets, less upfront doc re-reading (relied on
context already built over prior phases), lighter integration ceremony.

## Scope completed

- **Orchestration glue** (coordinator): `run_research_session` ties
  session → deterministic checklist → branch fetches (via Phase 06's real
  retrieval/evidence-ledger) → contradiction check → verification →
  `ready_to_publish`, with session-state-aware dispatch (stops issuing new
  branches once cancellation is observed) and clean handling of
  budget-exhaustion mid-run. Explicitly does NOT synthesize prose (no
  model call, no credentials) — stops one state short of `published`.
- **Planning UI worker**: `/holdings`, `/goals`, `/catalogue` pages
  wired to Phase 03's real API (money fields confirmed empirically —
  Decimal serializes as JSON strings, tested against a live TestClient,
  not guessed). Synthetic catalogue entries visibly badged.
- **Research UI worker**: built the missing `backend/app/api/research.py`
  router (Phase 07 had service logic but no HTTP surface) plus
  `/research` page. Verification/contradiction results are correctly shown
  as available only right after a run (not persisted, so GET-by-id returns
  them empty — surfaced honestly in the UI, not hidden).
- **Recovery/accessibility worker**: found and fixed a real bug in
  `useJobPolling.ts` (backoff failure-counter wasn't reset when the tracked
  job id changed, so a new job could inherit a stale exponential-backoff
  delay). Fixed missing loading states on `/admin` and `/settings`, an
  error-text styling inconsistency, and a missing `aria-label` on
  `RiskGauge`'s SVG. Confirmed (not just assumed) several other checks
  were already correct: `ProgressBar` already had text alternatives, no
  360px-breaking fixed widths found, existing tables already wrapped in
  `overflow-x-auto`.

## Files/contracts changed

New: `backend/app/services/research_orchestrator.py`,
`backend/app/api/research.py`, `backend/tests/test_research_orchestrator.py`,
`test_research_api.py`, `frontend/src/app/holdings/page.tsx`, `goals/page.tsx`,
`catalogue/page.tsx`, `research/page.tsx`.

Changed: `backend/app/main.py` (research router registered),
`frontend/src/lib/types.ts`, `frontend/src/components/Sidebar.tsx`,
`TopBar.tsx`, `frontend/src/lib/useJobPolling.ts`,
`frontend/src/components/ui/RiskGauge.tsx`, `frontend/src/app/admin/page.tsx`,
`frontend/src/app/settings/page.tsx`.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 342 passed (2 new: test_research_orchestrator.py)
cd frontend && node node_modules/typescript/bin/tsc --noEmit --incremental false && npm run build
# both clean, all new routes listed as static
```

## Known gap, disclosed

The `/research` page's "Run example research" button fetches 3 real public
Wikipedia URLs — a live, unmocked external network call (no credentials
involved, no private data, matches the existing pattern of real RSS
fetches elsewhere in this app). This is real, not simulated — a deliberate
demo choice by the worker, not hidden. No synthesis/publication happens
regardless of what the fetches return.

Neither the orchestration glue nor the `/research` page reaches actual
`published` state — both stop at `ready_to_publish` since no live model
adapter is wired in (no Gemini/Qwen credentials in this environment). This
matches Phase 04/07's own stated scope boundary, not a new gap.

## Phase gate verdict

**Conditional pass.** G15 (recovery: the useJobPolling bug fix is a real
recovery-correctness fix) and G16 (accessibility: confirmed/fixed) have
direct evidence. The "complete financial-input → plan → source → scenario
journey" gate is partially met: holdings/goals/catalogue and research
session pages are real and wired to real backend contracts; a live
plan/allocation view backed by Phase 05's engine is not yet built (Phase
05 was never wired into an API surface — carried forward as a known gap
since that phase's own report).

## Next ready task

Phase 09 (forecast/backtest validation) depends only on 02, already
satisfied — no blocker. Phase 10 (independent acceptance) needs 05/07/08/09
all done; 05's engine-to-API wiring remains the biggest unclosed loop
before a real Phase 10 pass would mean anything.
