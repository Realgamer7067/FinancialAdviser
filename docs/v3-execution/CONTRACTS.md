# V3 execution contracts (frozen at Phase 00)

Owner: coordinator. Version each contract when it changes; note the version in
dependent phase reports. These are the initial contracts required to start
Phases 01/02; later phases extend them under the same versioning rule.

## C1. Run outcome contract (v1) — Phase 01

Every recommendation-producing run (council run) and every portfolio
allocation resolves to exactly one of these outcomes, identified by the
**exact run/job identity that produced it**, never inferred from "most recent
row in a child table":

| Outcome | Meaning | Required fields |
|---|---|---|
| `empty` | Run completed; zero candidates survived screening/risk-gate | `run_id`, `completed_at`, `reason` |
| `populated` | Run completed; N recommendation rows exist | `run_id`, `completed_at`, `count` |
| `infeasible_allocation` | Candidates survived but no allocation could be constructed (e.g. all excluded post-gate, no return series) | `run_id`, `completed_at`, `reason` |
| `superseded` | A newer run of the same kind exists; this one is historical | `run_id`, `superseded_by_run_id` |
| `running` | Not yet terminal | `run_id`, `stage`, `progress_pct` |
| `failed` | Terminal, did not complete | `run_id`, `error` |

**Rule:** "latest" for any of `recommendations`, `portfolio`, and (once built)
`planning`/`research` endpoints means *the newest run whose status is
terminal (`done` or explicitly empty/infeasible), scoped to the correct
parent identity* — never "the newest child row in a downstream table that
happens to exist." A run that legitimately produced zero rows in a child
table (recommendations, portfolio allocation) must still be resolvable as
the current outcome, distinct from "no run has ever completed."

**v1 known gap this contract fixes (Phase 01 target):** `portfolio.py`'s
`_load_latest_portfolio` currently selects the newest `PortfolioRecommendation`
row directly, with no join back to the run that produced it and no check that
a *newer* completed run exists with no accepted allocation. Verified still
present in the current tree (`backend/app/api/portfolio.py:48-61`,
2026-09-14).

## C2. Job-attempt / publication-ownership contract (v1) — Phase 01

- A job attempt is identified by `(job_id, worker_token, lease_expires_at)`
  (already in `RecommendationJob`, migration `0008`).
- **v1 gap this contract fixes:** today only the *job row's* terminal write
  (`worker._mark_done` / `_mark_terminal`) is fenced by `worker_token`. The
  pipeline's own publication commit — `council_run.status = "done"` plus every
  `Recommendation`/`PortfolioRecommendation` row — happens inside
  `run_recommendation_pipeline` and commits unconditionally
  (`recommendation_pipeline.py:782-784`), before the fenced job-status write
  ever runs. A worker whose lease expired mid-run and was reclaimed by another
  attempt can still complete its own pipeline run and publish real
  `CouncilRun`/`Recommendation` rows; only the *job row* would then fail to
  update, while the *council run and its recommendations are already live*.
  This is a real publication race, not yet closed.
- **v1 rule:** no row that represents a "current outcome" (`CouncilRun.status
  = "done"`, any `Recommendation`, any `PortfolioRecommendation`) may commit
  unless the owning job row's `worker_token` still matches at the moment of
  that same transaction. The check and the write must be atomic (single
  conditional UPDATE / same transaction with a row lock), not a prior read
  followed by an unconditional write.
- Heartbeat (lease renewal) must not depend solely on stage-transition
  frequency — a single long-running stage (e.g. one slow Kronos/LLM call
  inside a loop with no intermediate `set_stage`) can outlive
  `job_lease_seconds` while still legitimately working. v1 records this as a
  known gap; Phase 01 must either shorten the practical worst-case stage
  granularity or add an independent heartbeat not tied to `set_stage`.

## C3. Data identity contract (v1, partial) — Phase 02 scope, flagged now

Already applied: `MarketCandle` natural key includes `source` (migration
`0007`); pipeline-side candle cache read (`_get_cached_candles`) filters by
`_expected_candle_source()`.

**Not yet applied, verified still open (2026-09-14):**
- `backend/app/pipelines/recommendation_pipeline.py:248` (`_get_cached_fundamentals`)
  filters by `instrument_id` and TTL only — no source/mode filter. A
  demo↔live toggle can serve the wrong mode's fundamentals from cache.
