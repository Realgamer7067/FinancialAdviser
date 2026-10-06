# Phase 04 — faster model execution and five-project scheduling

Date: 2026-09-14. Delegated to 3 parallel subagents (Adapter worker,
Scheduler worker, Benchmark worker) per the guide's own subagent assignment
table, dispatched alongside Phase 03's 2 workers (5 total). Coordinator did
live research first (WebFetch against current Google docs) to freeze model
IDs/pricing before writing task packets, matching Phase 02's pattern of
freezing contracts before delegation.

## Coordinator pre-work: live doc verification

Fetched `https://ai.google.dev/gemini-api/docs/models` and
`https://ai.google.dev/gemini-api/docs/pricing` directly (2026-09-14).
Confirmed the V3 plan's proposed defaults are accurate, current, real model
IDs — no correction needed:
- `gemini-3.5-flash-lite`: real, current, "fastest, most cost-effective 3.5
  model." Pricing confirmed: $0.30/$2.50 per 1M input/output tokens.
- `gemini-3.8-flash`: real, current, "most intelligent Flash model."
  Pricing confirmed: $0.75/$3.75 through 2026-12-31, then $1.50/$7.50.

No `pip` binary exists in this venv (`.venv/bin/python -m pip` → "No module
named pip") — the Gemini adapter was built against the REST API directly via
`httpx` (already a pinned dependency) rather than the `google-genai` SDK,
avoiding a dependency this environment cannot install anyway.

## Scope completed

**Adapter worker (own: new `models_iface/model_adapter.py`, `core/config.py`
additions, new tests; did not touch `orchestrator.py`/`llm.py`).**
- Provider-neutral `ModelRequest`/`ModelResponse`/`ModelAdapter` contract
  per V3 11.3 (task kind, schema version, model ID, thinking config, output
  limit, deadline, request ID, evidence refs; response carries parsed
  output, provider/model IDs, usage, finish reason, grounding refs, retry
  class, latency).
- `GeminiAdapter` — real `httpx` REST implementation against
  `generateContent`, structured output via `responseSchema`, one
  schema-repair retry on invalid JSON before giving up, HTTP-status failure
  mapping per V3 12.3's table (429→retryable, 401/403→permanent,
  timeout/5xx→retryable).
- `QwenAdapter` — thin translation wrapper keeping the existing
  `QwenOpenAICompatibleProvider` fully intact and usable through the new
  interface, per V3 11.3's "preserve Qwen's adapter as a selectable
  baseline."
- 13 tests, all `respx`-mocked HTTP, zero live network.
- **Real, unresolved flag from the worker, not silently picked one way**:
  two other fetched Google doc pages described a different, newer
  "Interactions API" (`/v1beta/interactions`) rather than the classic
  `generateContent` endpoint the adapter was built against. The worker
  built against `generateContent` (matching the task's frozen instructions
  and the primary API-reference fetch) but flagged the conflict explicitly.
  **Coordinator note**: this must be re-verified against live docs before
  any real `GEMINI_API_KEY` is wired up — recorded in STATE.md as an
  unresolved item, not resolved in this pass (no credentials exist to test
  either endpoint live anyway).

**Scheduler worker (own: new `models/scheduler.py`, `services/model_scheduler.py`,
new tests).**
- `ModelProject` (quota identity — alias, real Cloud project ID, owner,
  environment, supported models, daily spend cap, `credential_ref` as a
  secret NAME only, health flag) and `ModelCallReservation` (append-only
  reservation lifecycle: `reserved -> committed/released/expired/
  unknown_billing`).
- Reused the exact atomic-conditional-write technique `publication.py`
  established in Phase 01 (single `UPDATE ... WHERE <ownership predicate>`,
  never read-then-write) for `commit`/`release`/`mark_unknown_billing`/
  `expire_stale_reservations`. Task-attempt deduplication is a real atomic
  guarantee via a DB unique constraint (`task_attempt_id`) plus
  SAVEPOINT+`IntegrityError` handling, not a pre-check SELECT.
- `mark_unknown_billing()` is a status distinct from both `committed` and
  `released` — required by V3 12.3's "never automatically refund a possibly
  billed request to zero"; the daily-spend-cap check counts it, so a
  timed-out-but-possibly-billed call isn't invisible to budget enforcement.
- **Explicitly flagged, not a false guarantee**: the daily-spend-cap
  enforcement itself (sum-then-insert) is check-then-insert, not atomic —
  two concurrent `reserve()` calls could both pass the check and jointly
  exceed the cap. A hard guarantee needs a DB aggregate constraint/trigger
  or `SELECT ... FOR UPDATE` on a running total, neither provable here
  without real PostgreSQL. Recorded as a known soft-cap limitation, not
  fixed in this pass (fixing it blind without PostgreSQL to prove the fix
  against would be worse than stating the gap honestly).
