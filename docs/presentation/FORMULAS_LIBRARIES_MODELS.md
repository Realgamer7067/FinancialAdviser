# Formulas, libraries and models

This is the shared technical reference for all five members. Equations below describe repository behaviour or explicitly labelled conceptual background. Financial examples are fictional. Policy constants are educational choices rather than reviewed financial recommendations.

## 1. Valuation and exposure — part 2, then part 3

For a quantity-based holding with a valid price:

```text
V_i = units_i × price_i
V_known = sum of known holding values
w_i = V_i / V_known
covered_fraction = covered known value / V_known
```

Unknown values are excluded and counted, not substituted with zero. The twin can use broker-reported or user-entered values with their dates; it does not promise to reprice every asset live.

Example: two known values of ₹60,000 and ₹40,000 have weights 60% and 40%. An additional asset with no value means those are weights over ₹1,00,000 known value, not necessarily all wealth.

Source: [state/build.py](../../backend/app/portfolio_intelligence/state/build.py), [risk/exposure.py](../../backend/app/portfolio_intelligence/risk/exposure.py).

Economic state hash: SHA-256 of canonically ordered normalised economics and input revision references. It is a change/identity marker, not encryption and not a guarantee that source data is correct. For unit-based holdings, quote changes are valuation changes; value-only economics include declared value.

## 2. Concentration — part 3

```text
HHI = sum(w_i²)
effective_positions = 1 / HHI
```

Weights are those of the issuer subset used by the implementation. Do not silently interpret its issuer-subset denominator as all wealth. Equal weights across four represented issuers give HHI 0.25 and effective positions 4; one issuer alone gives 1.

Source: [risk/exposure.py](../../backend/app/portfolio_intelligence/risk/exposure.py).

## 3. Capacity and tolerance — part 3

```text
known_debt_payments = sum of known monthly liability payments
monthly_outgo = essential_expenses + known_debt_payments
reserve_months = emergency_reserve / monthly_outgo
reserve_target = target_months × monthly_outgo
computed_surplus = monthly_income - monthly_outgo
debt_service_ratio = known_debt_payments / monthly_income
tolerance_score = round(mean of three behavioural answer point values)
```

Tolerance bands: below 34 conservative; 34–66 moderate; 67–100 aggressive. Missing answers produce unknown tolerance. The user-stated investable surplus is stored separately, not silently replaced by computed surplus. If some liability payments are unknown, the capacity result marks debt payments incomplete; known-payment arithmetic is partial rather than proof of a complete debt burden.

Example: ₹60,000 income, ₹20,000 expenses, ₹5,000 known debt payments and ₹1,00,000 reserve give ₹25,000 outgo, four reserve months, ₹35,000 computed surplus and 8.33% debt-service ratio. A six-month target is ₹1,50,000, leaving a ₹50,000 reserve shortfall.

Source: [personal/facts.py](../../backend/app/portfolio_intelligence/personal/facts.py), [personal/constraints.py](../../backend/app/portfolio_intelligence/personal/constraints.py).

## 4. Goal and SIP projection — part 3

For effective annual assumption R, monthly rate r, starting amount P, end-of-month contribution C and n months:

```text
r = (1 + R)^(1/12) - 1
B_t = B_(t-1) × (1 + r) + C
FV = P × (1 + r)^n + C × ((1 + r)^n - 1) / r
```

At r = 0: FV = P + nC. For a positive-rate target T:

```text
required_C = max(0, (T - P × (1+r)^n) × r / ((1+r)^n - 1))
```

Today-money targets use inflation to convert the target to the future nominal basis. The cash-flow engine supports explicit rate basis/timing; the current goal path uses effective annual, end-of-month contributions. Its Decimal ledger and rounding are authoritative, not a floating-point textbook shortcut.

Current low/base/high assumptions: 4%, 8%, 11%. Active, already-started contributions count; proposed commitments and step-ups are excluded in this path. Fees and taxes are excluded from these goal illustrations. Required annual return is found by a bounded numerical search. An unfunded goal does not grant permission for more risk.

Source: [goals/projection.py](../../backend/app/portfolio_intelligence/goals/projection.py), [cash_flow_engine.py](../../backend/app/services/cash_flow_engine.py).

## 5. Returns, volatility and drawdown — parts 3 and 4

```text
r_t = P_t / P_(t-1) - 1
r_portfolio,t = sum(current_static_weight_i × r_i,t)
sample_variance = sum((r_t - mean(r))²) / (N - 1)
annualised_volatility = sqrt(sample_variance) × sqrt(252)
wealth_t = wealth_(t-1) × (1 + r_t)
drawdown_t = wealth_t / peak_wealth_so_far - 1
max_drawdown = minimum(drawdown_t)
```

