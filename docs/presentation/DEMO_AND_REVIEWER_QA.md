# Demonstration, recording and reviewer Q&A

**Financial Advisor — Supervisor: Dr. Jay Prakash Maurya.** This guide is for all five members and the deck operator.

## Prepare a reproducible demo

1. Build and start the stack before the review; verify API health and all required routes.
2. Use fictional accounts and financial facts. Keep actual broker IDs, holdings, credentials and session files out of screenshots/videos/GitHub.
3. Prepare manual/CSV data rather than depending on a fresh broker login on stage. `DEMO_MODE=true` does not populate every new portfolio page.
4. Warm any model dependencies actually used. Keep optional research/forecast unavailable states visible if access is absent.
5. Rehearse a profile with an emergency-reserve shortfall, then explain its cautious plan. Do not change real personal profile data just to obtain a dramatic screenshot.
6. Prepare a two-minute screen recording and local image copies. SVG architecture diagrams are explanatory assets, not substitutes for screenshots of execution.

## Two-minute demo storyboard

| Time | Screen / action | Narrator | Explain |
|---|---|---|---|
| 0:00–0:15 | Landing → Overview/navigation | 25BCE10139 | Read-only scope and connected modules |
| 0:15–0:40 | Holdings: prepared source account/import/twin | 25BCE10400 | Account separation, completeness, state/valuation dates |
| 0:40–1:05 | Financial profile → Goals/Risk | 25BCE11274 | Four-month reserve versus six-month target; constraints and covered risk |
| 1:05–1:30 | Market/rank → Plan new investment | 25BCE10458 | Quality/components, gated plan, costs and leftover cash |
| 1:30–1:55 | Compare a change → evidence/thesis or freshness | 25BCE10340 | Same baseline, tradeoffs, reasons and evidence gaps |
| 1:55–2:00 | Return to Overview | All | Owner reviews; no orders executed |

Use the exact rehearsed output. If insufficient history prevents a numerical risk result, explain why that is correct. If the profile blocks added risk, show the block; do not claim a plan executed.

## Fictional input/output examples

### Capacity

```text
Income: ₹60,000/month
Essential expenses: ₹20,000/month
Known debt payment: ₹5,000/month
Emergency reserve: ₹1,00,000
Reserve target: 6 months
```

Expected arithmetic: ₹25,000 outgo; four reserve months; ₹1,50,000 reserve target; ₹50,000 shortfall. Aggressive tolerance does not remove the reserve constraint. Capture actual rendered status from the current build rather than assuming wording.

### Purchase accounting

```text
Budget: ₹10,000
Price: ₹500/unit
Illustrative friction: 0.3%
Lot size: 1
```

Expected arithmetic under the stated illustration: 19 units, ₹9,500 trade, ₹28.50 friction, ₹471.50 left. The full application may reject a leg for other gates/minimums; this standalone calculation does not assert an actual eligible stock plan.

### Comparison

Freeze one baseline and equal cash flows. Show one actual comparison result. If a proposal lowers concentration but reduces cash cover, describe the tradeoff. Do not label a hypothetical proposal as a completed trade or measured return.

## CSV preparation

Ready-to-use [fictional input files](demo-inputs/README.md) include a validated holdings CSV, an intentionally invalid date example and a schema-valid financial facts JSON. Their values are fabricated; enter the specified liability separately for the four-month reserve example.

Current import header:

```csv
asset_type,isin,symbol,description,units,value,valuation_date,cost_basis,locked,ownership
```

Confirm accepted asset types/ownership values and required fields in [import_rows.py](../../backend/app/portfolio_intelligence/sources/import_rows.py) and the current UI before constructing the rehearsal batch. Use preview to validate rows; a valid identifier should come from the catalogue rather than an invented ISIN. Use a fresh fictional account so rehearsal does not replace a personal account's snapshot.

## Capture snapshots and video

Capture these real application views after rehearsal:

| Suggested local filename | Required content | PPT use |
|---|---|---|
| `01-overview.png` | Navigation and dated overview | Slide 24 |
| `02-holdings-twin.png` | Fictional account, positions and twin readiness | Slide 24 |
| `03-profile-risk.png` | Fictional capacity/reserve or covered risk | Slide 24 |
| `04-allocation.png` | Actual plan/status/components and leftover cash | Slide 24 |
| `05-comparison-evidence.png` | Actual comparison or evidence/freshness result | Slide 24 |
| `financial-advisor-demo.mp4` | Rehearsed two-minute walkthrough | Slide 23 |

Store captures locally in `docs/presentation/assets/captures/` only after checking they contain fictional information. A Markdown document does not embed a working video automatically into a generated PPT: attach the MP4 in the slide tool or add a tested local/accessible link. Do not ask the slide AI to invent application screenshots or a demo recording.

The documentation pass does not claim these captures already exist. The pack includes diagrams and exact capture instructions; the team must attach the actual recording/screenshots before final export.

## Presentation fallback

If internet/broker/model access fails, play the prepared recording and show actual saved screenshots. Explain the unavailable integration and continue with manual input, constraints and source-code evidence. Do not display a fabricated “successful” screen. Keep a copy of the deck/report/video on the presentation laptop rather than requiring a cloud login on stage.

## Common reviewer questions

| Question | Answer |
|---|---|
| What is the problem statement? | Fragmented data and isolated analysis make portfolio-level suitability hard to assess. |
| Why not just use a chatbot? | Our core financial logic is deterministic, state-bound and evidence-traceable; free-form text alone cannot ensure that. |
| What is novel? | Integration of account completeness, versioned state, capacity/goal constraints, common-baseline accounting and guarded research. |
| Where is machine learning? | Kronos, FinBERT, configured LLM assistance and experimental PPO; not every formula is ML. |
| What is the dataset? | Source observations, catalogue/candles/fundamentals/NAVs and source documents; no single newly labelled training dataset is claimed. |
| Did you train the pretrained models? | No. We integrate pretrained models; PPO is a separate lightly trained experiment. |
| Can it buy/sell automatically? | No. Read-only analysis; the owner executes manually. |
| Does 80 score mean 80% accuracy? | No. It is a policy rank/score, not a profit probability. |
| What if holdings/prices are incomplete? | Unknowns, freshness and coverage remain visible; some calculations/plans refuse a result. |
| Can a user override capacity with aggressive answers? | No. Tolerance and capacity are separate and hard gates remain. |
| Is the backtest unbiased? | Not universally; today's universe, missing historical fundamentals and earlier price-only/cost assumptions are explicit limitations. |
| Are all tests database-realistic? | Most use SQLite/mock transports; additional PostgreSQL tests need a disposable configured database. |
| How do you verify AI facts? | Source passage links, supported fact IDs, contradiction checks and deterministic condition aggregation. |
| What does no evidence mean? | Available evidence does not substantiate the claim; it is not automatically proof the claim is false. |
| Is this ready for public deployment? | No. Fixed-user local prototype; secure multi-user design is future work. |

## Mandatory academic follow-through

The supplied requirements say report approval by the guide is mandatory; Review II corrections must be incorporated; report softcopy is due two days before final review. [PROJECT_REPORT.md](../../PROJECT_REPORT.md) records those statuses without inventing approval or submission. Ask the guide about any deadline already passed, and keep correction evidence before the final review.