- `backend/app/api/stocks.py:39-46` (`latest_candle` read) and the
  fundamentals read a few lines below it query "most recent row" with no
  source filter at all — this is an API-read-path gap, distinct from (and
  in addition to) the pipeline-side ingestion-path fix already applied.

Full immutable-manifest binding (report → exact data/feature versions) is
Phase 02's real deliverable and is out of Phase 00/01 scope; this contract
section only freezes the *identity fields* (`provider`, `mode`,
`instrument_id`, `interval`, `source`) that Phase 02 must reuse.

## C3a. Data identity contract (v2, Phase 02 — supersedes C3's "not yet applied" items)

- `MarketCandle` refreshes now soft-supersede instead of hard-delete
  (`import_batch_id`, `superseded_at` columns; partial unique index
  `uq_market_candles_natural_key_current` scoped to `superseded_at IS NULL`).
  History a published report's evidence may reference is preserved, not
  destroyed on the next refresh. `_persist_candles` is idempotent: an
  unchanged re-import touches nothing.
- Every candle now carries `adjusted: bool` (split/dividend-adjustment
  status) — `Candle` (pydantic) and `MarketCandle` (ORM) both require it
  explicitly, no default inferred silently. yfinance path: `True`
  (`.history()` defaults to `auto_adjust=True`). Demo path: `False`
  (synthetic, no real corporate actions to adjust for).
- Both remaining "not yet applied" API read-path gaps from C3 are now
  closed: `api/stocks.py`'s `/{symbol}` and `/{symbol}/history` and
  `api/portfolio.py`'s `/allocate` all filter `source == expected_*_source()`
  AND (candles only) `superseded_at IS NULL`.
- Small permitted-source registry frozen: `docs/v3-execution/source-registry.md`.

## C7. Data-manifest contract (v1, Phase 02)

- New table `data_manifest_entries` (migration `0010`): one row per
  `(council_run_id, instrument_id)` — unique-constrained, append-only, never
  updated. Identifies the fundamentals/technicals/kronos data that fed that
  instrument's evidence by NATURAL identity fields (`source`, `as_of_date`/
  `retrieved_at`/`computed_at`/`generated_at`, `model_version`), not by
  foreign-keying to the exact row id (would have required invasive changes
  to how evidence is threaded through the pipeline — out of Phase 02 scope).
- Written once per candidate, inside `_evaluate_candidate`
  (`app/pipelines/recommendation_pipeline.py`), in the same uncommitted
  transaction as everything else the run produces (`record_manifest_entry`
  never commits itself).
- Read via `get_manifest_entry(db, council_run_id, instrument_id) ->
  DataManifestEntry | None`. `None` means "legacy run, predates the manifest
  system" (`is_legacy()`) — never backfilled retroactively.
- `api/stocks.py`'s `GET /{symbol}` resolves the newest `Recommendation`
  first, looks up its manifest entry, and — when found — pins the
  fundamentals/technicals/kronos(30d) reads to those exact natural-identity
  values instead of always "most recent." `latest_price`/`price_as_of` stay
  independently live on purpose (current market price is supposed to be
  fresh; the *scored evidence inputs* are what must match what the
  recommendation actually saw). `StockDetail.evidence_is_legacy: bool` tells
  the caller which case applied. `kronos_horizons` (7d/90d display-only
  entries) stay "most recent" — the manifest only tracks the 30d forecast
  that scoring actually used.

## C8. Financial-input identity contract (v1, Phase 03)

- `HoldingsSnapshot`/`HoldingPosition`, `Goal`/`GoalEarmark`,
  `RecurringCommitment` — see `backend/app/models/holdings.py`, `goals.py`,
  `commitments.py`. Holdings snapshots are append-only (new import = new
  snapshot); goals soft-supersede on edit (`version`/`superseded_at`, same
  pattern as `MarketCandle`).
- **All money fields are `Numeric`/`Decimal`, never `Float`** — the first
  new domain area in this codebase to follow V3 section 10.1's money-storage
  requirement; existing Float-for-money columns elsewhere predate this
  contract and are out of scope to retrofit.
- Goal earmarking invariant (enforced at write time via a real query, not a
  DB constraint): the sum of all earmarks against one holding must not
  exceed that holding's amount.
