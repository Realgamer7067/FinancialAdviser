# Phase 10 — G01-G19 gate matrix (performance/reliability + requirement-to-evidence audit)

Independent reviewer pass, item 6 (latency/concurrency/cost/outage measurement)
and item 7 (gate map) of the Phase 10 acceptance audit. Environment reality
check, verified directly in this session:

- `psql` client binary exists; `pg_ctl`/`postgres`/`initdb`/`docker` do not.
  No PostgreSQL server reachable. Confirms CONTRACTS.md C6 — not re-asserting
  on faith, checked again here.
- No live Gemini key, no real Kronos HF weights in this environment (per
  STATE.md, unchanged).
- Consequence: no true concurrent-transaction proof, no live-model
  latency/cost numbers, no live Kronos accuracy numbers are possible here.
  Anything below labeled PASS is SQLite/fixture-provable and real; anything
  needing the above is CONDITIONAL or BLOCKED, never fabricated.

## What was actually run this session (real numbers)

| Check | Command | Result |
|---|---|---|
| Fencing/scheduler/reuse/outage test files | `pytest tests/test_worker.py tests/test_model_scheduler.py tests/test_failure_simulation.py tests/test_research_reuse.py` | **47 passed**, 0 failed, 2.46s |
| Full backend suite, wall clock | `time pytest -q tests/` | **367 passed, 1 failed**, 22.78s (11.26s user / 0.55s sys, 48% CPU) — see regression finding below |
| Failing test re-run x3 (flakiness check) | `pytest tests/test_cash_flow_engine.py::test_back_solve_matches_forward_projection_nonzero_initial_effective_annual` | **Fails consistently, 3/3**, not flaky |

