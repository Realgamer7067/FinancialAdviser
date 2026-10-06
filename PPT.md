# Financial Advisor — PPT generation brief

## Paste this instruction into your PPT generator

Create a **26-slide, 16:9 academic final-review presentation** titled **Financial Advisor**, supervised by **Dr. Jay Prakash Maurya**, for team members **25BCE10139, 25BCE10400, 25BCE11274, 25BCE10458 and 25BCE10340**. Use the exact slide content below and place the longer explanations in speaker notes. This brief can be used with the intended Gemma/Gamma PPT tool or another slide generator; attach assets manually if the tool cannot read repository paths.

Use a white/light background, dark navy text and restrained blue/teal emphasis. Keep body text at least 22–24 pt and diagram labels readable. Prefer one clear diagram, comparison table or application view per slide. Preserve registration numbers and supervisor spelling. Use ₹ for rupees. Keep source citations in small but readable footers. Do not invent institution, student names, guide approval, Review II feedback, screenshots, demo recordings, investment accuracy or performance charts.

The product UI may say Portfolio Intelligence; the official academic title is Financial Advisor. Treat the project as a private read-only prototype. Keep current `/api/v4` behaviour separate from the disabled-by-default older recommendation pipeline. Policy assumptions and model limits must stay visible. Published paper benchmarks are not project results.

Suggested duration: **18–22 minutes**, including a two-minute recorded/live demonstration. Presenter order is the registration-number order above. Shared slides 23–24 let each member narrate their own screen.

**Available diagram assets:**

- `docs/presentation/assets/system-architecture.png` and `.svg`
- `docs/presentation/assets/data-workflow.png` and `.svg`
- `docs/presentation/assets/decision-workflow.png` and `.svg`

**Actual recording/screenshots:** capture the running project with fictional data using [the demo guide](docs/presentation/DEMO_AND_REVIEWER_QA.md). These assets are not fabricated by this Markdown file. Insert the real MP4 and images before exporting the final deck. Guide approval, Review II corrections and report submission must be confirmed by the team/supervisor.

## Coverage of the supplied presentation guidelines

| Required item | Slides |
|---|---|
| Project title, guide and members | 1 |
| Introduction | 2 |
| Existing work and limitations | 3 |
| Proposed work and methodology | 5, 11, 15, 21 |
| Novelty | 19, 26 |
| Real-time usage | 19 |
| Hardware/software requirements | 6 |
| Overall architecture diagram | 7 |
| Literature review | 4, with primary sources in notes |
| Module description | 8–10, 12–17, 20–21 |
| Module workflow | 11, 15, 17, 21 |
| Implementation/coding | 18 |
| Demo video | 23 |
| Project snapshots | 24 |
| Testing | 22 |
| Results and discussion: input/output | 25 |
| Conclusion and future scope | 26 |

## Team coordination and marks

25BCE10139: slides 1–8. 25BCE10400: 9–11. 25BCE11274: 12–15. 25BCE10458: 16–19. 25BCE10340: 20–22 and 25–26. All: 23–24.

Assessment: implementation/demo 20; documentation 25; presentation/team coordination 5; outcome 5; conclusion/future scope 5; total **60**. Prepare the mandatory report with supervisor approval, actual Review II corrections and the required submission timing. Do not assert those administrative steps are complete merely because the slides exist.

---

## Slide 01 — Financial Advisor

**Presenter: 25BCE10139**

**Subtitle:** Explainable, account-aware analysis of Indian investments.

**Supervisor:** Dr. Jay Prakash Maurya.

**Team:** 25BCE10139 · 25BCE10400 · 25BCE11274 · 25BCE10458 · 25BCE10340.

**Scope line:** Private, read-only college prototype; the owner executes orders manually.

**Visual:** Clean title layout with a simple account → review motif. No invented university logo.

**Speaker notes:** Introduce the official project title, supervisor and five-member team. The UI product name is Portfolio Intelligence. The goal is to connect holdings, personal finances and evidence into an explainable review.

---

## Slide 02 — Introduction: an investment needs context

**Presenter: 25BCE10139**

- Holdings can be spread across accounts and asset types.
- Reserve, debt and goals affect what risk an owner can bear.
- A chart or AI answer alone cannot represent the whole situation.
- Financial Advisor connects data, constraints and reasons.

**Visual:** Five connected inputs: accounts, finances, goals, market data and research.