- `RecurringCommitment.budget_interpretation` is DB-nullable but
  API-required (422 if missing) — "must be explicit, never assumed" is an
  application-layer rule here, not a schema-level one.
- Known incomplete: goal-edit earmark carry-forward is not automatic
  (orphaned on the old version); no real CSV parser (JSON rows only).

## C9. Product catalogue contract (v1, Phase 03)

- `ProductCatalogEntry` (`backend/app/models/catalogue.py`) — full V3 4.2
  identity contract. Every current row is synthetic
  (`is_synthetic=True`, `source_ids=["synthetic_fixture_v1"]`) — no real
  reviewed catalogue exists yet.
- `resolve_support_level()` (`backend/app/services/catalogue.py`) is the
  source of truth for what an entry actually qualifies for — never trust
  the stored `support_level` column. Two independent gates apply, combined
  via `min()`: (1) critical-terms completeness (missing any critical term
  caps at `category_planning`), (2) a `_POLICY_CEILING` table for
  product families V3.0 explicitly scopes down regardless of term
  completeness (currently: `hybrid_fund -> holdings_only`). A fully-
  populated entry can still be capped by (2) — terms completeness alone
  never overrides a policy ceiling.

## C10. Model-adapter and scheduler contract (v1, Phase 04)

- `ModelRequest`/`ModelResponse`/`ModelAdapter` (`backend/app/models_iface/model_adapter.py`)
  — provider-neutral, with `GeminiAdapter` (real `httpx` REST, no SDK — none
  installable in this environment) and `QwenAdapter` (wraps the existing,
  untouched `QwenOpenAICompatibleProvider`). Neither `orchestrator.py` nor
  `llm.py` route through this yet — that's Phase 07's integration work.
- **Unresolved, flag for whoever wires in a live key**: the adapter targets
  the classic `generateContent` REST endpoint; two other fetched Google doc
  pages described a newer "Interactions API" instead. Re-verify against
  live docs (and, once available, a real key) before trusting either
  definitively — not resolved in this pass.
- `ModelProject`/`ModelCallReservation` (`backend/app/models/scheduler.py`,
  `backend/app/services/model_scheduler.py`) — atomic reservation lifecycle
  reusing Phase 01's `publication.py` single-conditional-UPDATE technique.
  `task_attempt_id` dedup is a real atomic guarantee (DB unique constraint).
  **The daily-spend-cap check itself is NOT atomic** (check-then-insert) —
  a real concurrent-safety fix needs a DB aggregate constraint or `SELECT
  ... FOR UPDATE`, unprovable without PostgreSQL. Recorded as a known soft
  limitation, not silently treated as a hard guarantee.
- Model IDs/pricing verified live against `ai.google.dev` 2026-09-14:
  `gemini-3.5-flash-lite` ($0.30/$2.50 per 1M in/out) and `gemini-3.8-flash`
  ($0.75/$3.75 through 2026-12-31, then $1.50/$7.50) — both match the V3
  plan's proposed defaults exactly, no correction needed.
- Current orchestrator call count independently verified against its real
  code: 19 calls for a 3-candidate run before retries — matches the V3
  plan's stated figure exactly (`backend/app/services/call_budget.py`).

## C11. Allocation/SIP engine contract (v1, Phase 05)