252 is the annual trading-session convention. Portfolio risk requires at least **252 aligned daily returns** and **80% known-value coverage**. It describes the covered historical window with today's weights, not the owner's actual historical trading performance.

Example: a path that peaks at 120 then falls to 90 has drawdown 90/120−1 = −25%. It is different from volatility: path loss and return variability answer different questions.

Source: [risk/volatility.py](../../backend/app/portfolio_intelligence/risk/volatility.py).

## 6. Stress illustrations — part 3

```text
position_change_i = round_to_paisa(V_i × covered_shock_i)
modeled_change = sum(position_change_i)
post_shock_covered_value = modeled_value + modeled_change
```

A supported −20% shock on ₹1,00,000 of covered value gives −₹20,000. Unknown sensitivity is reported as unmodelled value. Broad-market and sector scenarios are separate, not stacked. Interest-rate shocks without duration information are explicitly unsupported.

Source: [risk/stress.py](../../backend/app/portfolio_intelligence/risk/stress.py).

## 7. Total returns and market descriptors — part 4

```text
TR_t = TR_(t-1) × (adjusted_close_t + scaled_dividend_t) / adjusted_close_(t-1)
SMA200_t = mean of the latest 200 closes
sma200_ratio = close_t / SMA200_t - 1
momentum_12_1 = level_(t-21) / level_(t-252) - 1
momentum_6_1 = level_(t-21) / level_(t-126) - 1
liquidity_value = median(close × volume over latest 20 sessions)
vol_ratio = volatility_60 / volatility_252
current_drawdown = close_t / highest_close_in_latest_252_sessions - 1
```

The momentum skip avoids using the latest month's return in the lookback; it is still past return. Current ranking momentum uses a prepared total-return level where dividends are applicable. The generic signal module also stores price-based descriptors. Distinguish their bases when discussing results.

Dividends are scaled for later split/bonus events. Unparseable dividends or uncertain scaling are skipped with counts. This prevents silently double-counting corporate-action adjustments.

Signal quality needs 253 closes for its full one-year measures, adequate freshness and no unreliable corporate-action window. The median traded-value threshold is ₹1 crore/day, an unreviewed policy. Trend and momentum share one descriptive family; liquidity is a gate. A 6–1 signal can be computed with a shorter window, but the ranking momentum helper intentionally requires the full 253-session history.

Source: [market/total_return.py](../../backend/app/portfolio_intelligence/market/total_return.py), [signals/compute.py](../../backend/app/portfolio_intelligence/signals/compute.py), [scoring/momentum.py](../../backend/app/portfolio_intelligence/scoring/momentum.py).

## 8. Current stock rank — part 4

Core inputs include:

```text
earnings_yield = EPS / price
book_yield = 1 / price_to_book
EBITDA_yield = 1 / EV_to_EBITDA
FCF_yield = free_cash_flow / trusted_market_cap
ROE_derived = PAT × price_to_book / trusted_market_cap
payout = trailing_dividend_per_share / EPS, capped at 1 when valid
cash_profitability = operating_cash_flow / average_total_assets
accruals = (annual_net_income - operating_cash_flow) / average_total_assets
```

Negative earnings yield ranks poorly rather than being called cheap. Invalid denominators produce no value and a reason. Financial businesses omit inappropriate debt/enterprise-value measures. Higher accruals and debt score in the weaker direction.

For comparable peers, after 5th/95th percentile winsorisation and direction alignment:

```text
midrank_percentile = 100 × (count_below + 0.5 × (count_equal - 1)) / (N - 1)
sector_blend = n/(n+4) × sector_percentile + 4/(n+4) × group_percentile
component_score = mean of usable active measure percentiles
composite = (wV × Value + wQ × Quality + wM × Momentum) / (wV+wQ+wM)
```

Sector blending uses group rank directly when sector peers are inadequate. Default weights are equal. Minimum measures: value 2, quality 3, momentum 1, with at least 50% component coverage; 12–1 must be present for momentum. At least eight values activate a measure in a comparison group; percentiles need at least three peers. Every component must be usable or the stock is not ranked. Candidate floor: 60. Current method: `stock-rank-p3-unvalidated`.

Example usable component scores 70, 80 and 60 produce composite 70. This is a comparative policy screen, not a 70% profit probability.

Source: [scoring/ranking.py](../../backend/app/portfolio_intelligence/scoring/ranking.py).