**Speaker notes:** Define portfolio-level analysis. The system first asks what is known and missing before considering a change. It does not promise profit or automatically trade.

---

## Slide 03 — Existing work and limitations

**Presenter: 25BCE10139**

| Approach | Useful function | Gap addressed here |
|---|---|---|
| Account dashboard | Source positions | Cross-account completeness and version binding |
| Spreadsheet/calculator | Flexible maths | Reproducible dated inputs and constraints |
| Isolated indicator | Price description | Personal suitability and independent evidence |
| Standalone LLM | Flexible explanation | Verified claims and auditable numbers |
| Pure optimiser | Estimated portfolio tradeoffs | Missing data, goals, units and accounting |

**Speaker notes:** This is a comparison of architectural approaches, not a benchmark declaring named commercial tools inferior. Many tools may cover some of these gaps; our project demonstrates their integration.

---

## Slide 04 — Literature review: foundations, not claimed results

**Presenter: 25BCE10139**

| Research | Role in this project |
|---|---|
| Markowitz, 1952 | Earlier mean-variance methods |
| Ledoit & Wolf, 2004 | Covariance shrinkage for risk |
| Aracı, 2019: FinBERT | Financial sentiment adapter |
| Shi et al., 2025: Kronos | Pretrained candlestick forecasts |
| Qwen Team, 2024 | Structured model assistance |
| Schulman et al., 2017: PPO | Experimental offline policy path |

**Footer:** Published model benchmarks are not our project's measured investment results.