- `backend/app/services/allocation_engine.py`: `target_gap_allocation`
  closes the GAP toward target exposure, never splits new cash by target
  percentages alone — verified exact against V3 6.6's worked fixture
  (₹100k @ 60/30/10, target 50/40/10, new ₹20k → ₹0/₹18,000/₹2,000).
  `validate_constraints` is a genuinely separate function from the
  allocator (V3 6.1 step 9's "independent" validation). Fund look-through
  preserves undisclosed remainder as `unknown_remainder`, never
  redistributed into known classes. No persistence yet — pure dataclasses.
- `backend/app/services/cash_flow_engine.py`: sits alongside (does not
  replace) `financial_planning.py`. `RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING`
  reproduces the legacy R/12 convention exactly (cross-checked against
  `sip_future_value()` directly); `RateBasis.EFFECTIVE_ANNUAL` is the new
  option. Every total is read off a real month-by-month ledger, never
  computed twice by a separate closed-form shortcut that could disagree
  with it. `back_solve_required_contribution` never returns negative.
- `backend/app/services/capacity_policy.py` + `config/allocation_policy.yaml`:
  capacity/eligibility computed with NO risk-tolerance parameter in the
  function signature at all — structural proof of V3 15.1's required
  separation. The policy file is explicitly `is_synthetic: true` with a
  rationale — no reviewed/approved policy exists yet (unresolved external
  input, unchanged since Phase 00/03).
- **Known gap, not yet done**: none of these three modules are wired in to
  replace the old, entangled `portfolio_score`-feeds-back-into-company-scoring
  path in `subscores.py`/`final_score.py`/`recommendation_pipeline.py`. That
  replacement is real follow-up work.

## C12. Retrieval and claim-ledger contract (v1, Phase 06)

- `backend/app/services/retrieval.py`: SSRF defense resolves+validates+pins
  the connection IP itself (custom `httpcore` backend), never trusting a
  second, independent DNS resolution at connect time. Redirects always
  manual, re-validated per hop. Byte-limit enforcement is a real streaming
  abort. PDF extraction is honestly stubbed (`RetrievalRejected`, no PDF
  library installable in this environment — no `pip`). **Not yet tested**:
  the actual network fetch/redirect path against a real or properly-mocked
  transport (SSRF pre-checks and text extraction ARE tested, for real,
  without needing network mocking).
- `backend/app/models/evidence.py` / `backend/app/services/evidence_ledger.py`:
  layered fact verification (schema → referenced-IDs-exist →
  entity/unit-consistency → numerical-check → source-support), each layer
  applicable only to the relevant `claim_type`. "A real link without a
  supporting passage does not count as verified support" is enforced and
  tested literally (empty-text passage → not counted). Entity/unit
  consistency is a small explicit heuristic — catches obvious mismatches,
  marks anything else inconclusive, never falsely passes.
- `backend/app/services/source_corpus_fixtures.py`: 12 synthetic
  representative documents + hostile fixtures (malformed PDF, oversized
  response, prompt-injection text, SSRF URL patterns incl. the real
  cloud-metadata address). Addendum in `source-registry.md` makes explicit
  this is fixture-only, not real acquisition.

## C13. Research workflow, assessment and reuse contract (v1, Phase 07)

- `backend/app/models/research.py` / `services/research_workflow.py`: the
  exact V3 9.2 state machine (`created → resolving → retrieving →
  calculating → synthesizing → verifying → ready_to_publish → published`,
  plus `cancelled`/`failed`), transitions guarded by an atomic conditional
  UPDATE (same technique as `publication.py`, Phase 01). Standard-question
  checklist is deterministic — 3 branches, zero model calls.
  `run_branch` is the first real integration of Phase 06's
  `retrieval.py`/`evidence_ledger.py` into an orchestrator, producing
  genuine `complete`/`partial`/`unavailable`/`failed` outcomes.
- `backend/app/schemas/research_assessment.py`: `CompanyAssessment` has
  exactly 13 fields and structurally cannot carry a `target_price` or
  `confidence` value — verified by asserting the field set directly, not
  by convention alone.
- `backend/app/services/research_verification.py`: per-claim verification
  wraps `evidence_ledger.verify_fact`; `apply_sector_template` is a small
  explicit bank-vs-industrial-ratio filter, not a general engine.
- `backend/app/models/research_report.py` / `services/research_reuse.py`:
  `compute_artifact_key` deliberately excludes personal profile/holdings
  versions (V3 13.2 puts those only under the separate "Suitability/plan"
  cache row, never "Company report") — reasoned and tested, not assumed.
  A follow-up report publish is proven, by test, to never mutate its
  parent's `content`/`manifest_snapshot`.
- **Known gap, not yet done**: no orchestration loop ties the pieces above
  into one real end-to-end research call. Each function is tested in
  isolation; the glue (session-state-aware branch dispatch, calling
  synthesis/verification/reuse in sequence, actually publishing) is
  unbuilt. Also: branch-level cancellation isn't wired (only session-level
  is); `run_branch` doesn't itself check session state before running.

## C4. Money/allocation contract (v1, unchanged from V2)

- `PortfolioAllocationResult.unallocated_cash` is explicit; the cap must never
  be exceeded by any fallback path. (Implemented, tested — `portfolio_mvo.py`,
  `portfolio_finrl.py`.)
- No change needed at Phase 00; Phase 05 extends this to multi-asset holdings.

## C5. Error/evidence-missingness contract (v1, unchanged from V2)