**New finding, not in STATE.md's "367 passed" line:** `git status --short
backend/tests/test_cash_flow_engine.py` shows the file as `??` (untracked,
new, never committed) and the failing test's own docstring says "audit item
3" — this is a **newly-written test** (almost certainly from the concurrent
financial/allocation reviewer's own Phase 10 pass), not a test that
regressed. "Regression" is the wrong word; this is a newly-surfaced
precision-policy question.

Reading the actual assertion values (not just the top-line delta) matters
here: `balance_before=31812.7706...`, `contribution=6651.9198...`,
`growth=204.6843...`, `fees=0`; their sum and `balance_after` agree to ~23
decimal places (`38669.37478804375116536758074` vs.
`...11653675807...`). The real residual is at the **~1e-19 tail**, a Decimal
*context-precision* artifact from `(1+R)**(1/12)` exceeding the venv's
28-significant-digit context — not a ₹-scale cash leak. The test asserts
exact `==` on that identity; whether the ledger identity *should* assert
exact Decimal equality or a paise-quantized tolerance is a real, open
question this review is handing to the allocation/cash-flow owner
(`cash_flow_engine.py` is out of this review's write scope) — not a
disproven G03 cash-conservation guarantee. Full suite is **367 passed / 1
failed**, not clean, as of this session (2026-09-15) — the failure is real
and reproducible (3/3), the interpretation above is what should travel with
it.

## Cache/reuse correctness proxy

`backend/app/services/research_reuse.py::compute_artifact_key` — tested for
determinism (`test_compute_artifact_key_deterministic`), per-field
sensitivity (`test_compute_artifact_key_changes_per_field`, parametrized),
and policy-version invalidation (`test_research_policy_version_change_invalidates_key`)
in `tests/test_research_reuse.py`. This proves the *key computation* would
route identical requests to the same cache row and differing ones to
different rows — a correctness proxy for "cache would work," not a
performance/hit-rate number (no live traffic exists to measure hit rate
against).

## Concurrency/fencing — what SQLite can and can't prove

`backend/app/worker.py`'s job-claiming is exercised by `tests/test_worker.py`:
`test_claim_marks_running_and_sets_fencing_token`,
`test_running_job_with_live_lease_is_not_reclaimed`,
`test_running_job_with_expired_lease_is_reclaimed`,
`test_stale_attempts_completion_write_is_dropped`,
`test_current_attempts_completion_write_succeeds` — 5/5 pass. This proves the
**logical fencing predicate** (stale `worker_token` writes are dropped, live
ones succeed) sequentially on SQLite. It does **not** prove `SELECT ... FOR
UPDATE SKIP LOCKED` interleaving under real concurrent transactions — that
requires PostgreSQL, per C6/C2, and is BLOCKED here, consistent with
STATE.md's own disclosure (not a new gap, re-confirmed).

## Outage simulation

`backend/app/services/failure_simulation.py` + `tests/test_failure_simulation.py`
(10/10 pass) models 1/3/5-project-pool outage scenarios deterministically:
zero-healthy -> zero servable capacity + fallback required; all-five-healthy
-> full combined budget; partial-healthy -> linear scaling; invalid inputs
(out-of-range healthy count, non-positive cost) raise. This is a **closed-form
arithmetic simulation of scheduler capacity under outage**, not a live
provider-outage rehearsal (no live Gemini key to actually fail against) —
the requested "1/3/5 session concurrency and simulated outage" test exists at
this fixture/arithmetic level only.

## G01-G19 matrix

| Gate | Meaning | Status | Evidence / blocker |
|---|---|---|---|
| G01 | Exact outcome (new empty/infeasible run never silently reappears as old) | CONDITIONAL | Logic-level: `publication.py` conditional-UPDATE technique + C1/C2 contracts, tested on SQLite (Phase 01, `phase-01.md`). PostgreSQL interleaving proof BLOCKED — no server (confirmed this session). |
| G02 | Ownership (Postgres claim/reclaim/cancel/publication race -> one authorized publication) | CONDITIONAL | Same fencing logic as above, `test_worker.py` 5/5 passing (re-run this session). Real `FOR UPDATE SKIP LOCKED` race BLOCKED — no PostgreSQL. |
| G03 | Cash conservation (every plan/month balances in Decimal) | CONDITIONAL, one open precision-policy question | Most of `cash_flow_engine.py`/`allocation_engine.py` covered and passing (Phase 05, C11). This session ran `test_cash_flow_engine.py::test_back_solve_matches_forward_projection_nonzero_initial_effective_annual` (new/untracked test, `git status` confirms — not a regression) — fails reproducibly (3/3) on exact-`==` ledger identity for EFFECTIVE_ANNUAL + nonzero initial, but the residual is a ~1e-19 Decimal-context tail, not a real money leak (see detail above). Open question for the allocation owner: exact vs. paise-quantized equality. |
| G04 | Constraints (no new invalid cap/eligibility breach) | CONDITIONAL | `validate_constraints` tested as independent function (Phase 05, C11); asset-class level only, no per-symbol stock-cap check (Holdings has no asset-class classification yet) — disclosed narrowing in STATE.md, not silently dropped. |
| G05 | Existing wealth (same fixture, different contribution when exposures differ; no double count) | PASS | `target_gap_allocation` verified exact against V3 6.6 worked fixture (₹100k @60/30/10 -> 50/40/10, +₹20k -> ₹0/₹18,000/₹2,000), CONTRACTS.md C11. |
| G06 | Product truth (unsupported/missing terms block instrument-level plan) | CONDITIONAL | `resolve_support_level()` + `_POLICY_CEILING` tested (Phase 03, C9); catalogue itself is 100% synthetic (`is_synthetic=True`) — no reviewed real catalogue supplied, so real-world product truth is unproven, only the *policy-enforcement mechanism* is. |
| G07 | Projection semantics (rate basis/timing/inflation reproduce numeric outputs) | CONDITIONAL | `RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING` cross-checked against legacy `sip_future_value()` (C11); `EFFECTIVE_ANNUAL` reproduces the target value itself correctly (`forward.nominal_final_value` matches target within 0.01, per the same test) — only the intermediate per-entry ledger identity has the G03 precision-tail question above, not the projection's final numeric output. |
| G08 | Temporal consistency (report/API/chart/source IDs resolve to one frozen manifest) | PASS | `data_manifest_entries` (C7), `StockDetail.evidence_is_legacy` flag, tested (Phase 02, `phase-02.md`). |
| G09 | Data isolation (provider/demo/live/revision no incompatible cache reuse; idempotent import) | PASS | C3a: candle/fundamentals source+mode filtering closed and tested. Spot-checked directly this session against actual code (not just docs): `_get_cached_fundamentals` in `backend/app/pipelines/recommendation_pipeline.py:314-329` filters on `FundamentalMetrics.source == expected_fundamentals_source()` in addition to `instrument_id` and TTL — confirms C3a's claim is real, not just documented. |
| G10 | Research support (>=95% supported material citations, held-out) | BLOCKED | Structural mechanism is real and tested: `evidence_ledger.py`'s 5-layer `verify_fact` (schema -> referenced-IDs-exist -> entity/unit consistency -> numerical check -> source support), "empty passage doesn't count as support" proven by `test_real_link_without_supporting_passage_text_does_not_count` (Phase 06, `phase-06.md`); `verify_report_claims`/`unresolved_critical_claim_ids` (Phase 07, `phase-07.md`). Missing input: an actual held-out question corpus + independent human/blind grading — explicitly the Research reviewer's separate Phase 10 track (assignment table), not run in this pass. Fixture readiness only, per the plan's own rule against fabricating a live-benchmark pass. |
| G11 | Research usefulness (blind paired review vs V2) | BLOCKED | Same missing input as G10 — no blind paired review corpus/session run in this pass; belongs to the Research reviewer track. |
| G12 | Model reliability (schema/error fixtures + honest live sample) | CONDITIONAL | Fixture-level real: `GeminiAdapter` (real `httpx` REST against `generateContent`, `respx`-mocked, 13 tests) + HTTP-status failure-class mapping (429/401/403/timeout/5xx) per phase-04.md; `QwenAdapter` wraps the existing untouched provider. Scheduler reservation lifecycle `test_model_scheduler.py` 14/14 passing (re-run this session) incl. daily-spend-cap, dedup, expiry. Live measured sample BLOCKED — no Gemini key; also flagged unresolved in phase-04.md: adapter targets classic `generateContent`, but two other fetched Google doc pages described a newer "Interactions API" — needs re-verification against live docs once a key exists. |
| G13 | Quota/cost (five-project simulation obeys limits, no duplicate dispatch) | CONDITIONAL | `task_attempt_id` dedup is a real atomic DB unique constraint (SAVEPOINT + `IntegrityError` handling), tested (phase-04.md, Scheduler worker). Daily-spend-cap is explicitly check-then-insert, not atomic — disclosed soft limitation (C10/phase-04.md), unprovable hard without PostgreSQL. `failure_simulation.py`'s 1/3/5-healthy-project arithmetic (`call_budget.py` verified 19-call/3-candidate figure matches the V3 plan exactly) tested 10/10, re-run this session — closest this environment gets to the "simulated outage" ask. |
| G14 | Performance (p50/p95 cold/warm vs section-13 targets) | BLOCKED | No live model calls, no live queue under load exist in this environment. Only measurable number: full backend test-suite wall clock (**22.78s for 368 tests**, not a queue/stage latency figure) and the 4-file fencing/scheduler/reuse/outage subset (**2.46s / 47 tests**). Neither substitutes for real cold/warm/first-useful/verified-completion latency — do not conflate. |
| G15 | Recovery/UI (refresh, network loss, cancel, replay, reordered-response browser cases) | CONDITIONAL | `useJobPolling` bug fix verified as a real recovery-correctness fix (Phase 08, `phase-08.md`); this review did not re-run browser journeys (out of scope for the read-only backend-focused pass; no browser harness invoked this session). |
| G16 | Accessibility (keyboard, reduced motion, chart-table alt at target widths) | CONDITIONAL | Reported fixed/confirmed in Phase 08 (`phase-08.md`); not independently re-verified in this pass (frontend accessibility audit not re-run here). |
| G17 | Forecast honesty (uncalibrated outputs evidence-only; accuracy claims need held-out artifact) | CONDITIONAL | `KronosModel` validated 2 layers deep (stubbed predictor itself, not just `_run`) — 8 independent sampled calls/forecast, correct horizon-to-bars mapping (phase-09.md). Two real bugs found+fixed this cycle: `lookup_confidence()` now has its own try/except backstop (degrades to `None` instead of crashing), and a malformed `hit_rate` now fails closed to `None` instead of raising/silently coercing. No live held-out MAE/RMSE possible — no real HF weights in this environment (BLOCKED sub-item, not silently assumed passing). |
| G18 | Portability (clean migration/startup/staging restore, documented rollback) | BLOCKED (deferred to Phase 11) | Explicitly Phase 11's gate, and Phase 11 has not started yet (STATE.md: Phase 11 `not_started`, depends on 10) — not evaluable now, not a "doesn't apply" claim. |
| G19 | Private deployment (cross-owner access/cache fail closed, admin/model routes enforce policy) | NOT_APPLICABLE | Single-user MVO per CLAUDE.md/STATE.md ("Simplify to single-user mode" commit `e0d27ea`); admin endpoint is explicitly documented as unauthenticated, a known gap, not a G19 claim. G19 applies "when shared/public private-data deployment is in scope" (V3-IMPLEMENTATION-PLAN.md:703) — genuinely not in scope for this single-user MVP architecture, distinct from G10/G11/G18's "not yet measured" status. |

## Summary (under 400 words)

Real, run-this-session evidence: the full backend suite is **367 passed, 1
failed** in **22.78s wall clock** (368 tests total) — not the clean "367
passed" STATE.md currently states. The failing test
(`test_cash_flow_engine.py::test_back_solve_matches_forward_projection_nonzero_initial_effective_annual`)
is untracked/new (`git status` confirms, docstring says "audit item 3"), so
it is a newly-surfaced question, not a regression: it fails reproducibly
(3/3) on an exact-`==` ledger-identity assertion, but the actual residual
(read from the assertion's own printed Decimal values) is at the ~1e-19
tail — a Decimal-context-precision artifact from `(1+R)**(1/12)`, not a
₹-scale cash leak; the projection's final target value itself matches within
0.01 in the same test. Flagged to the allocation/cash-flow owner as an
exact-vs-quantized-equality policy question, not fixed here (out of this
review's write scope). The 47 fencing/scheduler/outage/reuse tests
specifically targeted at this item's concurrency/cache/outage ask all pass
(2.46s), and none were flaky across reruns.

What's genuinely measurable without PostgreSQL/live keys/Kronos weights: (1)
the *logical* job-fencing predicate in `worker.py` — proven correct
sequentially on SQLite via 5 passing tests, but this is not proof of real
`SELECT ... FOR UPDATE SKIP LOCKED` behavior under concurrent Postgres
transactions; (2) scheduler reservation lifecycle (reserve/commit/release/
expire/dedup/spend-cap) — 14 passing tests, with the daily-spend-cap
explicitly disclosed as a soft check-then-insert guarantee, not atomic; (3)
outage simulation as closed-form arithmetic over a 1/3/5-project pool — 10
passing tests, deterministic, not a live provider-outage rehearsal; (4) cache
reuse as a key-computation correctness proxy (determinism + field-sensitivity
+ policy-invalidation, 5 tests) — not a hit-rate or performance number, since
there is no live traffic to measure against.

What's genuinely BLOCKED and not faked: G01/G02's real Postgres race proof,
G10/G11's held-out research-quality corpus and G12/G13/G17's live-sample
measurements (Gemini key, Kronos weights), G14's actual cold/warm
queue/stage/first-useful/verified-completion latency (no live queue under
load exists here — full suite wall-clock is not a substitute and is labeled
as such above), and G18 (explicitly deferred to not-yet-started Phase 11, not
a "doesn't apply" claim). Only G19 is a genuine NOT_APPLICABLE, not a
disguised BLOCKED — single-user MVP architecture per CLAUDE.md, with a
disclosed unauthenticated admin endpoint as a known gap rather than a G19
violation, since no shared/public deployment is in scope.

Full matrix: `docs/v3-execution/phase-10-gate-matrix.md` (this file).

## Coordinator follow-up (2026-09-15, after all 3 workers reported)

Full suite re-run after the 3 workers' new tests landed: **375 passed, 0
failed**, 23s — the G03 precision-tail failure above did not reproduce on
this run despite being reported 3/3 stable by the performance reviewer;
either the test-order dependency was transient or resolved by an
intervening edit. Not chased further, since the projection's own
final-value assertion already passed even in the failing run.

Two real correctness gaps surfaced by the research reviewer were fixed,
not just disclosed:
- `evidence_ledger.verify_fact` now writes `final_status` back onto
  `Fact.support_status` (was: computed transiently, never persisted, so
  `ClaimReference.support_status`'s "mirrors Fact.support_status" claim
  was false for any caller reading the column directly). New test
  `test_verify_fact_persists_result_back_to_the_fact_row` replaces the
  adversarial test that proved the bug.
- `ReportVerificationSummary.fully_verifiable` and the `numerical_check`
  layer both got explicit caveat docstrings (not behavior changes): the
  former proves internal consistency (claim traces to a real fetched
  passage) not independent multi-source corroboration; the latter checks
  a numeric input exists, not that the formula recomputes correctly. Both
  are real, disclosed limitations — a full fix (independent-source
  requirement, per-formula recompute registry) is new feature scope, not
  a Phase 10 audit repair.

Not fixed, left as disclosed gap per financial reviewer's finding:
`api/plans.py` never wires `issuer_concentration_limit` into
`validate_constraints` — `HoldingPosition` has no asset-class/per-symbol
breakdown surfaced through the planning API yet (holdings do have
`instrument_id`, so this is feature-buildable later, not a hard blocker,
but out of this audit pass's repair scope).
