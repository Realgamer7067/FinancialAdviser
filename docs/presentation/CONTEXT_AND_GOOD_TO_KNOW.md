# Context and good to know — read by all five members

## What are we building?

A private, read-only portfolio analysis system for Indian investments. It connects holdings, finances, goals, market information and research into an explainable review. It can report missing information, no material benefit or no change. The user controls all actual orders.

Official academic title: **Financial Advisor**. Supervisor: **Dr. Jay Prakash Maurya**. Product name in the UI: Portfolio Intelligence. Earlier API title: Indian AI Equity Research Platform. Repository: FinancialAdviser. These refer to the same evolving college project. `/api/v4` identifies the newer portfolio endpoints; it does not mean the frontend or every model is version four.

## The complete mental model

```text
External facts: holdings / market prices / source documents
                       +
Owner facts: income / reserve / liabilities / goals / restrictions
                       |
                       v
Normalised observations, identity and input revisions
                       |
                       v
Versioned economic state + separately dated valuation
                       |
                       v
Readiness -> constraints -> risk/descriptors -> proposals
                       |
                       v
Gates + conservation + comparison + evidence checks
                       |
                       v
Dated result with reasons and limits -> owner's manual action
```

## Current versus earlier paths

| Path | What it does | How to describe it |
|---|---|---|
| Current portfolio engine | Accounts, twin, capacity, risk, plans, decisions, theses and ledger | Main presentation and UI |
| Original recommendation pipeline | Screening → Kronos/news/fundamentals/technicals → optimiser/council → deterministic score/risk gate | Retained, disabled by default |
| Original calculator | Stateless SIP and goal calculations | Still available at `/planning` |
| Earlier holdings-aware planner | V3 allocation/cash-flow services | Historical API plus reusable cash-flow engine |
| Current rank | Value/quality/momentum percentile components | Policy rank, not verified prediction |
| Older checklist | Valuation/quality/balance/risk screen | Separate remaining mechanism/endpoint |

Do not apply the legacy score weights from `config/scoring.yaml` to the current stock rank. Do not say FinBERT sentiment drives every new plan. Do not call current Ledoit–Wolf covariance a mean-variance weight optimiser.

## Words everyone should understand

| Term | Meaning in this project |
|---|---|
| Holdings | Assets the owner currently reports owning |
| Account | A distinct broker/manual source whose imports stay separate |
| ISIN | Instrument identifier validated before confident matching |
| Observation | A source report with a date, identity, quantities and optional value |
| Complete import | A batch accepted as complete for that source; not proof every account is included |
| Portfolio twin | Versioned computational representation of holdings and bound personal inputs |
| Economic state | Ownership/quantity and personal-input structure rather than a quote timestamp |
| Valuation snapshot | Dated values selected under a declared valuation policy |
| Readiness | Separate account, holdings, valuation, identity and suitability statuses |
| Provenance | Where information came from and when it was observed/retrieved |
| Tolerance | Behavioural willingness to bear losses |
| Capacity | Financial facts limiting the ability to bear losses |
| Constraint | A rule restricting admissible changes or which money can be invested |
| Goal claim | Existing assets reserved for a goal; different from a recurring contribution |
| SIP/commitment | A user-reported recurring contribution plan |
| OHLCV | Open, high, low, close and volume for a price bar |
| NAV / TER | Fund net asset value / annual total expense ratio |
| Momentum | Past return over a stated window, not future return |
| Drawdown | Fall from an earlier peak of the observed price/return path |
| Liquidity | Ability to trade without excessive price impact; screened through traded value |
| HOLD | Common comparison baseline, with new contributions retained as cash |
| Friction | Declared illustrative trading cost/slippage assumption |
| Thesis | Owner-confirmed conditions explaining why they hold an investment |
| Lineage | Grouping of source provenance so copied/repeated links are not independent evidence |
| Rank IC | Correlation of feature ranks and later outcome ranks across securities on one date |
| Model evidence ledger | Frozen claims, dated inputs, matured outcomes and statistical evidence verdicts |

## Why unknown stays unknown

An asset with no value is not worth zero. A missing EPS is not zero earnings. An unreadable broker response is not an empty account. An expired session is not a successfully refreshed portfolio. Every owner must be able to explain one of these examples.

Calculations operate over available inputs and disclose their coverage. A 90% concentration figure among known holdings does not automatically describe unvalued assets. Historical risk refuses a numerical result if its required window/coverage is insufficient.

## State, data and runtime

The latest complete import from each included account contributes to the twin. Units-based prices change valuations separately from economics; value-only holdings behave differently because their value is their declared economic quantity. Hashes and revision references bind results to inputs, while timestamps describe freshness.

Next.js calls a relative API client; its server proxy forwards to FastAPI. The API writes jobs to PostgreSQL. The worker claims with a lease and fenced attempt token, then records progress and outcomes. The API scheduler queues after-close work. There is no Redis/Celery service.

Current tables include source accounts/imports/observations, portfolio states/positions/valuations, personal/goal revisions, jobs, security candles/signals/forecasts/scores, allocation plans, decisions, research facts and ledger rows. See [the architecture map](../../ARCHITECTURE.md).

## Rules and AI have different jobs

Deterministic Python computes money, exposure, tolerance, capacity, projections, ranking and gates. NumPy/pandas process time series. PyPortfolioOpt provides covariance methods and the earlier optimiser.

Kronos forecasts from candlesticks; FinBERT labels financial text sentiment; configured Qwen/Gemini adapters help structure research or earlier council responses. Models are not authorised to invent account balances, final financial scores or verified evidence. Experimental PPO does not establish a reliable investment strategy.

Current forecast signal-family vote is zero until evidence supports review. The separate current stock rank includes momentum with an explicit unvalidated policy weight. Those statements are compatible because a displayed policy ranking and an empirically earned signal weight are different mechanisms.

## Real-time usage: precise language

A connected session supports market-hour quote refreshes on watchlist-related surfaces; the existing setup guide describes a 30-second watchlist refresh. Historical signals, catalogue refreshes, ranking jobs and reviews primarily follow after-close/background work. Research/thesis assessment is on demand. Therefore say **live-data-assisted and scheduled analysis**, not tick-level continuous trading or fully real-time inference.

Broker sessions expire and may need daily reconnection. Quote retrieval time and exchange timestamp are not always interchangeable. A stale screen should disclose freshness rather than imply a current price.

## What the demonstration proves

Show a coherent software workflow: input → validated state → constraints/risk → plan or comparison → reasons. A no-change or insufficient-data answer can be a successful demonstration if the input actually requires it.

A test suite validates code behaviour under test conditions. Historical backtests evaluate methods under stated biases. A live study needs matured outcomes. None of those automatically proves future investment profitability.

## Things we must not claim

- Training Kronos, FinBERT or Qwen from scratch.
- Guaranteed returns, a validated profit probability or a calibrated forecast band without evidence.
- Every account, fund underlying, tax lot or liability is known.
- Every screen is populated offline by `DEMO_MODE=true`.
- A locally seeded user is a full public login/authentication system.
- A paper's benchmark is the result obtained by this college project.
- Guide approval, report submission, Review II incorporation, video capture or browser verification that has not happened.

## Shared preparation checklist

Read [the formula/model reference](FORMULAS_LIBRARIES_MODELS.md), [literature review](LITERATURE_REVIEW.md), [demo/Q&A guide](DEMO_AND_REVIEWER_QA.md) and [validation notes](VALIDATION.md). Each person should explain the overall one-minute introduction, their own input/output, one equation, one source file, one failure case and one honest limit. Rehearse handoffs in registration-number order.
