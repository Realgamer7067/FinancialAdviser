# Phase 07 — bounded research, verification and follow-ups

Date: 2026-09-14. Delegated to exactly 3 parallel subagents (Workflow
worker, Verification worker, Reuse/follow-up worker), matching this phase's
own subagent table exactly — no doubling up with another phase's workers
this time, per the rate-limit lesson recorded after Phase 05/06. **All 3
completed cleanly, no rate-limit interruption.**

## Scope completed

**Workflow worker (own: new `models/research.py`, `services/research_workflow.py`, tests).**
- `ResearchSession`/`ResearchBranch` models; the exact V3 9.2 state machine
  (`created → resolving → retrieving → calculating → synthesizing →
  verifying → ready_to_publish → published`, plus `cancelled`/`failed`),
  enforced via an atomic conditional-UPDATE transition guard (reusing
  Phase 01's `publication.py` technique) so an invalid transition (e.g.
  `created` straight to `published`) raises `InvalidStateTransition`, and
  a cancelled/published/failed session can never transition again.
- `run_standard_checklist` creates exactly 3 deterministic branches
  (financials_valuation, events_governance, peers_downside) with **no
  model call** for a standard question — matches V3 9.2's "the initial
  checklist is deterministic for standard company/fund questions" literally.
- `run_branch` actually calls Phase 06's `fetch_document`/`extract_passages`
  and Phase 06's `evidence_ledger.create_fact`/`link_fact_to_passage`,
  producing real `complete`/`partial`/`unavailable`/`failed` branch outcomes
  depending on what fraction of its fetch URLs succeed — the first genuine
  integration between the retrieval/evidence primitives and an orchestrator.
  Budget-checked per fetch via `check_budget`.
- `check_material_contradiction` detects `refutes`-linked facts.
- Two real gaps disclosed by the worker, not hidden: branch-level
  cancellation isn't wired (only session-level is), and `run_branch` doesn't
  itself check session state before running (a caller must check first) —
  recorded below, not silently assumed complete.

**Verification worker (own: new `schemas/research_assessment.py`,
`services/research_verification.py`, `council/research_prompts.py`, tests).**
- `CompanyAssessment` has exactly 13 fields, verified by the worker's own
  test asserting the field set directly against `model_fields.keys()` —
  **no `target_price` or `confidence` field exists anywhere in the
  schema**, structurally enforcing V3 9.5's "never invents an exact target
  price or calibrated confidence."
- `verify_report_claims` wraps Phase 06's `evidence_ledger.verify_fact` per
  claim and identifies `unresolved_critical_claim_ids` — the exact set a
  caller must strip or mark unknown before publishing (V3 9.4).
- `apply_sector_template("bank", ...)` removes industrial-leverage ratio
  keys (`debt_to_equity`, `interest_coverage`) — a small, explicit,
  documented rule, not a general engine, matching V3 9.5's bank-vs-
  industrial-ratio warning concretely.
- Both prompt constants (`SYNTHESIS_PROMPT_V1`, `VERIFICATION_PROMPT_V1`)
  explicitly forbid invented target prices/confidence numbers and state
  the LLM verifier's flag is advisory, never ground truth over the
  deterministic `evidence_ledger.verify_fact` result.

**Reuse/follow-up worker (own: new `models/research_report.py`,
`services/research_reuse.py`, tests).**
- `compute_artifact_key` is a deterministic sha256 over exact dependency
  identity (manifest/question-scope/prompts/models/research-policy
  versions) — reasoned explicitly against V3 13.2's cache-dependency table
  to conclude a personal profile version does NOT belong in a shared
  research artifact's key (only the "Suitability/plan" row depends on
  profile/holdings/goals; "Company report" does not) — a real, tested
  design decision, not a guess.
