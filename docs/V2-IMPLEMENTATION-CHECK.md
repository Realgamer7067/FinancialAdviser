# V2 implementation check

Checked 14 September 2026 against the current working tree, including uncommitted changes, and `V2-RETHINK.md`. This is a verification handoff for V3; the original blueprint remains unchanged.

**Verdict: substantial V2 foundation work is implemented and focused tests pass. The entire blueprint, particularly the proposed Plan B research workspace, is not complete.** Treat the current application as the V3 starting point and carry the specific unfinished requirements forward.

## Confirmed implementation

| Area | Evidence | Verification scope |
|---|---|---|
| Portfolio caps and explicit unallocated cash | `backend/app/models_iface/portfolio_mvo.py`; `backend/app/api/portfolio.py` | Single-name and fallback cap tests pass; date-indexed return alignment tested |
| Allocation rebuilt after rejection | `backend/app/pipelines/recommendation_pipeline.py:740` | Pipeline regression tests pass; score/allocation dependency remains below |
| Candle source filtering and natural identity | Pipeline candle helpers; `backend/app/models/market.py`; migration `0007` | Focused history/pipeline tests pass; deployed migration state not checked |
| Newest completed recommendation, including empty outcomes | `backend/app/api/recommendations.py:101` | Recommendation API tests pass; portfolio endpoint is a separate unresolved case |
| Worker atomic claim, leases, token checks | `backend/app/worker.py`; `backend/app/pipelines/progress.py`; migration `0008` | Sequential SQLite worker tests pass; PostgreSQL races and publication fencing remain unproven |
| Richer council input | `backend/app/scoring/evidence.py`; pipeline evidence conversion | Evidence tests pass; articles are headline/URL metadata, not retrieved passages |
| Rank before first truncation | `backend/app/pipelines/recommendation_pipeline.py:615` | Source inspection; expensive inference still precedes another unchanged ranking |
| Ownership semantics and fiscal date handling | `backend/app/providers/fundamentals.py`; migration `0009` | Source inspection; complete period/unit/source contracts remain unfinished |
| Kronos samples, percentile bands, nullable confidence | `backend/app/models_iface/kronos.py`; calibration module; migration `0005`; forecast UI | Four stubbed forecast tests and subscore tests pass; real predictive calibration not established |
| Backtest accounting and dated technical calculations | `backend/app/backtesting/engine.py`; `backend/app/services/technical_analysis.py` | Focused regression tests pass; this does not establish strategy outperformance |
| Frontend progress, refresh recovery, richer reports and charts | `frontend/src/lib/useJobPolling.ts`; report/dashboard/chart components | Source inspection and TypeScript pass; browser interaction/accessibility not tested |

## Remaining gaps to carry into V3

1. **P0 — An empty new run can leave an old portfolio active.** The pipeline creates no `PortfolioRecommendation` when no accepted allocation remains (`recommendation_pipeline.py:768`). `_load_latest_portfolio` selects the newest portfolio row without checking the newest completed council run (`backend/app/api/portfolio.py:59`). Thus an earlier allocation remains available through both `/latest` and `/allocate`. Bind allocation retrieval to the exact completed run and publish an explicit empty/cash outcome. This is a source-established path, not a new runtime regression test in this check.

2. **P0 — Job fencing is incomplete.** Terminal/progress helpers read a token and later commit ordinary ORM changes; the token is not an atomic update predicate. More importantly, the pipeline commits `council_run.status = "done"` and result rows without a final ownership check (`recommendation_pipeline.py:782`). A superseded worker can still publish a completed run that the latest endpoint sees. Lease renewal occurs at stage updates, so a long stage can outlive its lease. Require atomic ownership enforcement through publication, independent heartbeat/cancellation, and PostgreSQL interleaving tests. Existing worker tests use SQLite and sequential token replacement.