## 9. Allocation and accounting — parts 4 and 5

```text
target_value_bucket = target_weight_bucket × applicable_post_contribution_base
gap_bucket = max(target_value_bucket - existing_bucket_value, 0)
units = floor(budget / (price × (1+fee)) / lot_size) × lot_size
trade_value = round_to_paisa(units × price)
debit = trade_value + round_to_paisa(trade_value × fee)
assets_after + friction = assets_before + contribution - withdrawal
```

Short-horizon claims adjust the applicable target calculation; it is not simply all wealth multiplied by a tolerance weight. Monetary calculations use Decimal. Leftovers remain explicit. Current illustrative fee is 0.3%; real tax, settlement and provider charges may differ.

Current satellite policy: at most five stocks, at most two per sector, 3% post-plan portfolio cap per stock, at least three eligible names, ₹5,000 minimum satellite leg. Buy-only allocation may consolidate small amounts into a core choice and never forces an ineligible stock.

Source: [allocation/policy.py](../../backend/app/portfolio_intelligence/allocation/policy.py), [allocation/plan.py](../../backend/app/portfolio_intelligence/allocation/plan.py), [decisions/engine.py](../../backend/app/portfolio_intelligence/decisions/engine.py).

## 10. Covariance and earlier optimisation — parts 3 and 5

```text
shrunk_covariance = (1 - delta) × sample_covariance + delta × target_covariance
portfolio_volatility = sqrt(w_transpose × annualised_covariance × w)
```

The current shrinkage helper uses up to 252 aligned return sessions, requires at least 126 returns and at least two proposed stocks, describes an equal-weight proposed sleeve, and warns for correlation above 0.7. It does not select weights.

Earlier mean-variance background:

```text
expected_portfolio_return = w_transpose × mu
portfolio_variance = w_transpose × covariance × w
estimated_Sharpe = (expected_return - risk_free_rate) / volatility
```

The original optimiser uses constrained PyPortfolioOpt routines and labelled fallbacks. These equations explain that older method, not a claim the current allocation policy is an optimised strategy.

Source: [risk/shrinkage.py](../../backend/app/portfolio_intelligence/risk/shrinkage.py), [portfolio_mvo.py](../../backend/app/models_iface/portfolio_mvo.py).

## 11. AI outputs — part 5

**Kronos:** each sample's terminal return is `(sample_close - latest_close) / latest_close`; predicted return is the median; p10/p90 describe sampled dispersion; direction agreement is the fraction matching the median sign. ±1% is the wrapper's neutral band. Eight independent seeded draws are the default. Labels `7d`, `30d`, `90d` map to **7/30/90 bars**, not automatically calendar days. The nightly path has stricter history requirements than the wrapper's 30-bar minimum.

**FinBERT:** the adapter takes the top positive/neutral/negative label probability. Signed sentiment is +p for positive, −p for negative and 0 for neutral. That is a text-classification output, not expected market return.

**LLMs:** validated structured outputs, optional evidence synthesis and thesis condition mapping. The model never decides whether an unsupported fact becomes verified or whether a new cash balance exists.

**PPO:** experimental reinforcement-learning allocation. The repository uses Stable-Baselines3/Gymnasium and a local checkpoint. Treat this as exploratory, not a validated trading agent.

Sources: [kronos.py](../../backend/app/models_iface/kronos.py), [finbert.py](../../backend/app/models_iface/finbert.py), [llm.py](../../backend/app/models_iface/llm.py), [model_adapter.py](../../backend/app/models_iface/model_adapter.py), [portfolio_finrl.py](../../backend/app/models_iface/portfolio_finrl.py).

## 12. Evidence and testing mathematics — part 5

```text
rank_IC_per_date = correlation(rank(feature), rank(later_outcome))
mean_IC = mean(IC across eligible dates)
standard_error = sample_sd(IC) / sqrt(number_of_dates)
Bonferroni_alpha = 0.05 / number_of_registered_claims
```

The ledger handles ties with ranked series. Each date is a unit of evidence, not each stock row treated as independent. Bootstrap intervals and minimum detectable effect help distinguish too little information from measured lack of evidence. The four-claim historical registry uses alpha 0.0125 per claim; live registries are separate and their family size must be read from their version.

Historical study-v1 uses price outcomes; study-v2 uses total-return outcomes. Biased historical evidence does not automatically earn a decision weight. Live claims need matured forward windows and adequate dates; stored plan outcome accounting is not automatically skill evidence.

Source: [ledger/stats.py](../../backend/app/portfolio_intelligence/ledger/stats.py), [ledger/registry.py](../../backend/app/portfolio_intelligence/ledger/registry.py).