- `publish_report` is proven, by a real test that re-fetches the parent row
  fresh from the DB, to never mutate a parent report when a follow-up
  child is published — the exact invariant V3 9.6 requires ("producing a
  new manifest version rather than mutating the old one").
- `diff_source_ids` computes the real symmetric difference for `refresh_sources`
  revisions, tracking exactly which sources changed.

## Coordinator integration

- Confirmed `models/__init__.py` merged cleanly across all 3 workers (no
  conflicts — each added its own import/`__all__` lines).
- One combined migration `0013` for all 3 new tables, correctly ordered for
  FK dependencies (research_sessions/branches before research_reports,
  which references research_sessions via `session_id`). Verified via
  `alembic upgrade head --sql`.
- Reviewed the Workflow worker's disclosed budget-key spelling
  inconsistency (`ResearchSession.budget_envelope`'s documented example
  uses `max_`-prefixed keys, `check_budget`'s own docstring used bare
  names) — the worker's own `_resolve_budget_key` already resolves this
  defensively (accepts either spelling, prefers `max_`-prefixed) with a
  passing test; judged sufficient, no further coordinator fix needed.

## Files/contracts changed

New: `backend/app/models/research.py`, `research_report.py`,
`backend/app/services/research_workflow.py`, `research_verification.py`,
`research_reuse.py`, `backend/app/schemas/research_assessment.py`,
`backend/app/council/research_prompts.py`,
`backend/alembic/versions/0013_phase07_research_workflow.py`,
`backend/tests/test_research_workflow.py`, `test_research_reuse.py`,
`test_research_verification.py`, `test_research_assessment_schema.py`.

Changed: `backend/app/models/__init__.py`.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 338 passed, 15 warnings, ~26s (2026-09-14), run 3x consecutively, stable
```
14 (workflow) + 13 (reuse) + 11 (verification/schema, combined) = 38 new
tests over the 295 baseline (some ordering variance in the workers' own
reported deltas due to concurrent landing, resolved by the coordinator's
final stable count above).

## Review findings and resolution

No cross-worker file conflicts. Real gaps disclosed by workers and
preserved here rather than hidden: (1) branch-level cancellation not wired
(only session-level cancellation exists); (2) `run_branch` doesn't check
session state before executing — an orchestration loop calling it must
check state first, itself not yet built; (3) a `failed`-path exception
handler's own `db.flush()` could itself raise if the original failure was
DB-related, leaving that branch row unpersisted — a known, narrow edge case,
not fixed in this pass; (4) `CompanyAssessment`/`SuitabilityNote` remain
Pydantic-only (not persisted) — `ResearchReport.content` stores them as an
opaque JSON dict for now.

## Rollback / feature-flag behavior

Migration `0013` has a tested-offline `downgrade()`. Nothing yet routes a
real request through this workflow — no API endpoint calls
`create_session`/`run_branch`/`publish_report` yet, so this is fully
additive with zero effect on any live path.

## Phase gate verdict

**Conditional pass.** The structural state-machine correctness (invalid
transitions rejected, terminal states enforced), the deterministic-
checklist requirement, real branch outcomes derived from actual Phase 06
fetch/evidence calls, the assessment schema's structural absence of
invented numbers, and the artifact-key/no-parent-mutation reuse guarantees
all have direct passing test evidence. G10 (research support: ≥95%
supported material citations on held-out review) remains explicitly out of
reach at the unit-test level — that requires an actual corpus of held-out
questions and human/blind review, which is Phase 10's job, not claimable
here. No orchestration loop yet ties `create_session` →
`run_standard_checklist` → `run_branch` (× branches, respecting session
state/cancellation) → `check_material_contradiction` → synthesis →
`verify_report_claims` → `publish_report` into one real end-to-end call —
each piece is tested in isolation, the glue is the next integration step.

## Next ready task

Phase 08 (integrated frontend journeys) depends on 03/05 (planning track,
satisfied) and 06/07 (research track, now satisfied at the unit level).
Before Phase 08's UI work has something real to call, the coordinator
should write the actual end-to-end orchestration loop gluing this phase's
pieces together (the gap named above) — that is real, un-delegated
integration work, not a new subagent task, since it requires judgment
about exactly how session-state checks, branch dispatch, and the
verification/reuse steps compose.