**Speaker notes:** Use the following primary references, with full links in notes: [Markowitz](https://onlinelibrary.wiley.com/doi/full/10.1111/j.1540-6261.1952.tb01525.x), [Ledoit–Wolf](https://ledoit.net/Honey_2004.pdf), [FinBERT](https://arxiv.org/abs/1908.10063), [Kronos](https://arxiv.org/abs/2508.02739), [Qwen2.5](https://arxiv.org/abs/2412.15115), [PPO](https://arxiv.org/abs/1707.06347). We integrate established methods rather than claiming original training of the pretrained models. Full context is in the sourced literature-review document.

---

## Slide 05 — Proposed work and methodology

**Presenter: 25BCE10139**

**Workflow:** Import → validate → twin/valuation → constraints/risk → plan/compare → dated explanation.

- Preserve source provenance and unknown information.
- Use deterministic financial calculations and explicit policies.
- Restrict AI assistance to validated tasks.
- Keep the final action under the owner's control.

**Visual:** Use the data-workflow diagram, simplified if needed for large slide labels.

**Speaker notes:** Introduce the full pipeline. A no-change or insufficient-data result may be appropriate. Distinguish the main newer portfolio engine from the retained original recommendation flow, which is disabled by default.

---

## Slide 06 — Hardware and software requirements

**Presenter: 25BCE10139**

| Area | Requirement |
|---|---|
| Host | Modern laptop/desktop and browser; CPU inference supported |
| Practical preparation | Multi-core CPU, around 16 GB RAM suggested; not a benchmarked minimum |
| Runtime | Python 3.11 / Node 20 in CI; PostgreSQL 16 in Compose |
| Frontend | Next.js, React, TypeScript, Tailwind and Recharts |
| Backend | FastAPI, SQLAlchemy, Alembic, Pydantic and asyncio |
| Computation/AI | Decimal, NumPy, pandas, PyPortfolioOpt, PyTorch/Transformers |

**Speaker notes:** Model/cache/container storage varies. Initial build/downloads need network access. Optional provider integrations need account/model availability. No GPU is required for the intended CPU path. Do not present suggested hardware as measured performance testing.

---

## Slide 07 — Overall system architecture

**Presenter: 25BCE10139**

**Visual:** Full-slide `system-architecture.png` or SVG.

**Caption:** Next.js/proxy → FastAPI → deterministic engines and PostgreSQL; database jobs → worker → sources/models.

**Speaker notes:** Explain four Compose services. The API scheduler queues after-close work; the worker handles expensive tasks. Jobs use leases, retry limits and fenced publication. The migration barrier checks schema compatibility. Browser calls stay same-origin through the server proxy. There is no Redis/Celery service in this implementation.

---

## Slide 08 — Five modules and team responsibility

**Presenter: 25BCE10139**

| Registration number | Module |
|---|---|
| 25BCE10139 | Architecture, interface and runtime |
| 25BCE10400 | Data ingestion, identity and portfolio twin |
| 25BCE11274 | Financial capacity, goals and risk |
| 25BCE10458 | Signals, ranking and allocation |
| 25BCE10340 | Decisions, AI research and validation |

**Speaker notes:** These are presentation responsibilities, not assertions of historical code authorship. Each module has an input, output, workflow and known limits. Handoff: “The architecture needs trustworthy inputs; the next module establishes them.”

---

## Slide 09 — Accounts, imports and identity

**Presenter: 25BCE10400**

- Manual entry, CSV preview/confirm and optional read-only Angel sync.
- Each account keeps its own dated import history.
- ISIN/catalogue resolution is stronger than symbol-only guessing.
- Repeated requests use idempotency keys.
- Partial broker data does not replace the last complete import.

**Visual:** Source accounts → import batches → normalised observations.

**Speaker notes:** Explain real empty holdings versus unreadable response. A complete import is complete for that source, not a declaration that every account exists in the system. Broker login happens privately through a local CLI; no order endpoint is provided.

---

## Slide 10 — Portfolio twin and dated valuation

**Presenter: 25BCE10400**

- Twin = versioned holdings plus bound personal inputs.
- Economic state is separate from valuation freshness.
- Unit-based prices can change without ownership changing.
- Readiness covers accounts, holdings, valuation, identity and suitability.

**Equation:** `known value = sum of available holding values`.

**Speaker notes:** For 10 units at ₹500, reported value is ₹5,000. A later ₹520 price changes valuation to ₹5,200 without implying a trade. Value-only assets behave differently because their declared value is economic input. Unknown assets remain visible and unvalued, not assigned zero.

---

## Slide 11 — Data module workflow and quality

**Presenter: 25BCE10400**

**Workflow:** Source → validate rows/identity → complete batch → state → valuation → readiness.

- Preserve prior complete data on sync failure.
- Store source dates separately from retrieval time.
- Audit corporate actions before using history.
- Disclose missing values and stale inputs.

**Visual:** Highlight the first half of `data-workflow.png`.

**Speaker notes:** Some market data uses scheduled external refreshes; missing broker/model access should remain an explicit gap. Normalisation prepares data for later metrics rather than inventing it. Handoff: “Recorded holdings now need personal capacity and goal context.”

---

## Slide 12 — Tolerance is different from capacity

**Presenter: 25BCE11274**

| Tolerance | Capacity |
|---|---|
| Behavioural willingness to accept losses | Financial ability to absorb them |
| Three questionnaire answers | Income, outgo, reserves and liabilities |
| Conservative/moderate/aggressive | Constraints and named missing inputs |

**Example:** ₹1,00,000 reserve / ₹25,000 monthly outgo = **four months**.

**Speaker notes:** With a six-month target the owner has a reserve shortfall even if their behavioural answers are aggressive. ₹60,000 income minus ₹20,000 expenses and ₹5,000 debt payments gives ₹35,000 computed surplus; user-stated investable surplus remains separate. Unknown liability payments are flagged.

---

## Slide 13 — Goals, claims and SIP scenarios

**Presenter: 25BCE11274**

- Goal claims reserve existing assets; commitments describe future contributions.
- Low/base/high assumptions: **4% / 8% / 11% effective annual**.
- Monthly rate: `(1 + R)^(1/12) − 1`.
- End-of-month ledger: `next balance = current × (1+r) + contribution`.
- A shortfall never loosens risk limits.

**Visual:** Three labelled assumption paths; do not invent a chart of real portfolio performance.

**Speaker notes:** These are deterministic policy illustrations, not probabilities or model forecasts. Taxes/fees, step-ups and proposed commitments are excluded in the current goal path. Today-money targets need inflation. Revise target/date/contribution when a goal is unreachable under stated scenarios.

---

## Slide 14 — Risk: exposure, volatility and stress

**Presenter: 25BCE11274**

- Known-value weights and verified issuer/sector exposure.
- Annualised volatility: `sample std(daily returns) × sqrt(252)`.
- Portfolio figure requires **252 aligned returns** and **80% coverage**.
- Drawdown measures an observed peak-to-trough fall.
- Stress applies one covered shock and reports unmodelled value.

**Speaker notes:** Static current weights describe a past window, not actual historical owner performance. A 120-to-90 fall is −25% drawdown. A −20% shock to ₹1,00,000 covered value is −₹20,000, not a probability. Underlying fund composition and unsupported sensitivities remain gaps.

---

## Slide 15 — Personal planning module workflow

**Presenter: 25BCE11274**

**Workflow:** Profile + liabilities + tolerance + goals → effective constraints → covered risk and scenario explanations.

- Unknown capacity restricts added risk.
- Reserve shortfall makes normal planning more cautious.
- Money claimed for goals due within three years is protected.
- A high required return does not create risk permission.

**Visual:** Two input branches, behavioural tolerance and financial capacity, merging with goals into constraints.

**Speaker notes:** This is an input/constraint layer, not stock selection. Show Financial profile, Goals or Risk during the shared demo. Handoff: “The next module selects only within those constraints.”

---

## Slide 16 — Signals and transparent stock ranking

**Presenter: 25BCE10458**

- Signals describe trend, momentum, volatility and tradability.
- Current stock rank combines **value / quality / momentum**.
- Default equal weights; sector percentiles shrink toward the wider group.
- Every component must meet coverage requirements.
- Rank 70 is not 70% profit probability.

**Equation:** `composite = weighted mean(Value, Quality, Momentum)`.

**Speaker notes:** Price-based signal families and the current ranking are different mechanisms. Trend/momentum share one descriptive family, liquidity is a gate and forecasts have zero family vote. Ranking momentum has an explicit unvalidated policy weight. Financial businesses use appropriate metrics. Inadequate components produce not-ranked.

---

## Slide 17 — New-money allocation workflow

**Presenter: 25BCE10458**

**Workflow:** Constraints → target gaps → eligible instruments → lot-aware units → hard gates → recorded plan.

- Buy-only; no forced sale or automatic order.
- Direct-stock satellites: max five names, two per sector, 3% each.
- Minimum sizes, charges and lot rounding matter.
- Unallocated money stays explicit.

**Speaker notes:** Target mix and limits are declared unreviewed policy. Existing over-target buckets can direct future money elsewhere without selling. A minimum three eligible satellite names and ₹5,000 minimum leg apply. What-if output remains hypothetical and does not erase engine gates.

---

## Slide 18 — Implementation and coding

**Presenter: 25BCE10458**

**Production source:** `backend/app/portfolio_intelligence/allocation/plan.py`.

```python
from decimal import ROUND_FLOOR, Decimal

def units_for(amount, price, lot, fee):
    return int(((amount / (price * (1 + fee))) / lot)
               .to_integral_value(rounding=ROUND_FLOOR)) * lot
```

**Illustration:** ₹10,000 budget, ₹500 price, 0.3% friction → **19 units, ₹28.50 friction, ₹471.50 leftover**.

**Speaker notes:** The production helper expects Decimal inputs; the surrounding pipeline checks eligibility, risk, minimums and paisa rounding. Explain why spending exactly every rupee is not always possible. This illustration is not a claim that a real stock leg passed every gate.

---

## Slide 19 — Real-world usage and project novelty

**Presenter: 25BCE10458**

- Consolidate accounts and understand completeness.
- Check reserve/goal constraints before adding risk.
- Inspect components, purchase quantities and reasons.
- Quote-assisted views, after-close jobs and on-demand research.
- Novelty: the integrated, versioned, evidence-aware workflow.

**Speaker notes:** Connected watchlist surfaces can refresh quotes during market hours; most historical signals/reviews are scheduled, not continuous tick-level inference. We integrate established methods rather than inventing them. Handoff: “A transparent proposal also needs fair comparison and verified evidence.”

---

## Slide 20 — AI research with evidence boundaries

**Presenter: 25BCE10340**

| Component | Restricted role |
|---|---|
| Kronos | Optional sampled candlestick forecast |
| FinBERT | Earlier financial sentiment labels |
| Qwen/Gemini | Optional structured research assistance |
| Python rules | Final financial maths, citation checks and thesis status |

**Workflow:** Documents → passages → facts → verification → condition mapping → qualitative status.

**Speaker notes:** We integrate pretrained models; PPO is a separate light-training experiment. Unknown fact IDs are rejected and unsupported numbers suppressed. Source-lineage grouping avoids treating copies as independent corroboration. Model availability or sample agreement does not establish profit accuracy.

---

## Slide 21 — Compare changes fairly against HOLD

**Presenter: 25BCE10340**

**Visual:** `decision-workflow.png` or SVG.

- Freeze the same baseline, valuation, constraints and goals.
- Apply equal contributions/withdrawals to every alternative.
- Recompute metrics and enforce hard gates.
- Report dominance, tradeoff, no material benefit or missing input.

**Invariant:** `assets_after + friction = assets_before + contribution − withdrawal`.

**Speaker notes:** HOLD retains new money as cash. Dominance is relative to compared metrics/materiality, not universal market superiority. Multi-leg allocation's hard-gate status is separate from its comparison with HOLD. A sale without tax-lot information is a review-required preview.

---

## Slide 22 — Testing and verification

**Presenter: 25BCE10340**

| Layer | Verification |
|---|---|
| Input/API | Row validation, idempotency, source errors and responses |
| Financial rules | Constraints, projections, conservation and rank coverage |
| Research | Citation IDs, numeric notes, contradictions and lineages |
| Frontend | TypeScript check and production build |
| Documentation | Links, diagrams, roles and guideline coverage |

**Current results:** 924 backend tests passed; 14 skipped. TypeScript passed; production webpack build passed.

**Result source:** `docs/presentation/VALIDATION.md` contains exact commands and limitations.

**Speaker notes:** Use exact current results from validation notes when exporting. Most tests use mocked transport and SQLite; PostgreSQL-specific tests need a disposable configured database. Frontend build passed using webpack after Turbopack hit an environment restriction. A software test suite does not establish investment skill. Historical ledger counts should not be substituted for a current run.

---

## Slide 23 — Demo video: two-minute end-to-end walkthrough

**Presenters: all five**

**Insert the actual rehearsed recording:** `financial-advisor-demo.mp4`, captured with fictional data.

**Sequence:** Overview → Holdings/twin → Profile/Risk → Rank/Allocation → Comparison/Evidence.

**Speaker notes:** This is a mandatory real capture step before final export; the generator must not invent a video. Each member narrates their module. Keep a local copy for network failure. The video must show actual outputs, including legitimate blocks/unknowns. Follow the storyboard in `DEMO_AND_REVIEWER_QA.md`.

---

## Slide 24 — Project snapshots: actual input and output

**Presenters: all five, one sentence per module**

**Insert actual captured application views:**

1. Overview/navigation.
2. Fictional holdings and twin readiness.
3. Profile/reserve or covered risk result.
4. Actual allocation/status and leftover money.
5. Comparison or evidence/freshness result.

**Visual:** Readable screenshot montage; use two large views with the others in appendix/notes if labels become too small.

**Speaker notes:** Capture the actual project; the SVG diagrams are not app screenshots. Retain dates and meaningful unknown/blocked statuses. Do not show personal broker IDs or invent populated success states. Caption each image with the actual input/status and what it proves.

---

## Slide 25 — Results and discussion

**Presenter: 25BCE10340**

| Illustrative input | Output | Meaning |
|---|---|---|
| ₹1 lakh reserve / ₹25k outgo | Four reserve months | Below six-month target |
| Rank components 70/80/60 | Composite 70 | Policy screen, not profit probability |
| ₹10k, ₹500/unit, 0.3% friction | 19 units + ₹471.50 cash | Conserved purchase accounting |
| Inadequate history/coverage | Insufficient-data reason | Unsupported precision refused |
| Conflicting metric changes | Tradeoff | No automatic “best” action |

**Speaker notes:** These are labelled arithmetic/logic examples, not market-performance measurements. Put actual rehearsed application outputs in slide 24 and actual test results in slide 22. Discuss unreviewed policy, fund look-through, point-in-time data, provider availability, historical bias and insufficient long-term live evidence.

---

## Slide 26 — Conclusion and future scope

**Presenter: 25BCE10340**

**Conclusion:** Financial Advisor integrates account data, financial capacity, risk and evidence into a transparent, owner-controlled review.

**Future scope:**

- Reviewed policies and stronger data coverage.
- Tax lots, fund look-through and point-in-time fundamentals.
- Longer matured live evaluation and reproducible benchmarks.
- Secure multi-user access if deployment expands.

**Closing line:** Explain the inputs, limits and reasons before acting.

**Speaker notes:** Emphasise auditable software behaviour over guaranteed investment returns. The owner places orders manually. Thank the supervisor/review panel and invite questions, with each team member answering their assigned module. Confirm the report's academic approvals/corrections/submission separately; do not invent them on the closing slide.