## 13. Earlier recommendation score — explain only when asked

```text
legacy_score = 0.25×fundamental + 0.20×kronos + 0.15×news
             + 0.15×technical + 0.15×portfolio + 0.10×risk
```

All subscores are on the legacy 0–100 scale. Score thresholds are 80/65/50; confidence/risk gates can still force no recommendation. This path is off by default and is not the current value/quality/momentum rank.

Source: [scoring.yaml](../../config/scoring.yaml), [legacy final_score.py](../../backend/app/scoring/final_score.py).

## 14. Backend dependency inventory

Versions below are the repository's exact pins, not claims about latest releases.

| Libraries | Version | Role |
|---|---|---|
| fastapi / uvicorn[standard] | 0.115.0 / 0.30.6 | HTTP API/server |
| sqlalchemy / alembic | 2.0.35 / 1.13.2 | ORM and schema migration |
| asyncpg / psycopg2-binary | 0.29.0 / 2.9.9 | Async/sync PostgreSQL drivers |
| pydantic / pydantic-settings | 2.9.2 / 2.5.2 | Data validation and environment config |
| httpx[socks] / python-multipart | 0.27.2 / 0.0.20 | HTTP clients/proxy support and CSV upload |
| pandas / numpy | 2.2.3 / 2.0.2 | Tabular/time-series/numerical processing |
| pandas-ta-classic | 0.6.52 | Earlier technical indicator library |
| torch / transformers | 2.4.1 / 4.45.1 | CPU model inference |
| huggingface-hub / safetensors / einops | 0.25.1 / 0.6.2 / 0.8.1 | Model downloads, weights and tensor operations |
| PyPortfolioOpt | 1.6.0 | Covariance shrinkage and earlier MVO |
| openai | 1.51.0 | OpenAI-compatible client for configured providers |
| yfinance | 1.7.0 | Yahoo market/fundamental access |
| feedparser | 6.0.11 | Earlier RSS news ingestion |
| tenacity / PyYAML | 9.0.0 / 6.0.2 | Retry support and configuration loading |
| stable-baselines3 / gymnasium | 2.5.0 / 0.29.1 | Experimental PPO environment/training |
| pytest / pytest-asyncio / respx / aiosqlite | 8.3.3 / 0.24.0 / 0.21.1 / 0.20.0 | Tests and SQLite test DB |

Standard-library tools include Decimal, asyncio, hashlib, json, datetime, uuid and pathlib. Kronos itself is cloned separately because its repository is not pip-installable; the listed einops/safetensors pins are supporting dependencies.

Manifest: [requirements.txt](../../backend/requirements.txt).

## 15. Frontend dependency inventory

| Library | Manifest version/range | Role |
|---|---|---|
| next | 16.3.1 | App Router and server proxy |
| react / react-dom | 19.2.8 / 19.2.8 | Interface components/rendering |
| typescript | 5.6.3 | Static type checking |
| tailwindcss / postcss / autoprefixer | 3.4.13 / 8.5.26 / 10.4.20 | CSS tooling |
| recharts | ^2.15.4 | Charts |
| framer-motion | ^13.1.1 | Motion |
| lucide-react | ^1.33.0 | Icons |
| clsx | ^2.1.1 | Conditional class names |
| @types/node / @types/react / @types/react-dom | 20.16.11 / 19.2.2 / 19.2.1 | Type declarations |

A caret is an allowed range; installed resolution is governed by package-lock.json. Manifest: [package.json](../../frontend/package.json).

## 16. Model/config inventory

| Model/config | Repository setting | Runtime role |
|---|---|---|
| Kronos model | `NeoQuasar/Kronos-small` | CPU sampled OHLCV forecast |
| Kronos tokenizer | `NeoQuasar/Kronos-Tokenizer-base` | Market-bar tokenisation |
| FinBERT | `ProsusAI/finbert` | Legacy financial sentiment |
| Qwen | `qwen2.5-32b-instruct` default, configurable endpoint/model | Structured model assistance |
| Gemini | Configurable Flash/Flash-Lite IDs in `.env.example` | Optional research adapter |
| PPO checkpoint | `data/models/finrl_ppo_v1/` | Experimental offline-trained inference |
| PostgreSQL | 16-alpine in Compose | Persistent relational store |

Configured remote IDs are not guarantees of account access or provider availability. Confirm them in the intended environment. Source: [config.py](../../backend/app/core/config.py), [.env.example](../../.env.example), [docker-compose.yml](../../docker-compose.yml).
