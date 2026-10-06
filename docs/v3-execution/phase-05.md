# Phase 05 — deterministic allocation and SIP scenario engine

Date: 2026-09-14. Delegated to 3 parallel subagents (Allocation worker,
Cash-flow worker, Policy/suitability worker), dispatched alongside Phase
06's 3 workers (6 total). **All 6 subagents hit the session's rate limit
mid-task and terminated with an API error (429), not a clean completion.**
This is disclosed here rather than folded into a normal "scope completed"
narrative, because it changes what evidence backs this phase's claims: two
of Phase 05's three workers (Allocation, Policy/suitability) had already
reached "all tests pass, full suite green" before dying and left complete,
tested modules on disk; the third (Cash-flow) left a complete module but
its own test file was never written before the session died. The
coordinator verified all three directly (code review + writing/running the
missing tests) rather than trusting the partial worker reports at face
value.

## Scope completed

**Allocation worker (own: new `services/allocation_engine.py`, tests) —
completed and self-verified before the rate limit hit ("All 12 pass" was
the worker's last confirmed status).**
- `ExposureBreakdown`, `ConstraintResult`, `AllocationPlan` dataclasses;
  `compute_current_exposure`, `apply_fund_look_through`,
  `target_gap_allocation`, `validate_constraints`, `rounding_and_fallback`.
- **The V3 6.6 worked fixture is exact**: existing ₹100,000 at 60/30/10,
  target 50/40/10, new ₹20,000 → contribution is exactly ₹0 / ₹18,000 /
  ₹2,000. Confirmed by direct inspection of `test_v3_6_6_worked_fixture_exact`
  in the test file and its passing assertion (`contributions["fixed_income"]
  == Decimal("18000")`), not just the worker's own claim.
- Fund look-through preserves undisclosed remainder as `unknown_remainder`
  rather than redistributing it into known asset classes (V3 6.4).
- Independent final constraint validator is a genuinely separate function
  from the allocator, per V3 6.1 step 9.
- Flagged, not resolved: fund-of-fund recursion depth limiting has no real
  data to recurse over in this task's scope; whether `AllocationPlan` needs
  to become a persisted ORM model is left as a coordinator/later-phase
  decision (not persisted in this pass — pure dataclasses only, no
  migration needed).

**Policy/suitability worker (own: new `config/allocation_policy.yaml`,
`services/capacity_policy.py`, tests) — completed and self-verified before
the rate limit hit ("All 6 pass" was the worker's last confirmed status).**
- `allocation_policy.yaml` is explicitly labelled `is_synthetic: true` with
  a rationale block stating no reviewed policy has been supplied — verified
  by reading the actual file, which opens with an unambiguous warning
  comment (quoted in this phase's integration notes) that this must never
  be presented to a user as personalized or optimal advice.
- `compute_capacity`/`resolve_scenario` deliberately do NOT accept a
  risk-tolerance parameter at all — the function signature itself proves
  the separation V3 15.1 asks for (capacity/eligibility vs. risk tolerance
  vs. goal constraints are structurally different inputs, not merged into
  one score).
- Did NOT touch `subscores.py`/`final_score.py`/`recommendation_pipeline.py`
  — the entangled V2 portfolio-weight-in-scoring path (V3 15.1's "remove the
  portfolio contribution from the new assessment policy") is identified and
  designed around, not yet wired in to replace the old path. That wiring is
  explicit follow-up work, not done here.

**Cash-flow worker (own: new `services/cash_flow_engine.py`) — module
complete on disk; test file never landed before the session died.**
- `ProjectionAssumption`/`RateBasis`/`AssumptionProvenance`/
  `ContributionTiming`, `CashFlowEvent`-driven month-by-month ledger,
  `project_fixed_contribution`, `project_with_events`,
  `back_solve_required_contribution`.
- **Coordinator wrote and ran the missing test file** (`test_cash_flow_engine.py`,
  16 tests) after reviewing the module's actual code line-by-line. Confirmed
  by direct cross-check test: the new `NOMINAL_ANNUAL_MONTHLY_COMPOUNDING`
  basis produces a final value within ₹1 of `financial_planning.py`'s
  existing, untouched `sip_future_value()` for equivalent inputs (12%/5yr/₹5,000
  monthly) — the legacy convention is genuinely preserved, not just claimed.
  `financial_planning.py` itself was read but not modified.
- All V3 7.4 required edge cases covered: zero return, severe-but->-100%
  negative return, non-finite rate rejection, target already funded,
  partial year, zero future budget, skipped contribution, withdrawal before
  maturity, beginning-vs-end-of-month (beginning strictly ≥ end for a
  positive rate), leap-year calendar stepping (Feb 29 2028), fees consuming
  residual growth, back-solve never negative.

## Files/contracts changed

New: `backend/app/services/allocation_engine.py`, `capacity_policy.py`,
`cash_flow_engine.py`, `config/allocation_policy.yaml`,
`backend/tests/test_allocation_engine.py`, `test_capacity_policy.py`,
`test_cash_flow_engine.py` (coordinator-written).

No migration — every Phase 05 output is a pure dataclass/function, no ORM
persistence in this pass.

## Tests

```sh
cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
# 295 passed, 15 warnings, ~26s (2026-09-14), run 3x consecutively, stable
```
Allocation: 12 tests including the exact V3 6.6 fixture. Capacity policy: 6
tests. Cash-flow: 16 tests (coordinator-written, see above).

## Review findings and resolution

The real finding this phase is procedural, not a code defect: **spawning 6
subagents in one batch exceeded this session's rate budget** and lost one
worker's test-writing step entirely (Cash-flow) and all three Phase 06
workers' completion (see phase-06.md). The coordinator's response was to
verify the surviving code directly rather than either (a) trusting an
unverified partial report, or (b) discarding real, working code because its
own test suite didn't finish. Both `allocation_engine.py` and
`capacity_policy.py`'s own claims ("all tests pass") were spot-checked
against the actual test file contents, not accepted blind.

## Rollback / feature-flag behavior

Not applicable — no migration, and nothing yet wires these new modules into
any live call path (they're new, additive, unused-so-far services).

## Phase gate verdict

**Conditional pass.** G03 (cash conservation), G04 (constraints), G05
(existing wealth changes the contribution split), G07 (projection semantics,
rate basis/timing/inflation reproduce numeric outputs) all have direct
passing test evidence. G06 (product truth) is partially addressed —
`capacity_policy.py` never claims optimal suitability, but the actual
wiring of "unsupported/missing terms prevent instrument-level plan" against
Phase 03's catalogue `resolve_support_level()` is not yet connected to this
phase's allocator. Not yet done, flagged rather than assumed: replacing the
old entangled scoring path in `recommendation_pipeline.py`/`subscores.py`
with the new separated `SuitabilityResult`/`AllocationPlan` design.

## Next ready task

Wiring Phase 05's engine into an actual API surface (`/api/plans` or
similar) and replacing the old portfolio-weight-in-scoring path is the
natural next integration step, but per the guide's own dependency map that
work belongs more to Phase 08 (integrated frontend journeys/API
compatibility) once Phase 06/07's research side has something to plan
against too. Immediate next-ready phase: Phase 07 (bounded research) once
Phase 06 is actually complete (see phase-06.md — it is not, this session).