3. **P1 — Reports still mix vintages.** `backend/app/api/stocks.py:39` onward independently selects latest candles, fundamentals, technicals, forecasts and recommendations. Council text is tied to a recommendation run, but the complete page has no immutable evidence manifest. Latest candles also lack a source/mode filter here.

4. **P1 — Fundamentals cache lacks source/mode isolation.** `_get_cached_fundamentals` (`recommendation_pipeline.py:248`) filters instrument and retrieval TTL only. Candle isolation does not establish isolation for all data. Include provider/mode and relevant version identity in reuse rules.

5. **P1 — Research remains the fixed council.** `backend/app/council/orchestrator.py` still runs a planner, five analysts and a judge per candidate. The Qwen completion adapter remains in `backend/app/models_iface/llm.py`. Passage retrieval, claim/source ledger, verified citations, bounded evidence-driven follow-ups and durable research checkpoints were not found in the inspected application. These are unfinished V2 aspirations to incorporate deliberately in V3.

6. **P1 — Slow work remains on the critical path.** Kronos runs over `stage1` before `stage2` repeats the same fundamental/technical ranking (`recommendation_pipeline.py:624`). Portfolio inputs still contribute to pre-publication scores (`recommendation_pipeline.py:929`), even when allocation is subsequently rebuilt. Separate assessment, suitability and allocation; measure stage timings before attributing all latency to the LLM.

7. **P1 — Recovery and calibration claims need narrower wording.** A failed initial stored-job fetch clears the saved ID for any error (`frontend/src/lib/useJobPolling.ts:78`), including a transient failure. Kronos has calibration machinery, but the inspected tests stub `_run`; they do not prove real sampling quality, held-out interval coverage or financial usefulness. Sample percentiles are not established real-world confidence intervals.

8. **Product scope — SIP and alternatives remain separate.** `backend/app/services/financial_planning.py` supplies deterministic SIP projections; `backend/app/api/education.py` serves static alternative-product education. The allocator still operates on stocks. Existing holdings, cross-asset exposure, goals and recurring contributions do not yet form one allocation process.

## Verification results

**111 focused backend tests passed in two non-overlapping groups. Frontend TypeScript passed.** Backend checks were rerun outside the sandbox after sandboxed async/thread-dependent runs timed out (exit 124); the successful reruns do not prove the precise cause of the sandbox stalls. No full-suite pass is claimed.

From `backend/`, with `PYTHONDONTWRITEBYTECODE=1` and a 55-second command timeout:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=25 tests/test_portfolio_mvo.py tests/test_kronos_model.py tests/test_backtest_engine.py tests/test_worker.py tests/test_recommendations_api.py tests/test_stock_detail.py tests/test_pipeline_smoke.py tests/test_stock_history.py tests/test_job_progress.py
# 36 passed, 13 warnings in 18.27s

.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_subscores.py tests/test_final_score.py tests/test_risk_gate.py tests/test_risk_scoring.py tests/test_backtest_metrics.py tests/test_fundamental_analysis.py tests/test_technical_analysis.py tests/test_financial_planning.py tests/test_evidence_richness.py
# 75 passed, 12 warnings in 2.47s
```

From `frontend/`:

```sh
node node_modules/typescript/bin/tsc --noEmit --incremental false
# exit 0
```

Warnings include existing Pydantic namespace and FastAPI/pytest-asyncio deprecations, plus a numerical warning in a portfolio alignment fixture. No application code, database, credentials or original blueprint was changed by this verification. No live provider calls, deployment/migration checks, PostgreSQL concurrency tests, browser review, full research-quality evaluation or model latency benchmark were performed.

## V3 planning handoff

Preserve the implemented foundations. Start V3 scope with the correctness gaps above, then design one integrated goal/holdings/asset-allocation/contribution journey, evidence-backed research, and a measured faster model path. The team has five members with five accounts; actual Google Cloud project identities and quotas remain unverified. Model scheduling must reflect those projects rather than assuming one independent quota per account or key. Detailed V3 implementation decisions and performance targets remain to be planned against this verified baseline.