- `None` means unknown, never guessed or zero-filled. Sub-scores return `None`
  when their evidence is absent or uncalibrated (`kronos_score`,
  `fundamental_score`, etc.). Preserved; no change at Phase 00.

## C6. Test-environment contract (v1)

- **PostgreSQL: unavailable in this execution environment.** No `psql`
  server, no `pg_ctl`/`postgres`/`initdb` binaries, no `docker`. Verified
  2026-09-14 (`pg_isready` → "no response"; binary search → not found).
  Every gate requiring real PostgreSQL locking/interleaving evidence (G01,
  G02, and Phase 02's concurrent-importer case) is **blocked**, not failed.
  SQLite-provable logic (atomic-predicate correctness, fencing logic,
  sequential token replacement) proceeds; true concurrent-transaction proof
  does not exist until a PostgreSQL instance is available.
- Backend test commands (from `backend/`):
  ```sh
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/
  ```
  132 passed, 13 warnings, ~20s, in this environment on 2026-09-14 — full
  suite, no stall observed. (The prior reviewer's sandbox-stall note is
  recorded as historical; it did not reproduce here. This does not establish
  the stall's original cause.)
- Frontend commands (from `frontend/`):
  ```sh
  node node_modules/typescript/bin/tsc --noEmit --incremental false   # exit 0
  npm run build                                                       # succeeds, all 12 routes
  ```
- Updated 2026-09-14 (post Phase 02): full backend suite **154 passed**, run
  3x consecutively with no flakiness after all three Phase 02 workers'
  changes integrated (one transient `IntegrityError` was observed by two
  workers mid-session while `market.py`/`recommendation_pipeline.py` were
  being concurrently edited by multiple agents; not reproduced after
  integration, 5/5 stable reruns). Frontend `tsc`/`npm run build` both clean.
- Updated 2026-09-14 (post Phase 03+04, 5 parallel workers): full backend
  suite **227 passed**, run 3x consecutively stable. No `pip` binary exists
  in this venv (`google-genai` SDK not installable) — Gemini adapter built
  against REST via `httpx` instead. No PostgreSQL still (see above);
  Phase 04's atomic-reservation logic is SQLite-provable at the
  single-statement level only, same limitation as Phase 01/02. Frontend
  unaffected this round (`tsc` still exit 0, no new frontend files).
- Updated 2026-09-14 (post Phase 05+06, 6 parallel workers dispatched in one
  batch): **all 6 subagents hit the session's rate limit (429) and
  terminated before reporting completion.** 3 of 6 had already reached
  "tests pass" before dying (Allocation, Policy/suitability, Source-fixture)
  and their work was verified directly by the coordinator, not trusted
  blind. 2 left a complete module but no test file (Cash-flow, Retrieval) —
  coordinator wrote and ran their tests after reviewing the actual code.
  1 (Evidence worker) produced nothing — coordinator built the claim ledger
  directly from the same frozen contract. Full backend suite after all
  integration: **295 passed**, run 3x consecutively stable. **Lesson for
  future phases: do not dispatch 6 subagents in one batch — the guide's own
  4-slot (coordinator+3) guideline exists for a reason beyond just
  ownership clarity; it's also a rate-limit budget concern this session
  learned the hard way.**
- Updated 2026-09-14 (post Phase 07, exactly 3 parallel workers -- the
  lesson above applied): all 3 completed cleanly, zero rate-limit
  interruptions. Full backend suite **338 passed**, run 3x consecutively
  stable. Confirms 3-subagent batches are the right size for this
  session's rate budget; 6-in-one-batch (Phase 05+06) was the outlier to
  avoid, not the norm to expect.
- Updated 2026-09-15 (post Phase 05 API wiring + Phase 09, 2 parallel
  workers): Phase 05's engine wired into POST /api/plans + GET
  /api/plans/scenarios (5 new tests). Phase 09 forecast worker validated
  KronosModel two layers deep (stubbed predictor, not just stubbed _run)
  and hardened kronos_calibration.py against malformed hit_rate values
  (was an unguarded float() cast -- now fails closed to None). Backtest
  reviewer documented a previously-undisclosed convention: engine.py's
  returns approximate TOTAL return (yfinance auto_adjust=True upstream),
  not price return, with a regression test proving the distinction. Full
  suite: **367 passed**, stable.