- 14 tests.

**Benchmark worker (own: new `services/call_budget.py`,
`services/failure_simulation.py`, new tests; read-only on `orchestrator.py`).**
- Verified the CURRENT orchestrator's real call count against its actual
  code (not assumed): 5 analyst roles + 1 judge = 6 calls/candidate, 1
  planner per run → 19 calls for a 3-candidate run before retries. **Matches
  the V3 plan's stated number exactly** — no discrepancy found.
- `call_budget.py`: pure, deterministic call-count estimator for the legacy
  council vs. the target extraction→synthesis→verification shape. Verified
  arithmetic matches V3 11.2's own stated figures ("five calls when all
  extraction batches miss cache," "cached extraction can reduce this to
  synthesis plus verification").
- `failure_simulation.py`: pure dispatch/outage simulator (no I/O, no
  randomness) for the "all projects unavailable" required case.
- 32 tests.

**Coordinator integration (this pass).**
- One combined migration `0011` (shared with Phase 03) for `model_projects`/
  `model_call_reservations` alongside Phase 03's 6 tables.
- Confirmed no shared-file conflicts across all 5 Phase 03/04 workers'
  concurrent edits to `models/__init__.py`.

## Files/contracts changed

New: `backend/app/models_iface/model_adapter.py`, `backend/app/models/scheduler.py`,
`backend/app/services/model_scheduler.py`, `backend/app/services/call_budget.py`,
`backend/app/services/failure_simulation.py`,
`backend/alembic/versions/0011_...` (shared with Phase 03),
`backend/tests/test_gemini_adapter.py`, `test_model_scheduler.py`,
`test_call_budget.py`, `test_failure_simulation.py`.

Changed: `backend/app/core/config.py` (additive: `gemini_base_url`,
`gemini_api_key`, `gemini_flash_lite_model`, `gemini_flash_model`,
`gemini_configured`), `backend/app/models/__init__.py`.

`backend/app/council/orchestrator.py` and `backend/app/models_iface/llm.py`
were read but NOT modified — the existing council keeps working exactly as
before; this phase built the adapter/scheduler primitives for a later phase
(07, research workflow) to actually route through.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 227 passed, 15 warnings, ~23s (2026-09-14), run 3x consecutively, stable
```
No live Gemini/GCP calls anywhere — no credentials exist in this
environment. Every adapter/scheduler test runs against mocked HTTP or pure
in-memory logic, per V3 12's explicit "Live smoke tests are separately
opt-in and use public/synthetic evidence only" and the external-input
handling table's "Continue with: Adapters, mocks, shared-scheduler
simulations... Do not claim: Live model availability, live cost or
five-project throughput."

## Review findings and resolution

Two real items flagged by workers, both recorded rather than silently
resolved or hidden: the `generateContent` vs. Interactions API endpoint
conflict (adapter worker), and the soft daily-spend-cap race (scheduler
worker). Neither was fixed in this pass — the first needs a live credential
to verify against reality, the second needs PostgreSQL to prove a real fix
correct; both are recorded in STATE.md as unresolved rather than papered
over with an unverified guess.

## Rollback / feature-flag behavior

Migration `0011` has a tested-offline `downgrade()` (see phase-03.md).
Application code (`model_adapter.py`, `model_scheduler.py`) is entirely
additive and unused by any existing call path — reverting it has zero
effect on current behavior, since nothing routes through it yet.

## Phase gate verdict

**Conditional pass.** G12/G13's fixture/scheduler-level requirements are
implemented and tested: typed adapter contract with real failure-mode
mapping, atomic reservation/accounting primitives, verified call-count
claims. Explicitly NOT claimed: live model availability, live cost, or
five-project real throughput — no credentials exist, and the plan doc
itself states a missing key "permits fixture readiness, not a fabricated
live benchmark pass." One working project's worth of live measurement
remains a future step once credentials are supplied.

## Next ready task

Phase 06 (evidence acquisition) depends on Phase 02 (satisfied) plus "the
adapter from 04 for model-assisted extraction" (now satisfied at the
fixture level). Phase 07 (bounded research) depends on 01/04/06. Both are
reasonable next targets once Phase 06 exists; Phase 05 (allocation/SIP,
using Phase 03's now-available typed inputs) is also ready and arguably
higher-value next given it needs no external credentials at all.
