# UI/UX Audit & Redesign Plan

**Project:** Indian AI Equity Research Platform / Portfolio Intelligence Engine  
**Date:** 2 October 2026  
**Method:** Read-only repository review. Recommendations are not implemented.

## TOP 10 UX PROBLEMS

### 1. Two product generations compete for the user's mental model

**Problem:** A portfolio review product and an earlier candidate stock research product share one navigation hierarchy.

**Where it appears:** frontend/src/components/Sidebar.tsx:34 exposes 15 current links and eight “Earlier tools.” Overview/Dashboard, Invest/Portfolio, Plan/Goals and Finances/Onboarding have overlapping labels but different data.

**Why it hurts users:** Beginners must understand development history before choosing a workflow. “Old” describes a version, not a user task. Proposed allocations can be confused with owned investments.

**Severity:** Critical.

**Recommended direction:** Four primary domains—Overview, Portfolio, Planning, Explore—with Attention and Settings as utilities. Keep earlier tools secondary and explicitly scoped; consolidate only after checking data compatibility.

### 2. Holdings contradicts its own read-only legacy guidance

**Problem:** A section described as read-only still contains operational holding entry and import confirmation.

**Where it appears:** frontend/src/app/holdings/page.tsx:165, :216, :304; AccountsPanel presents a different current import path above it.

**Why it hurts users:** “Add a holding” saves through /api/holdings/import/confirm, while the current consolidated portfolio comes from /api/v4/state/current. A plausible successful workflow can update the wrong system.

**Severity:** Critical.

**Recommended direction:** One account-scoped current import journey. Historical snapshots offer viewing and deliberate adoption with a clear destination.

### 3. Settings edits a different profile from current reviews

**Problem:** Settings' Investor profile is the earlier onboarding profile; current tolerance/capacity use My Finances.

**Where it appears:** settings/page.tsx:22, onboarding/page.tsx:23, finances/page.tsx:84; /api/onboarding/me versus /api/v4/profile.

**Why it hurts users:** Updating “my profile” appears to configure current analysis but does not establish its current facts. Earlier onboarding returns to /dashboard. The two risk assessments have different meanings.

**Severity:** Critical.

**Recommended direction:** One canonical current Financial profile. Label the earlier questionnaire historical research configuration and do not imply automatic conversion.

### 4. Expense instructions can double-count loan payments

**Problem:** The essential-expenses hint includes EMIs; capacity computation adds known liability payments to expenses.

**Where it appears:** finances/page.tsx:14; backend/app/portfolio_intelligence/personal/facts.py:148.

**Why it hurts users:** ₹30,000 of expenses including a ₹10,000 EMI, plus that recorded EMI, becomes ₹40,000 of essential outgo. Reserve coverage and surplus can be understated and proposals blocked.

**Severity:** Critical.

**Recommended direction:** Decide the expense contract before redesign. Collect living expenses excluding separately recorded payments, or explicitly reconcile an inclusive total. Show the arithmetic.

### 5. Failed retrieval can look like setup or healthy absence

**Problem:** Missing, loading, unavailable and empty states are conflated.

**Where it appears:** overview/page.tsx:50 catches failures to null/empty arrays; Finances, Risk, Simulate, TwinPanel, AngelPanel and SignalsPanel can return no content while loading.

**Why it hurts users:** Returning users may see first-time setup after an outage, or goals/history disappear without explanation. Missing evidence must not imply no risk.

**Severity:** High.

**Recommended direction:** Independent explicit loading, empty, error, partial, stale and success states. Retain dated last-known content and scoped retry.

### 6. Holdings mixes too many responsibilities

**Problem:** Consolidated holdings, observations, completeness, broker setup, account tables, creation and legacy entry share one long initial view.

**Where it appears:** holdings/page.tsx and components/holdings/{TwinPanel,SuggestionsPanel,AccountsPanel,AngelPanel}.tsx.

**Why it hurts users:** Inspecting owned assets requires navigating configuration and system concepts. Positions repeat in consolidated and account tables.

**Severity:** High.

**Recommended direction:** Holdings collection first; Accounts secondary collection; account detail for imports/sync; observations contextual to assets or review.

### 7. Goals separate outcomes from management

**Problem:** All projections render before separate goal allocation cards, then creation and contribution management.

**Where it appears:** plan/page.tsx:164, :253, :269.

**Why it hurts users:** Repeated names must be matched across distant sections. Every goal exposes funding entry before editing intent.

**Severity:** High.

**Recommended direction:** Goal rows combining target/date/funding/outlook; goal detail for scenarios, set-aside changes and contributions.

### 8. Financial edits have unreliable task boundaries

**Problem:** Loan/restriction actions reload and repopulate the financial form; profile save does not refresh separately loaded constraints.

**Where it appears:** finances/page.tsx:68, :84, :122, :147.

**Why it hurts users:** Adding a loan can overwrite unsaved income edits. After saving, profile capacity and constraint summaries can reflect different retrieval times.

**Severity:** High.

**Recommended direction:** Independent edit scopes, draft protection, conflict reconciliation and summaries tied to accepted inputs.

### 9. Exploration loses selected context

**Problem:** Watchlist “Thesis” opens a generic page; Market “Watch” picks the first list; security detail expands in a table without a durable detail URL.

**Where it appears:** watchlist/page.tsx:78; market/page.tsx:170 and :91; components/market/SecurityDetail.tsx.

**Why it hurts users:** Users reselect securities, find unexpected list placement and lose state on navigation. Different identifiers/coverage scopes become unexplained limitations.

**Severity:** High.

**Recommended direction:** Shared security detail, chosen-list confirmation, prefilled rationale creation, persistent filters and origin-aware return.

### 10. Accessibility and mobile task structure are incomplete

**Problem:** Bespoke tabs lack full keyboard behavior; mobile drawer lacks explicit focus management; compact controls and wide tables persist on narrow screens.

**Where it appears:** Sidebar.tsx:139; Market/Inbox/Watchlist tablists; Compare/Goals forms; ui/ProgressBar.tsx; market/page.tsx:284.

**Why it hurts users:** Keyboard interaction is inconsistent; some fields lack names; mobile users horizontally scan data while secondary controls consume vertical space.

**Severity:** High.

**Recommended direction:** Accessible navigation/field contracts, focused mobile details, column priorities, and manual keyboard/zoom/device verification.

## TOP 10 HIGHEST-IMPACT IMPROVEMENTS

1. Establish one current flow: owned portfolio → personal context/goals → review → optional simulation; keep historical research clearly secondary.
2. Replace 23 visible navigation destinations with four primary domains and contextual secondary navigation.
3. Make current holdings entry account-scoped: choose source → enter/upload → review replacement → confirm → updated account/portfolio.
4. Make Financial profile the canonical current configuration destination, including links from Settings and missing-input notices.
5. Resolve EMI interpretation and protect financial drafts; show exactly what saved and which summaries updated.
6. Make Overview attention-first: conclusion, actionable exceptions, known value/coverage, goals; readiness/audit one level deeper.
7. Combine each goal's outlook and funding; move detailed scenarios and funding edits into goal detail.
8. Standardize loading/error/empty/stale/job states and mark outputs outdated after input changes.
9. Preserve security context across Market, Watchlists, Research, Rationales and simulation; allow chosen watchlist placement.
10. Define a small consistent interaction system—headers, actions, fields, statuses, tables, focus and mobile priorities—before visual polish.

## 1. Executive Summary

The primary problem is structural. The repository evolved from beginner equity research into a private portfolio intelligence tool, but both generations remain visible. Users encounter two profiles, two goal systems, competing definitions of portfolio, several comparison tools and controls expressed through snapshots, claims, revisions and pipeline stages.

The newer product has valuable foundations: dated evidence, explicit unknowns, legitimate no-action outcomes, goals backed by holdings and simulations that never execute trades. Simplification should make those safeguards understandable at the decision point.

The recommended architecture groups understanding the present, reviewing assets, planning finances and investigating investments. Attention remains cross-product. Historical tools, source operation and technical evidence become secondary. Fixing data meanings and edit boundaries must precede cosmetic redesign.

### Scope and evidence limits

- Inspected all **27 user-facing page routes**, global layout/navigation, holdings/market screensets, shared UI primitives, chart implementations, state hooks, API client/proxy and relevant backend contracts.
- Read README.md, ARCHITECTURE.md, repository frontend instructions, portfolio intelligence intent documents and configuration. Current implementation is authoritative for observed behavior; planning documents can lag.
- **Source-based audit:** no app server, browser rendering, screenshot, database query, form submission, dependency installation or app mutation. No measured performance, contrast pass or screen-reader result is claimed.
- **Confirmed** means directly visible in source. **Inferred** means likely user consequence. **Manual check** requires runtime/rendered verification. Frequency and cognitive-load ratings are hypotheses, not analytics.
- Accessibility review used the current [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md) as a check reference; findings are tied to repository evidence.
- Paths below are repository-relative; frontend route files are under frontend/src/app unless otherwise qualified. Line numbers are anchors. Proposed destinations are conceptual, not implemented routes.
- The working tree was already substantially modified/untracked before inspection. Those files are included in the current product and preserved.

### Severity

Critical: wrong data system, fundamental product misunderstanding or materially misleading financial input. High: core/frequent task blocked, obscured or unsafe to edit. Medium: repeated friction/discoverability/hierarchy problem. Low: limited secondary polish. Severity is user impact, not implementation difficulty.

## 2. Product Understanding

### Product and audiences

This is a local single-user India-focused investment research and portfolio review app. Earlier workflows screen Nifty50 stocks, use fundamentals/technicals/forecast/news/council scoring and illustrate candidate allocations. Current workflows import existing accounts, build dated state/valuation, collect personal circumstances, assess exposure/liquidity, project goals, evaluate alternatives against doing nothing and publish reviews/attention items.

README and root metadata emphasize beginner equities. docs/PORTFOLIO-INTELLIGENCE-ENGINE-PLAN.md describes private portfolio review. Current Market includes stocks, ETFs and funds; manual holdings include deposits, gold, cash and other assets. Landing's equity/indices-only claim no longer describes the whole implemented scope.

Likely users: individual owner with beginner/intermediate investing knowledge; experienced owner using scenarios/watchlists; operator configuring sources or evaluating model evidence. Only one actual application identity exists. No frontend authentication, account switching, collaboration or enforced roles. backend/app/core/single_user.py and main.py:41 confirm fixed-user mode. Operator is a task distinction, not a permission role.

### Domains/entities

| Domain | Entities | User goal | Internal language to demote |
|---|---|---|---|
| Investments | Source account, import, position, state, valuation | What I own, where, value/completeness | State IDs, revisions, publication, row ordinal |
| Personal context | Financial profile, liability, preference | Affordability, reserve, debt, restrictions | Expected version, capacity ceilings |
| Planning | Goal, allocation claim, commitment, projection | Target/date, set-aside money, recurring funding | Chain IDs, claims, budget interpretation |
| Review | Outcome, evaluation, job, timeline | Need attention? Why? Next step? | HOLD/REVIEW enums, gates, policies |
| Attention | Issue, event, snooze/dismiss/resolved states | Follow-up and changes | Event kinds, reopen counts |
| Exploration | Security/broker instrument, quote/NAV, history, signals | Find, understand and watch investments | Instrument master, adjustment audit |
| Research memory | Session/report, thesis/conditions/assessment | Reasons, supporting/opposing facts | Branches, lineages, synthesis states |
| Method validation | Study, claim, live ledger | How much trust is warranted | IC, detector thresholds, registry hashes |

### Boundaries

No trading execution. Angel login is operator CLI only; connections API has no browser login endpoint. Manual/CSV remain accessible alternatives. Simulations are saved analyses, not published current reviews (api/v4/actions.py). Allocation is buy-only with unreviewed rules. Earlier heuristic scores and current descriptive signals have different scopes.

Backend exposes saved allocation plan retrieval, state history, research session retrieval and thesis/goal/contribution updates without complete matching frontend paths. Do not create a page for every endpoint; expose useful completion/recovery. Earlier /api/plans is a distinct engine without a dedicated frontend, not the current /api/v4/allocation/plan.

## 3. Current Product Architecture

~~~text
Shared Sidebar + desktop TopBar + main content
├── /                     Landing → Get started → Overview
├── Current sidebar: 15 items
│   ├── /overview         Setup, value, review, readiness, goals, history
│   ├── /holdings         Twin, observations, accounts/import/sync, legacy entry
│   ├── /market           Stocks / ETFs / Funds; inline SecurityDetail
│   ├── /allocate         Invest; new-money proposal
│   ├── /watchlist        Lists, prices, alerts, notes, simulation links
│   ├── /scorecard        Live validation ledger and historical study
│   ├── /risk             Exposure, cash, movement, stress scenario
│   ├── /finances         Facts, tolerance, capacity, loans, restrictions
│   ├── /plan             Goals & SIPs; projections, claims, contributions
│   ├── /simulate         Compare options against doing nothing
│   ├── /actions          Review, reasoning, alternatives, audit, history
│   ├── /inbox            Open / Snoozed / Dismissed / Resolved; events
│   ├── /theses           Personal conditions and evidence assessments
│   ├── /research         Question, sources, report, branches, verification
│   └── /settings         Earlier investor profile → Onboarding
├── Earlier tools: 8 always-rendered links
│   ├── /dashboard        Earlier analysis launcher and market summary
│   ├── /recommendations  Candidate stock cards and screening funnel
│   ├── /portfolio        Hypothetical candidate allocation and sizing
│   ├── /goals            Earlier goals and legacy snapshot earmarks
│   ├── /catalogue        Product terms/support, synthetic fixtures
│   ├── /compare          Nav “Compare products”; actual stock comparison
│   ├── /planning         SIP growth and target calculators
│   └── /safer-alternatives Product education
├── Contextual/direct
│   ├── /onboarding       Earlier questionnaire → Dashboard
│   ├── /stocks/[symbol]  Earlier recommendation/evidence detail
│   └── /admin            Operator diagnostics
└── /api/[...path]         API proxy; not a user page
~~~

Screensets: AccountsPanel contains AccountCard/ImportBox and AngelPanel. Market expands SecurityDetail with PriceChart/SignalsPanel. Watchlist rows expand alerts/notes. No global search, command palette, breadcrumbs or general contextual back pattern exists. Mobile repeats all destinations in a drawer.

Relationships: Overview directs missing input to Holdings/Finances/Plan and explanation to Actions. Account imports refresh current state. Risk/simulations consume state; Goals allocate positions and count commitments. Inbox links whole pages rather than specific entities. Watchlist preserves stock through /simulate?buy=…, but not Theses. Earlier Recommendations opens stock detail; newer Market has a separate inline detail.

## 4. Primary User Journeys

Counts describe conceptual stages, excluding field entry and terminal steps; they are not measured clicks. Validate frequency through owner task observation.

### Primary

| Journey | Current flow/stages | Discovery and friction | Recovery/completion target |
|---|---|---|---|
| Establish holdings | Overview → Holdings → Create account → Import → CSV/manual → Preview → Confirm; ~7 | Setup links useful; create buried; parallel legacy entry | Source choice then scoped import; reconcile removed/changed rows; return updated account and portfolio |
| Daily check | Overview → Actions/issue → Finances/Plan/Risk/Simulate; ~2–4 | Attention framing good; readiness/value compete; issue links uneven | Conclusion first, exact fix destination, pending/current review after return |
| Inspect assets | Holdings → consolidated table/account tables | Easy label; configuration interrupts, no consolidated search | Collection/table first, filters, selected holding provenance |
| New-money proposal | Invest → amount/risk preview → Build → status/mix/purchases/checks; ~3–4 | Advanced override early; saved result inaccessible | Readiness/amount first, proposal with scope/date, saved retrieval |
| Fund a goal | Plan → bottom create → projections above → set aside → contribution; ~4–5 | Repeated goal identities and assumptions | Basic goal then detail combining outlook/funding and next adjustment |

### Secondary

| Journey | Current flow | Finding | Target |
|---|---|---|---|
| Explore/watch | Market → search/type/filter → Details/Watch → Watchlist | Implicit first list; temporary detail | Durable security, selected list and Undo |
| Compare watched stock | Watchlist → simulate?buy → amount/account/funding → compare | Prefill good; accounting decisions complex | Preserve origin/stock, derive funding summary |
| Write rationale | Watchlist Thesis → generic Theses → stock/reason/conditions → Save | Stock context lost | Contextual draft, examples, user wording preserved |
| Research | Question/source options → synchronous run → report/diagnostics | Technical setup, spinner, local result only | Simple entry, durable report, sources deeper, retained prior result |
| Handle alert | Inbox → fix page or reason/date/dismiss/snooze | Deferral forms visible per item | Resolve first, deliberate defer editor |
| Stress-test | Risk → bottom scenario → Run → ledger | Scenario buried; ledger overwhelms result | Loss/coverage first, contributions deeper |
| Compare stocks | Compare products → 3 slot pick/type → cards | Wrong label, duplicate input methods | Explore contextual comparison, aligned metric rows |
| Calculator | Planner → SIP/target inputs → result | Distinct useful independent task | Planning Calculators; illustrative assumptions explicit |

### Administrative

Broker setup: Holdings → CLI instructions → terminal auth → return → Sync → polling. This is not a browser reconnect action. Explain operator requirement and manual/CSV fallback.

Coverage confirmation: Holdings → complete/partial plus comma-separated missing categories. Ask after first account import; thereafter expose in Accounts, not as a daily full card.

Restrictions: Finances bottom Type/Value/confirm → Add. Use human sector/asset/security selectors.

Model evidence: Scorecard → statistical ledger/backtest → Run study → manually reload. Advanced method trust work, not personal performance.

Diagnostics: direct Admin; no enforced operator role. Navigation separation is not security protection.

### Backend mental model leakage

Snapshot rebuild, claims, expected versions, external cash flows, branches, instrument masters and earned weights become mandatory concepts too early. Translate to updated holdings, money set aside, newer saved data, additional cash, source collection and method evidence. Keep consequential limits—unknown tax, unmatched assets, stale reviews and unsupported analysis—explicit.

## 5. Major UX Problems

### Why clutter occurs

| Cause | Evidence | User experience | Replacement |
|---|---|---|---|
| Container overload | StockSummaryCard contains Panels which wrap Cards; council cards inside parent Card | Inset boundaries all look important | Flat metric groups/comparison rows; council disclosure |
| Card overload | Overview review/readiness/goals/history; Plan projections and separate goals | Scan containers rather than tasks | One primary summary and flat task lists |
| Border overload | Card border/shadow plus readiness/signal/preview inner borders | Warnings compete with ordinary boundaries | Space/headings internally; borders where separation matters |
| Action overload | Inbox dismiss/snooze forms per issue; set-aside form per goal | Every object becomes a control console | One next step, secondary menu/focused editor |
| Label overload | Snapshot/version/date/readiness/coverage repeated | Trust information becomes administrative reading | Compact coverage summary; details available |
| Repetition | Holdings aggregate/account tables; Plan duplicate goal names; allocation bars/donuts | Scrolling without new decisions | One default representation; second view only for distinct question |
| Early complexity | Research URL branches; Invest risk override; goal inflation/priority | Technical choices before simple intention | Intent-first, advanced on relevance |
| Equal visual weight | Same Card style for value, form, audit and history | Hard to identify primary content | Order/type/space hierarchy |
| Density and inefficient length | Market nine columns; 13-stage progress; long item cards | Cramped desktop and long mobile | Column priority, compact rows, stage summary |

Five-second test: many pages identify their name but fail to explain main content/next step. Holdings promises manual recording while showing a twin; Plan separates outcome from controls; Scorecard implies personal performance; Actions is actually a review.

One-level-above test: IDs, versions, complete readiness dimensions, lineages and statistical diagnostics can move deeper. Blockers and material missing-data caveats stay beside conclusions.

Remove test: removing terminal setup, all readiness tiles, all history and all creation forms from the initial view would not harm routine asset inspection. Demote, do not delete functionality. Removing unknown share or stale-review warnings would harm decisions and is rejected.

Competing-attention test: Holdings has large value, colored readiness, observation borders, coverage declaration, Angel warnings, account actions and legacy controls simultaneously. Value/coverage and holdings should dominate; material source failures compact; configuration contextual.

## 6. Information Architecture Audit

1. Portfolio tasks lack a parent: Holdings, Risk, Actions, Invest and Compare options consume the same current state but appear as unrelated peers.
2. Planning spans My Finances, Goals & SIPs, Goals (old), Planner and education without persistence/assumption distinctions.
3. Exploration spans Market, Watchlist, Theses, Research, Catalogue, Compare and Candidates without shared selected-security context.
4. Attention and review blur: Overview issues, Inbox tasks, Actions findings and Holdings observations differ, but navigation does not establish those roles.
5. Scorecard is primary despite being advanced model validation.
6. Settings contains the earlier profile; current profile and source configuration live elsewhere.

Preserve these distinctions:

- Owned assets versus hypothetical proposals.
- Saved goals versus independent calculators.
- Securities catalogue versus product category education/terms, especially synthetic fixtures.
- Model validation versus personal returns; do not rename Scorecard Performance without actual personal performance.
- Saved simulation versus published review.
- Dismissed issue versus resolved cause.

Missing useful access: saved plans, saved simulations, research retrieval, general goal/rationale/contribution revision and account import history. Expose these around user tasks, not as separate navigation items per backend resource.

## 7. Recommended Information Architecture

~~~text
Application
├── Overview
├── Portfolio
│   ├── Holdings
│   ├── Accounts
│   │   └── Account detail → Update/import → History/source details
│   ├── Risk & exposure → Market-fall scenarios
│   ├── Portfolio review → Current / History/detail
│   └── Plan new investment → Proposal / Saved proposals / Compare a change
├── Planning
│   ├── Goals → Goal detail: outlook, funding, contributions, assumptions
│   ├── Contributions
│   ├── Financial profile
│   │   ├── Income, spending & reserve
│   │   ├── Loans
│   │   └── Risk answers & investing preferences
│   └── Calculators
├── Explore
│   ├── Market → Shared security detail
│   ├── Watchlists
│   ├── Research → Reports/new question
│   ├── Investment rationales
│   ├── Compare securities
│   └── Learn about products
├── Attention (utility)
│   ├── Needs attention
│   ├── Snoozed / Dismissed / Resolved
│   └── Activity
└── Settings (utility)
    ├── Connections
    ├── Financial profile link (canonical destination)
    ├── About the analysis → Model evidence
    └── Earlier tools & historical data
        ├── Research runs/candidate allocations
        ├── Earlier profiles/goals/snapshots
        └── Explicit adoption where supported
Operator diagnostics: separate operator-purpose destination
~~~

Overview handles present attention. Portfolio handles owned assets and contemplated changes. Planning handles future intentions and personal financial context. Explore handles investigation without implying suitability. Attention spans domains; Settings contains source operation and method/history.

Move Risk/Actions under Portfolio and call Actions Portfolio review. Invest becomes Plan new investment; simulation remains available contextually and as secondary tool. Split Accounts from routine holdings. Combine goal projection/funding; separate cross-goal contributions. Finances becomes current profile; preserve earlier questionnaire explicitly. Group research/watch/rationales around security identity. Product learning combines related education but keeps securities and fixtures distinct. Scorecard moves to method context. Remove Earlier tools from primary exposure, preserving historical retrieval/adoption.

Do not add Transactions or personal Performance: complete purchase records and those frontend journeys are not established.

## 8. Navigation Audit

Sidebar has 23 links, a scrollable rail and always-expanded historical group. Text/icons and active visual treatment are useful. There is no parent active state for stock detail/onboarding, no aria-current and no breadcrumb. At laptop heights many links require rail scrolling. At sm the 224px rail removes substantial tablet width.

Labels mismatch: Compare products/Compare stocks, Goals & SIPs/Goals & contributions, Recommendations/Stock candidates (old), Portfolio/Candidate portfolio. TopBar repeats page name, uses h2 before h1, lacks return/breadcrumb, and is hidden on mobile.

Mobile drawer has backdrop/close/link actions but no explicit Escape, focus trap/return, initial focus, inert background or expanded trigger relationship in source.

Target: four primary links, active-section secondary links, Attention/Settings utility group. Breadcrumbs on entity/history detail; collection roots need no redundant crumb. Deep-link filters/type/watchlist/page/history selection. Back restores collection context. Use “Back to watchlist/accounts/current review” where meaningful. Mobile exposes fewer immediate choices; final drawer versus bottom navigation requires task testing.

Every major page must answer location, purpose, main information, options, next step and return. Historical output must announce date/scope before its conclusion.

## 9. Global UI/Shell Review

Persist section navigation, Attention count and Settings. Keep search/actions contextual. Global search is optional later and should find supported entities, not invent a generic command layer.

Root layout applies full sidebar to welcome and onboarding. A setup mode should orient without all destinations. Returning users need an obvious Overview entry rather than marketing content.

Shell “Cached data only — no live feed” is incomplete for Market/Watchlist, which show live/delayed/last-session Angel quotes and periodic refresh. Distinguish price timestamp, portfolio date and review date locally. Avoid implying continuous streaming or that every datum shares one freshness.

Hierarchy: page identity/purpose → main conclusion/task → main collection/form → relevant qualification → technical/history detail. Read-only or healthy pages need not force a primary button. Do not encourage trades just to satisfy a CTA rule.

| Template | Applies | Structure |
|---|---|---|
| Overview | Overview | Conclusion → exceptions → value/coverage → goals |
| Collection | Holdings, Accounts, Goals, Market, Watchlists, reports | Header/action → search/filter → rows → count/pagination/states |
| Detail | Account, goal, security, review, proposal, rationale | Identity/context → summary → task → related evidence → sources/history |
| Configuration | Financial profile, Connections | Grouped edit scopes → save/cancel → implications |
| Simulation | Compare, stress, calculators | Question → inputs → run/recalculate → dated result → assumptions |
| Evidence | Model validation | Human conclusion → limitations → expert detail → operator actions |

## 10. Page-by-Page Audit

Each entry covers purpose/user goal, order, CTA, entry/relationships, complexity, five-second test, severity and target flow. No rendered layout result is assumed.

### 10.1 Landing — /

Purpose: welcome beginners; goal: understand/start. Order: equity headline, long explanation, Get started, three feature cards, risk disclosure. Entry: root/brand; related: Overview. Primary CTA: Get started; sidebar introduces competing choices. Load: Moderate.

**High:** promise omits portfolio/funds/deposits, and “simple profile” misdescribes current setup. Full navigation precedes orientation. Link wraps Button. Five seconds identifies earlier product, not current purpose.

Target: short private portfolio-review promise → required inputs/outcome → Start financial picture → source choice. Returning owner Overview entry. Demote model list/feature cards; emphasize dated review, no execution and manual/CSV. Evidence: page.tsx, layout.tsx.

### 10.2 Overview — /overview

Purpose: owner check-in; goal: know if attention needed. Order: header, setup/value, review, five readiness tiles, goals, activity, recent reviews. Primary: See why; secondary: Inbox, Review again/fix links. Entry: nav/root; related: Actions/Holdings/Finances/Plan/Risk/Simulate. Load: High.

**High:** null/failure becomes setup; optional failures vanish. Value/readiness compete with conclusion. Setup lacks saved-progress cues; history duplicates Actions. Five seconds: good question, diluted priority.

Target: conclusion/date/validity → actionable issues → value/coverage → goals → activity link. Flow: read → exact fix → pending/current review. Demote readiness matrix, version/history. Emphasize no-action and stale-basis notice. Evidence: overview/page.tsx:50, :69, :132; useDecision.ts.

### 10.3 Holdings — /holdings

Purpose: inspect/record assets. Order: manual-copy header, twin/readiness/table, observations, accounts/coverage/Angel/import, legacy table and entry. CTAs: account create/import plus legacy Add compete; secondary: include/exclude/sync/rebuild/adopt. Entry: nav/setup/issues; related: Risk/Plan/Review. Load: Very High.

**Critical:** active legacy write contradicts read-only label. Current and source tables repeat; header does not describe account model. Five seconds cannot identify correct source of truth.

Target: value/date/coverage → holdings toolbar/table → row detail. Accounts secondary. Flow: inspect → selected account update → reconcile/confirm → dated account/portfolio. Demote old data, broad readiness/observations. Emphasize actual holdings, account attribution, exclusions and unknowns. Evidence: holdings/page.tsx:165, :216 and holdings components.

### 10.4 Account/import/Angel screenset

Purpose: trustworthy source update. Order: completeness question, connection/setup, account position tables, inline imports, bottom add-account. Primary: Preview/Confirm; secondary: inclusion/template/adoption. Entry: Holdings; related: twin/goals. Load: Very High with several accounts.

**High:** creation buried; manual six-column row; raw asset types; choosing CSV clears staged rows. No row edit beyond remove/reenter. Preview remains primary while Confirm is secondary. No explicit removed-position reconciliation. Matching errors have limited recovery. Angel initial failure invisible because status-null returns first. “Coming next” copy contradicts available AngelPanel.

Target: Accounts collection → account detail → update steps source/input/reconciliation/confirm. Show replacement consequences and goal claims. Operator connection instructions in Settings with manual alternative. Demote constant coverage and CLI panels; emphasize account scope, last successful import, partial sync and affected rows. Evidence: AccountsPanel.tsx, AngelPanel.tsx, api/v4/imports.py/connections.py.

### 10.5 Market and SecurityDetail — /market

Purpose: browse investments, not picks. Order: explanation/counts, three stock movers, type tabs, search/filters, wide table/detail, pagination/caveat. Main task: search; secondary: Details/Watch/history fetch. Entry: nav; related: Watchlist/model evidence, weak Research link. Load: Very High.

**High:** nine stock columns; stock movers remain on fund/ETF tabs. Job/catalogue counts precede task. Watch selects first list. Detail adds charts/signals/adjustment audit within horizontal table. State not durable; tab switching may leave unsupported sort value while effective backend sort differs. Initial null data has no loading row.

Target: search/type/simple filters → prioritized list → durable security detail → chosen Watch/Research/Rationale/Compare. Demote movers unless stocks/context, advanced filters/columns/jobs/audit. Emphasize identity/date/type/plan. Five seconds purpose clear, search buried. Evidence: market/page.tsx:163, :170, :284; market components.

### 10.6 Invest new money — /allocate

Purpose: buy-only rule proposal; goal: fit additional money into portfolio. Order: limitations, amount/risk override, status, mix, purchases, warnings/checks, SIP alternatives, policy JSON. Primary: Build plan; secondary: override/disclosures. Entry: nav; related: Finances/Simulate. Load: High.

**High:** advanced override early. Edits retain old output unmarked. Saved plan ID has no open/history path. Bars show target while heading implies where money would sit; current/target/proposed distinction ambiguous. “What to buy” can overshadow blocked status.

Target: current basis/readiness → amount → Generate proposal → status → projected mix/purchases → saved detail. Demote override/equations/per-leg rules; keep costs/unknowns/status/date prominent. Five seconds action clear, limits/results hierarchy complicated. Evidence: allocate/page.tsx; api/v4/allocation.py:58.

### 10.7 Watchlist — /watchlist

Purpose: monitor context/alerts; goal: notice change/investigate. Order: intro/source, list tabs, Refresh/sort/Delete, Add search, rows with actions/details, New list. Primary: Refresh currently/Create empty; secondary: add/details/simulate/thesis/remove/notes. Entry: nav/Market; related: Inbox/Simulate/Theses. Load: High.

**High:** search precedes list; persistent New list form; Delete beside Refresh. Thesis loses stock. Search errors silent and response ordering unguarded. Row/alert removal immediate; list delete confirmed. Broad detail combines many subtasks; selected list not durable.

Target: selected-list header/Add → compact monitored rows → focused alert/note/rationale. Demote list creation/deletion and all observations; emphasize triggers/ownership/date. Five seconds monitoring purpose good, next investigation crowded. Evidence: watchlist/page.tsx:78, :173, :214, :256.

### 10.8 Scorecard — /scorecard

Purpose: validate model claims; audience: advanced owner/operator. Order: method intro, earned statement, live ledger, historical caveats/statistics or Run study. Primary: Run only if absent. Entry: primary nav; related: Market/Invest. Load: Very High.

**Medium overall / High interpretation:** Scorecard sounds like personal performance. IC, intervals, detectability, hashes and accounting claims require expertise. Live retrieval error swallowed; indefinite Loading possible. Queue requires manual reload. No actual weight editor exists.

Target: About analysis → evidence maturity summary → live/historical distinction → expanded claims → operator run progress. Demote statistics/hashes; emphasize no-earned evidence, biases and non-use of signals. Five seconds title misleading. Evidence: scorecard/page.tsx, ledger API.

### 10.9 Risk — /risk

Purpose: exposure/liquidity/historical movement/scenarios. Order: dated header, mix table, concentration/company/sector, cash, movement/correlation, scenario/results/ledger. Primary: Run scenario; secondary: sparse. Entry: nav/issues/review; related: Holdings/Finances/Simulate. Load: High.

**High:** initial blank; salient concentration buried in prose. Missing-finance message lacks direct section link. Scenario buried and old result remains after selector change. Fixed-width bars strain small tables; unavailable correlation occupies equal narrative space.

Target: key observations/coverage → mix/concentration → cash → optional movement → scenario summary/detail. Demote exhaustive lists/correlation; emphasize biggest exposure, unknown share, cash months, modeled coverage. Five seconds title clear, major finding unclear. Evidence: risk/page.tsx.

### 10.10 My Finances — /finances

Purpose: confirmed facts/restrictions; goal: accurate context/understand consequences. Order: ten context/money fields, three tolerance questions, Save, raw capacity, ceilings, loans, restrictions. Primary: Save; secondary: loan/restriction changes. Entry: nav/setup/issues; related: Plan/Risk/Invest. Load: Very High.

**Critical expense contract; High edits:** double-count EMI; unrelated reload replaces draft; save leaves constraints old. No general liability edit. Rate-reset field shown regardless of type. Free-text restriction values; version dominates title; loading blank/conflicts reload without reconcile.

Target: grouped independent edits → safe save/cancel → one updated implications summary. Explain needed data; unknown allowed. Demote raw scores/versions/ISIN/expert restrictions. Emphasize arithmetic/budget/save boundary. Five seconds purpose clear, required next input unclear. Evidence: finances/page.tsx:14, :68, :223; personal/facts.py:148.

### 10.11 Goals & contributions — /plan

Purpose: saved goals and funding; goal: understand/adjust attainability. Order: budget, all projections, separate goal claims/forms, Add goal, contributions/list/form. Primaries: Add goal/per-goal Set aside; secondary: Close/Release/Confirm/Pause/Resume/Stop. Entry: nav/setup/issues; related: Finances/Holdings/Overview. Load: Very High.

**High:** repeated identities; creation bottom; allocation forms always exposed; no general revise UI despite messages. Inflation fraction/priority expose implementation. Empty message before fetch; mutations lack busy/success. Immediate close/release/stop. Pause/Stop may imply broker mandate changes but update records only.

Target: goal rows/outlook → detail with funding/scenarios/edit → recorded contributions. Demote assumptions/forms until intent. Emphasize gap/flagged allocation/budget. Five seconds task understandable, funding/outcome relationship weak. Evidence: plan/page.tsx:164, :238, :269; goals API.

### 10.12 Compare options — /simulate

Purpose: independent alternatives versus no change; goal: effect of a proposed change. Order: baseline, cash contribution/withdrawal, draft options, add/compare, baseline result, alternatives/accounting/metrics/gates. Primary: Compare; secondary: Add/Remove/details. Entry: nav/Review/Watchlist prefill. Load: Very High.

**High:** common cash and per-buy funding duplicate decisions. “Options” may be read as combined steps while API compares independently. Result identity generic. First instrument/account/holding defaults silent. Missing prerequisite plain text; initial blank. Edits retain old result. Saved ID inaccessible.

Target: intent → explicit draft/identity → derived funding → baseline comparison → advanced alternatives/save. Demote withdrawal/multi-option/equations; emphasize baseline, tax unknown on sale, same state/coverage. Five seconds comparison clear, formulation difficult. Evidence: simulate/page.tsx, api/v4/actions.py.

### 10.13 Actions — /actions

Purpose: latest review explanation/history; goal: why and next step. Order: status/rerun, issues, reasoning, comparisons, audit, all history. No clear primary; secondary Review again/Risk/what-if/history. Entry: nav/Overview. Load: High.

**High:** Actions/HOLD imply execution. Issues lack contextual next-step links present elsewhere. Audit full card. Historical selection local state; Risk link opens current risk instead of pinned historical analysis. Table displays first evaluation alternative although multiple alternatives listed; ambiguous evidence matching. Evaluation failures silent.

Target: dated Portfolio review → reasons/fix links → named comparisons → material limits → sources/history. Historical links durable and explicit; current-risk link labeled Current. Demote IDs/full history; emphasize validity/unassessed/changed data. Five seconds explanation present, title misleading. Evidence: actions/page.tsx:41, :127, :143.

### 10.14 Inbox — /inbox

Purpose: deduplicated issue follow-up; goal: fix/defer. Order: intro/tabs/issues with dates/reopen metadata/action and reason/date forms/events. Primary per issue: fix; secondary dismiss/snooze/reopen. Entry: nav/Overview. Load: High.

**High:** all deferral controls exposed. Whole-page destinations lose entity. Loading insufficient; tabs keyboard incomplete. Reopen count/date dominate. Watchlist alerts promised here, but NEXT lacks alert kinds and some issue kinds, leaving no contextual destination.

Target: Attention prioritized rows → issue detail → exact fix or requested defer editor → updated status. Activity secondary. Demote forms/metadata/events; emphasize affected entity/meaningful urgency. Five seconds purpose clear, next action diluted. Evidence: inbox/page.tsx NEXT/action mapping.

### 10.15 Theses — /theses

Purpose: personal reason/conditions checked against sources. Goal: record rationale/review evidence. Order: intro/all cards/conditions/buttons, expanded assessment/acknowledgement, bottom creation. Primary Check evidence/Save; secondary price/show/ack/add condition. Entry: nav/Watchlist. Load: High.

**High:** technical term, stock context lost, creation bottom, first instrument auto-selected. No visible revise/close despite API. Evidence/ack/price handlers lack catches. Short conditions filtered silently. Model/lineage paragraphs compete with own conditions.

Target: Investment rationales collection → selected security → own reason/checkable examples → evidence changes → reviewed state. Context edit/close preserves history. Demote full audit; emphasize user conditions/contradictions/gaps. Five seconds definition helps, entry language weak. Evidence: theses/page.tsx; api/v4/theses.py:171.

### 10.16 Research — /research

Purpose: question-based company assessment. Order: technical intro/question/auto-source/quota/three URL branches, run/example, session/report/branches/gaps/verification. Primary Run; secondary example/source input. Entry: nav; lacks security prefill/history. Load: Very High.

**High:** provider internals before question outcome. Example asks about Example Bank with Reliance/TCS/HDFC URLs, making demonstration incoherent. Rerun clears prior output. Synchronous spinner; no durable task tracking. UI mentions permalink but implements no route-state retrieval/permalink. Verification tallies not persisted on GET, confirmed backend. Claim rendering lacks direct source link for each cited claim.

Target: company/question → progress retaining earlier report → summary/support/opposition/sources → saved retrieval. Advanced URLs on request. Demote branches/quota/ID, expose actual source failure. Five seconds purpose good, operation dominates. Evidence: research/page.tsx:25, :235, :270; backend/api/research.py.

### 10.17 Settings — /settings

Purpose: earlier profile; user goal: current configuration. Order: profile gauge/details/Update. Primary Update; entry nav → Onboarding. Load: Low visual/High conceptual.

**Critical:** wrong profile authority; missing earlier profile can error despite current facts existing; gauge not current capacity/tolerance.

Target: Connections/canonical profile link/About analysis/archive. Demote old gauge. Five seconds Settings clear, scope misleading. Evidence: settings/page.tsx:22.

### 10.18 Onboarding — /onboarding

Purpose: old questionnaire; goal: setup/update. Order: long profile fieldset/three radio questions/Submit/result gauge/Dashboard. Primary Submit; entry Settings/old Dashboard. Load: High.

**High:** update does not prefill existing answers. Select defaults assume facts; no explicit unknown. Radio questions not separate legends. Generic Submit/no cancel. Finishes old Dashboard and not current facts.

Target: historical scope while current setup progressively collects relevant facts. Prefill edits; preserve drafts; save/return clear. Demote duplicated old objective/horizon from current journey, no guessed answers. Five seconds form clear, current relevance unclear. Evidence: onboarding/page.tsx:66, :220.

### 10.19 Earlier Dashboard — /dashboard

Purpose: candidate research launcher. Order: market/Nifty/risk stats, profile prompt, safer option, Opportunities/run/13 stages/results. Primary Run analysis; secondary profile/education/results. Entry archive/onboarding. Load: Moderate, High running.

**High:** legacy pipeline defaults off but CTA still offered. Existing results link depends on locally observed completion. Header differs from nav. Stages expose backend machinery. Disabled capability explained only after failure.

Target: research history/explicit enabled launcher; existing run date/result first, progress summary/detail. Preserve reload recovery. Five seconds summary readable, main product relevance weak. Evidence: dashboard/page.tsx; config.py:31; api/jobs.py; AnalysisProgress.tsx.

### 10.20 Earlier Recommendations — /recommendations

Purpose: candidates; goal: understand evidence. Order: regime/funnel, grid with two badges/four bars/horizon/fit/strength. Primary candidate link; secondary empty-run path. Entry archive/Dashboard → stock. Load: High.

**High:** process before results; confidence/agreement/coverage related bars equally weighted. Earlier personalized fit conflicts with current observations. All errors become no recommendations. Run scope/date weak.

Target: historical candidate collection → key evidence/date/limits → detail. Funnel/mechanics expanded; emphasize no-opportunity outcome. Five seconds list apparent, heuristic interpretation difficult. Evidence: recommendations/page.tsx.

### 10.21 Earlier stock detail — /stocks/[symbol]

Purpose: old recommendation evidence. Order: identity/price/badges/timestamps, chart, confidence/scores/rationale, risk gauge, forecast, council, news, advanced fundamentals/technicals. No primary CTA; secondary toggles/sources. Entry Recommendations. Load: Very High.

**High:** forecasts/council prominent while fundamentals advanced. Mixed vintages warned but need clearer historical/current boundary. No return/current watch/research flow. News/history failures may look empty. Council nested cards.

Target: shared identity → explicitly dated historical assessment → business/support/opposition/risks → deeper method. Preserve distinct evidence vintages. Demote model mechanics, emphasize neutral reasoning/uncertainty. Five seconds stock identity clear, next investigation unclear. Evidence: stocks/[symbol]/page.tsx; CouncilTranscript.tsx.

### 10.22 Candidate portfolio — /portfolio

Purpose: hypothetical sizing; goal: mix for amount. Order: expected return/volatility/Sharpe, solver warning, bars/donut, sector donut, amount/table. Main control amount; entry archive. Load: High.

**High:** Portfolio implies owned assets; input buried; uncertain metrics dominate; duplicate charts; solver internals long. Debounced requests can return out of order.

Target: Candidate allocation illustration → amount/date → purchases/cash → optional mix/method. Demote expected metrics/duplicate chart; emphasize hypothetical/fallback/unknown. Five seconds ownership ambiguous. Evidence: portfolio/page.tsx.

### 10.23 Earlier Goals — /goals

Purpose: goals/legacy earmarks; goal: track funding. Order: create form, states/cards/progress, earmark editor. Primary Create; secondary Earmark/Save/Cancel. Entry archive, legacy holdings. Load: High.

**High:** separate data hidden by same terminology; unlabeled earmark controls; positions errors become empty; create precedes collection. Progress is earmarked money, not full attainability. No transition for old earmarks.

Target: historical collection/detail, explicit mapping if adopted. Preserve historical identities/amounts; no silent recalculation. Demote duplicate active creation from main product. Five seconds locally clear, whole-product confusing. Evidence: goals/page.tsx.

### 10.24 Product Catalogue — /catalogue

Purpose: product terms/capabilities; goal: compare categories. Order: fixture explanation, type/support filters, cards with issuer/type/fixture/support/terms. Main task browse; entry archive. Load: High.

**Medium:** support taxonomy internal; fixtures mixed with actual terms; no actionable/source detail; long raw labels.

Target: Learn about products with sourced terms/category comparisons; demonstration fixtures separate. Demote support filter; emphasize liquidity/lock/risk/date/source. Five seconds “knows terms for” uncertain. Evidence: catalogue/page.tsx.

### 10.25 Compare stocks — /compare

Purpose: three stocks side by side. Order: slot cards/select/manual input/Go, nested summary cards. Main action choose/load; entry mislabeled Compare products. Load: High.

**Medium:** nav wrong; select label unassociated/manual unlabeled; no loading/request guard; metrics unaligned; mobile stacks whole stock then next; no evidence timestamps in summaries.

Target: Explore comparison with common search and aligned metric rows/date/unit/missing values. Demote nested panels, emphasize comparability. Five seconds page clear/nav inaccurate. Evidence: compare/page.tsx; StockSummaryCard.tsx.

### 10.26 Planner — /planning

Purpose: independent SIP/goal calculators. Order: growth inputs/chart/stats, goal form/result. Primary Calculate target; growth auto-update. Entry archive; defaults old profile/portfolio. Load: Moderate.

**Medium:** overlap with saved goals; assumption may inherit candidate return, not current owned assets; mixed auto/manual behavior; old responses unguarded.

Target: Planning Calculators, independent illustrative tools with visible chosen assumption. Demote silent inherited return; emphasize invested versus growth/result basis. Five seconds tools clear, relation ambiguous. Evidence: planning/page.tsx; ARCHITECTURE.md.

### 10.27 Safer Alternatives — /safer-alternatives

Purpose: education; goal: compare lower-volatility/liquidity/lock. Order: intro/disclaimer/fit-ordered cards. No primary action; entry archive/old Dashboard. Load: Moderate.

**Medium:** earlier-profile suitability badge may overstate personalization; “safer” needs credit/liquidity/inflation qualification; low-opacity eligibility.

Target: product learning comparison, suitability factors/scope/source/date. Demote old fit, emphasize tradeoffs. Five seconds education clear, personal relevance uncertain. Evidence: safer-alternatives/page.tsx.

### 10.28 Admin — /admin

Purpose: operator diagnostics; goal: troubleshoot. Order: no-auth note, model/demo stats, sources/jobs. No action; direct entry. Load: Moderate operator/Very High investor.

**Medium:** no role enforcement; consumer shell/IDs/raw errors. Client requests /admin/debug while proxy only covers /api/*; no matching frontend route/rewrite found. Confirm runtime status before claiming diagnostic usability.

Target: separate operator-purpose source/job health/recovery, redacted state. Navigation hiding is not protection. Five seconds operator purpose clear. Evidence: admin/page.tsx; lib/api.ts; api/[...path]/route.ts; next.config.js.

## 11. Ideal Page Blueprints

Conceptual wireframes only; no JSX/HTML/CSS. Conditional areas are not all shown simultaneously.

### Overview

~~~text
[Header] Overview; attention question
[Review] No change needed / needs review; date/data basis; pending qualification
         [Read review] when useful
[Attention] Up to 3 specific issues → exact entity/input
[Picture] Known value | completeness | missing/stale values
[Goals] Name | outlook | meaningful next change
[Secondary] Activity/history; setup progress only when needed
~~~

### Holdings / Accounts / Import

~~~text
[Portfolio nav] Holdings | Accounts | Risk | Review | Plan new investment
[Header] Holdings                                      [Update holdings]
[Summary] Known value + accounts + dated coverage
[Toolbar] Search | Account | Asset type | More filters
[Table] Holding | Account | Value | Share | Meaningful issue
        Row → units/provenance/goal funding/observations

[Accounts] Name | source | included value | last success | issue [Add account]
[Account detail] Back; identity/inclusion/status          [Update / Sync]
                 Holdings; secondary history/source configuration

[Import context] Replace holdings in [account]
[1 Source] CSV / Manual; template
[2 Input] Editable rows; field errors and matching
[3 Review] Added / changed / removed / unresolved; goal consequences
           [Confirm replacement] [Back] [Cancel]
[Complete] Saved rows/date; portfolio update status      [View account]
~~~

### Review / Risk / Scenarios

~~~text
[Review] Current or clearly historical/date
[Conclusion] No change / review / missing information; input basis
[Why] Material findings → affected item and next step
[Compared] Named changes versus baseline
[Limits] Missing/unassessed information
[Secondary] Sources/method; validity; history; review again

[Risk] Coverage and key observations
[Mix/concentration] Summary; selected company/sector breakdown
[Cash] Reserve/essentials → Financial profile
[Scenario] Choose illustrated fall                      [Estimate effect]
[Result] Modeled loss + outside coverage
         Expand per-holding contributions/assumptions
[Secondary] Historical movement and source details
~~~

### New investment / Compare change

~~~text
[New investment] Current portfolio/readiness; no execution
[Input] New amount                                      [Generate proposal]
[Status] Ready/blocked/missing with exact correction links
[Mix] Current → proposed; target explicitly labeled; unknown share
[Purchases] Instrument | units | dated price | estimated debit; cash left
[Secondary] Why/limits/costs; compare change; saved proposals
[Advanced] Other risk assumption; checks; rules

[Compare] Back to origin; baseline date
[Intent] Buy / sale preview / reserve / recorded contribution change
[Draft] Explicit entity + amount
[Funding] Held cash/additional cash; derived baseline
          [Compare with doing nothing]
[Result] Baseline | change | meaningful differences | unassessed limits
[Advanced] Withdrawal; independent alternatives; gates/cost arithmetic
~~~

### Goals / Contributions / Financial profile

~~~text
[Goals]                                                 [Add goal]
[Rows] Goal | target/date | set aside | monthly | outlook
[Budget] Available / recorded contributions / remainder

[Goal detail] Back; target/date                          [Edit]
[Outlook] Base illustration/shortfall; assumptions/needed inputs
[Funding] Holdings set aside                             [Set aside money]
[Contributions] Recorded funding                         [Add]
[Secondary] Other scenarios; flagged allocations; history/close

[Contributions] Monthly equivalent/budget distinction    [Record contribution]
[Rows] Name | goal | amount/frequency | recorded status → Edit
       Broker mandate changes happen outside this app

[Financial profile] Last saved/missing inputs/implications
[Sections] Income/spending/reserve; loans; risk answers; restrictions
[Active edit] Explained fields; outgo arithmetic          [Save] [Cancel]
[Feedback] Saved; calculations updated/review pending
[Advanced] Constraint detail/revisions
~~~

### Market / Security / Watchlist / Research / Rationale

~~~text
[Market] Search | Stocks / ETFs / Funds | simple relevant filters
[Rows] Identity | price/NAV/date | key context | Watch
[Optional] Stock movers only when relevant; advanced columns/filters

[Security] Back to origin; identity/plan/price/date
[Context] Owned/watched                                 [Watch in chosen list]
[Actions] Research | Write rationale | Compare
[Main] History + business/fund explanation + sourced facts
[Secondary] News/observations/costs/terms; method/adjustment audit

[Watchlist] Selected list                                [Add security]
[Status] Prices/date/disconnection
[Rows] Security | price | change | triggered alert | ownership
       Detail → notes/alerts/rationale
[Secondary] List management/refresh/sort

[Research] Saved reports                                 [New research]
[New] Company/question; Run; optional sources
[Report] Summary/business → support/opposition → risks/gaps/source links
[Secondary] Branches/verification/method

[Rationales] Security | relationship | evidence change/date [Add]
[Detail] Own reason → conditions → new evidence
         [Check evidence] [Mark reviewed]
[Secondary] Revise/close/history/source details
~~~

### Attention / Settings / Supporting pages

~~~text
[Attention] Priority | issue | entity | next step
            Secondary requested Snooze/Dismiss editor
[Views] Snoozed / Dismissed / Resolved / Activity

[Settings] Connections | Financial profile link | About analysis | Earlier tools
[Connections] Source/session/last success; operator detail if required
[Methods] Human evidence maturity → live/historical evidence → expert statistics
[Calculators] Choose question → assumption/input → illustrative result
[Learn] Category comparison → sourced terms/risk/liquidity/lock/cost
[Compare securities] Common fields across selected identities/date
[Archive] Runs/allocations/profiles/goals/snapshots → dated record/adoption
[Diagnostics] Separate operator health/recovery
~~~

Earlier Dashboard/Recommendations/Portfolio/Goals become historical templates, rather than independent equal primary pages. Earlier stock analysis remains explicitly scoped within security/history context. Catalogue/Safer Alternatives retain education; calculators remain independent.

## 12. Dashboard Review

Overview should answer attention, material changes, financial basis and next step. It should not dump readiness dimensions, all events, projections and history.

Order: conclusion/date/validity → actionable exceptions → known value/coverage → concise goal outlook → secondary activity/history. First-use mode shows verified setup progress, not healthy empty outcomes. Known value and goal shortfall are useful with scope/actions; Nifty status, model booleans and screening funnel belong elsewhere.

Earlier Dashboard is a historical research launcher where enabled. Reuse its good job recovery. A healthy review can have no prominent action; avoid manufacturing an Invest CTA.

## 13. Forms Review

Use coherent form submissions and named/associated fields/help/errors. Required input is task-specific; unknown remains allowed. Money fields need currency/decimal constraints; percentage fields should accept familiar percent values, visibly interpreted, not unexplained fractions. Preserve exact saved precision.

Show inline errors plus focusable summary where needed; explain disabled prerequisites. Busy state prevents duplicate requests; success names what saved. Cancel restores saved values. Protect drafts on navigation/unrelated reload; conflict reconciliation preserves user input.

| Form | Shape | Changes and completion |
|---|---|---|
| Account | Short single form | Name/source; broker setup separate; open created account |
| Import | Focused 3 stages | Source/input/reconcile; edit rows, show removed assets/conflicts; preserve preview on failure |
| Manual asset | Short asset-specific entry + staged rows | Lookup/name first; optional ISIN/date/source; warn switching file discards draft |
| Financial profile | Independent section edits, optional guided initial setup | Group cash flow/reserve; separate risk/loans; explain EMI; fresh saved implications |
| Loan | Focused single editor | Outstanding/date/payment; floating reset conditional; existing record editable |
| Restriction | Context editor | Type-specific human search, confirmation, reversible removal |
| Goal | Basic single form then detail | Name/target/date; explain basis, conditional inflation; advanced priority |
| Set aside | Goal-local editor or drawer | Available value/other allocations; confirmation and flagged recovery |
| Contribution | Short local editor | Already running versus idea; frequency/goal/budget example; recorded-only scope |
| Alert | Small context editor | Threshold unit based on kind; trigger/session meaning and success |
| Research | Company/question | Sources optional/expanded; coherent example; retained/durable result |
| Rationale | Focused detail editor | Own words and observable condition examples; no silent discard |
| Simulation | Intent first, advanced alternatives optional | Explicit choices/funding basis; result marked dirty after edit |

Confirmed specifics: finances.load resets drafts after unrelated writes; onboarding update lacks prefill; Plan/Accounts/Watchlist/Theses many writes lack local pending feedback; older and newer goal validation differs. Backend validation does not replace user-facing field recovery.

## 14. Tables & Data Presentation Review

Retain tables where comparing values is the task. Do not replace all data with cards.

| Surface | Current | Default target | Detail/power behavior |
|---|---|---|---|
| Holdings | Five columns, no search/filter | Holding/account/value/share/issue | Units/date/source/claims; search/type/account/sort |
| Accounts | Six columns per account repeated | Collection summary → selected account table | Source match/date history |
| Import | Row/identifier/value/match plus errors | Identity/value/change/match | Correction/removed summary, raw fields, stable row references |
| Stock/ETF Market | Nine columns, 50/page | Identity/dated price/day/key context/actions | Range/volume/trend/momentum/volatility preset |
| Funds | Scheme/category/NAV/TER/date | Scheme-plan/category/NAV-date/cost | AMC/option/terms; direct/regular/growth/IDCW clear |
| Purchases | Four columns with long why prose | Instrument/units/debit/total | Price-date/charges/reason |
| Goals | All scenario tables | Selected goal base outlook | Other scenarios and assumption comparison |
| Change comparison | Metrics per alternative card | Aligned baseline/change/material result | Full gates/accounting; named option |
| Stock compare | Separate nested cards | Common metric rows | Date/unit/source/missing values |
| Ledger | Many claim blocks | Evidence maturity list | Expert statistical detail |

Right-align numeric data, use tabular numerals/currency/appropriate precision, preserve unknown versus zero. Keep holding identity accessible during horizontal scroll. Useful bulk tasks might organize watched items or fix staged imports, not trade. Large collections need scoped loading/error/empty/count/pagination, not silently absent rows.

Charts: old Portfolio repeats bars/donut; AllocationDonut lacks its own visible legend/data equivalent; forecasts need method/uncertainty beside them. New PriceChart narrative aria-label is good. Goal contributed money and illustrated growth must differ. Do not add personal return charts without transaction basis.

## 15. Modal/Drawer/Overlay Review

No established dialog library or modal form system. Most work expands inline: ImportBox, watchlist detail, goal earmark, SecurityDetail, thesis evidence. Sidebar is overlay/drawer. Watchlist deletion uses native confirm, whereas many removals immediate.

The problem is expanding complex workflows inside collections, not excessive conventional modals.

| Task | Mechanism | Reason |
|---|---|---|
| Simple note/field edit | Inline save/cancel | Immediate context |
| Choose watchlist/row overflow | Popover/menu | Small contextual decision |
| Snooze/dismiss/add alert | Small accessible editor/dialog | Only after intent, focus/error handling |
| Goal set-aside | Local editor/drawer | Available-value context |
| Holding provenance | Desktop drawer/mobile detail | Secondary evidence and origin |
| Import replacement | Dedicated focused page/steps | Reconciliation too large for simple modal |
| Security/goal/rationale/review | Durable detail page | Substantial revisitable information |
| Close/delete/exclude | Consequence confirm or Undo | Goal/alert/review effect clear |
| Mobile menu | Accessible drawer if used | Focus lifecycle/background/scroll containment |

Avoid nested confirmations over complex import dialogs. Mobile overlays need reachable title/close and keyboard-safe scrolling.

## 16. Empty, Loading, Error & Feedback States

| State | Observed gap | Target |
|---|---|---|
| Loading | Null-return pages/Market blank body | Keep identity, region loading/busy |
| First use | Overview checklist also on failure/initial null | Show only verified empty; one saved-progress next step |
| Empty account/list | “Create below” | Direct scoped CTA, explain outcome |
| Filter empty | Text but no clear reset action | Current filter context + Clear |
| Error | Overview empties, Recommendations no-data, ledger silent | Distinct unavailable/retry, last-known content |
| Partial | Honest unknowns often present | Which tasks still possible, exact correction |
| Stale | Twin/Review warnings useful | Data/review dates and constrained interpretation |
| Edited result | Allocate/Risk/Simulate retain old result | Outdated/clear and rerun; input basis visible |
| Source disconnected | CLI panel/last prices; initial error hidden | Last successful update, operator requirement/alternative |
| Job pending | Old recovery good; review bounded polling; study reload | Pending never becomes done; persistent job/retry/reopen |
| Success | Import/profile feedback, many silent reloads | Human outcome, affected entity/review status |
| Conflict | 409 reload | Preserve draft, explain newer state/reconcile |
| Capability | Old run off by default | Explain availability before offering action |

Empty states answer what, why, next action and what follows. “No holdings for Bank deposits; import or add a deposit; account value appears after confirmation” is different from failed account retrieval.

Announce status/errors without announcing entire tables repeatedly. Quote refresh should not move focus/reorder an active edit. Treat success, dismissal and actual cause resolution differently.

## 17. UX Writing & Terminology

| Concept | Current terms | Target | Reason |
|---|---|---|---|
| Owned assets | Holdings/Twin/snapshot | Holdings; snapshot in details | Collection versus internal state |
| Hypothetical allocation | Portfolio/candidate/suggested | Candidate illustration / investment proposal | Ownership distinction |
| Review | Actions/HOLD/REVIEW | Portfolio review; No change needed/Needs review | Avoid execution implication |
| Missing facts | Readiness/NEEDS INFORMATION | More information needed + item | Recovery clear |
| Personal context | My Finances/Investor profile | Financial profile | Canonical current scope |
| Tolerance/capacity | Risk profile/score | Comfort with losses / ability to take risk | Different concepts |
| Goal allocation | Claim/earmark/set aside | Set aside for a goal / available to allocate | Consistent beginner meaning |
| Recurring funds | SIP/commitment/contribution | Recorded contributions (SIPs) | No broker mandate implication |
| Simulation | Action lab/Compare options | Compare a change | Distinguish security comparison |
| Stock comparison | Compare products/stocks | Compare securities or Stocks if limited | Match supported scope |
| Buying plan | Invest/What to buy | Plan new investment/Proposed purchases | Preview status |
| Personal reason | Thesis | Investment rationale | Discoverable; glossary may retain thesis |
| Research internals | Branch/gaps/ready to publish | Research areas/missing evidence/report unfinished | Outcome language |
| Data operation | Ingest/instrument master | Update/load investment list | Avoid provider machinery |
| Validation | Scorecard/earned weight | Model evidence/method review | Not personal performance |
| Fixture | Synthetic | Demonstration data—not a real quote | Explain consequence |
| Missing value | UNKNOWN/n-a/dash/unknown | Unknown/Not available plus reason | Not zero/inapplicable |
| Actions | Submit/Go/Run/Save/Add | Save profile/Estimate/Compare/Add restriction | Specific completion |

Move provider/quota/algorithm explanations deeper; keep missing-data/cost/material limitations beside results. Translate enums intentionally, not just replacing underscores. Heuristic confidence must not look like calibrated profit probability.

## 18. Design System Consistency

Existing local system: CSS RGB theme tokens, Tailwind mapping/radii/shadows, Inter/Space Grotesk, Lucide, Button/Card/Panel/EmptyState/Skeleton/StatCard/ProgressBar/RiskGauge, shared motion. No comprehensive fields/tabs/menu/dialog/table contract.

Button offers primary/secondary only; destructive actions vary between ordinary button and red text. Card emits h3 and universal border/shadow regardless of hierarchy. Page-local input classes repeat with different validation/save behavior. Status shape/casing/tone varies. Hardcoded charts use additional palette. Older pages often motion/skeleton; newer pages often blank-load.

| Component | Small role set | Contract |
|---|---|---|
| Action | Primary/Secondary/Quiet/Destructive | Task-level emphasis, pending, focus, correct link semantics |
| Status | Neutral/Information/Success/Warning/Error | Text meaning, unavailable distinct from failure |
| Surface | Main content/interaction/callout | Headings/space internally, no automatic nested card |
| Field | Text/money/percent/search/date/choice | Label/help/error/unknown/dirty/save |
| Toolbar | Search/basic filter/More/sort | Persistent state/count/reset |
| Disclosure | Details/row detail/history | Expanded state/keyboard/context |
| Table | Collection/comparison/reconciliation | Headers/caption/numbers/states/mobile |
| Navigation | Primary/section/breadcrumb/filter-tab | Location/labels/full interaction pattern |

Use page title/section/body/helper hierarchy. Decisions/forms/material caveats need readable text; 10–11px should be limited to secondary metadata and tested. Space groups fields/related facts more tightly than independent tasks. Semantic green/red remains for financial change; signal positivity is not personal suitability. Confirm contrast before specifying new tones.

## 19. Accessibility

Source-based practical review, not conformance certification.

### Confirmed gaps

| Gap | Evidence | Recommendation |
|---|---|---|
| Link wrapping button | Landing, Overview, Inbox | Styled navigation link |
| Missing field names | Compare slot/manual; Goals earmark | Associated visible labels |
| Incomplete custom tabs | Market/Inbox/Watchlist | Full keyboard/panel pattern or proper filter buttons |
| Drawer focus lifecycle absent | Sidebar.tsx:139 | Escape/trap/initial and return focus/background inert |
| Current nav not semantic | Sidebar active classes only | aria-current |
| No skip; heading order | Layout/TopBar h2/Card h3 | Skip to main, one h1, hierarchical sections |
| Error associations absent | No shared aria-invalid/describedby | Field errors/summary/focus/announcement |
| No authored reduced-motion path | Presets/sidebar/repeating Skeleton | Reduced variants including charts |
| Toggle state incomplete | Candlestick horizon/stock advanced | Pressed/expanded relationships |
| Decorative icon hiding uneven | Shared buttons/badges/nav | Hide decorations, preserve meaningful names |
| Table semantics uneven | New captions/scope; old Portfolio/Holdings/Admin omit some | Consistent scoped headers/captions/row context |

Preserve Button focus rings, wrapped labels, newer table semantics, RiskGauge/PriceChart descriptions. Do not call all inputs unlabeled.

### Manual checks

Contrast: muted opacity, amber warning, chart metadata/sidebar/disabled controls—no measured ratio claimed. Keyboard/chart tooltip access depends on Recharts runtime; ensure readable narrative/data alternatives. Plain buttons may have browser focus defaults; verify rather than assuming none. Measure compact targets and spacing. Broad live regions may overannounce. Check radio question group announcements. Test 200–400% zoom, long names, currencies, soft keyboard and reflow.

Future gate: keyboard completes import/profile/goal/alert/review/simulation; drawer focus returns; errors announced; reduced motion stops infinite decoration; zoom retains actions and financial meaning; destructive changes have consequence/confirmation or Undo.

## 20. Responsive UX

At sm the fixed 224px rail coexists with form grids switching to 3–5 columns. At 640px only roughly 416px remains before padding. This source combination suggests crowding; exact rendering requires manual confirmation.

| Width class | Risk | Priority |
|---|---|---|
| Mobile 320–480 | 23-link drawer, long cards, wide data, tiny actions | Conclusion/identity/one action; compact rows/detail |
| Tablet 640–900 | Desktop rail + multi-column forms/comparison | Later/compact rail; content-width-based columns |
| Laptop 1024–1440 | Rail scroll, summaries push main task down | Main collection/conclusion in initial viewport |
| Desktop | Dense table/nested detail | Stable identity and optional selected detail |
| Large desktop | Prose unbounded | Reading/form width capped, data tables allowed wider |

Hotspots: Market 640px minimum/nine columns; Invest 560px table; Risk 128px bars; ProgressBar 128px label + 48px value with long currency; AnalysisProgress indentation; Plan scenario tables; three-stock stacked comparison; six-column manual rows; five-column loans.

Mobile retain name/value/meaningful status/action. Units/matching/range/momentum/versions deeper. Import errors/replacement remain readable. Goal target/date/outlook before scenarios. Finance single-column groups with visible save/cancel.

Test 360/390/768/1024/1440, tablet landscape, zoom/long text/empty/stale/error and keyboard. Responsive proof is task completion, not just no scrollbar.

## 21. First-Time User Experience

Likely current session: equity-only promise/full nav → Overview three setup domains → Holdings twin empty/observations/coverage/CLI before account creation → either correct account entry or lower legacy entry → Settings may lead to old onboarding → old Dashboard run off by default. Successful setup still leaves profile authority unclear.

Target:

1. Explain private portfolio review, evidence/date and external execution.
2. Choose manual/CSV or accurately qualified operator connection.
3. Import one account with preview/replacement scope.
4. Show dated first holdings and ask whether other accounts missing.
5. Collect task-relevant finances with expense/loan example and unknown support.
6. Add a goal when relevant; explain goal-dependent conclusions without pretending all risk observations require goals.
7. Pending then first review/missing input; no-change outcome counts as success.

Progress survives navigation and distinguishes draft/saved. Teach set-aside at goal funding and price-level basis at target creation, not backend concepts in opening prose.

## 22. Experienced User Experience

Preserve direct detail links, tables, evidence, remembered filters/selected lists, compact column presets and advanced scenarios. Do not force setup again. Keep actual answers distinct from hypothetical risk assumptions.

Good patterns: Market debounce/request guard/pagination; old job recovery; Watchlist buy prefill; details disclosures. Extend consistently. Later shortcuts: account updates, selected-security watch/rationale, saved comparison, keyboard issue navigation, bulk watched-item organization with undo. No trading shortcut.

Remember presentation, not silently changed financial facts. Global command/search is optional after stable entities/IA.

## 23. Feature Placement Analysis

| Feature | Current | Target | Reason |
|---|---|---|---|
| Value/coverage | Overview/Twin | Compact Overview, detailed Holdings | Different depths |
| Consolidated assets | Twin card | Holdings main collection | Core task |
| Accounts/imports | Deep Holdings | Accounts/detail/update | Scope and focused reconciliation |
| Broker CLI | Daily Holdings | Connections/operator detail | Configuration |
| Coverage answer | Full Holdings card | Post-import/Accounts editor | Ask after actual data |
| Inclusion | Every account action | Detail/overflow with effect | Deliberate material change |
| Observations | Holdings panel | Asset detail/Review when material | Different from task queue |
| Exposure/scenario | Top Risk | Portfolio Risk | Owned-state context |
| New money | Top Invest | Portfolio proposal | Planned change |
| General simulation | Top Compare | Contextual Compare change | Intent first |
| Financial facts | My Finances | Planning profile | Canonical personal context |
| Loans/preferences | Bottom Finances | Independent profile sections | Safe edit boundary |
| Goals/outlook | Split Plan | Goals/detail | Outcome/funding together |
| Contributions | Bottom Plan | Cross-goal plus goal local | Budget and context |
| Review/history | Actions/Overview | Portfolio Review | Dated assessment |
| Issues/events | Inbox/multiple summaries | Attention/secondary Activity | Follow-up versus event |
| Watchlists | Top link | Explore + shortcut | Monitoring/investigation |
| Research | Top technical form | Explore/security action | Identity preserved |
| Theses | Top link | Rationales/security context | Own reason |
| Model study | Primary Scorecard | About analysis/context links | Method not health |
| Product education | Legacy catalogue/safer | Learn | Useful education, fixtures separate |
| Candidate runs/allocation | Separate legacy links | Run history/detail | Hypothetical scope |
| Old profile/goals/snapshot | Active overlaps | Archive/adoption | Preserve separate records |
| Calculators | Legacy Planner | Planning Calculators | Independent value |
| Debug | Direct Admin | Operator-purpose context | Troubleshooting boundary |

## 24. Redundancy & Consolidation Opportunities

Consolidate presentation, not unverified data: Overview/Twin readiness; goal outlook/funding; capacity/constraints human summary; consolidated versus every account table; allocation bars/donut; repeated full audit; shared security identity. Preserve old/current evidence scope.

Separate reading from account configuration/import, finance edits from unrelated writes, goal collection from funding detail, issues from events, research reports from diagnostics and method validation from personal review.

Independent calculator is not duplicate saved-goal engine. Category education is not securities catalogue. Old earmarks/answers must not be silently mapped to current relationships.

## 25. Cognitive Load Analysis

Ratings consider unfamiliar concepts/decisions/relationships, not DOM counts.

| Surface | Load | Why / reduction |
|---|---|---|
| Navigation | Very High | 23 overlapping peers → four domains |
| Landing | Moderate | Dense promise/full choices → current purpose/start |
| Overview | High | Review/value/readiness/history → attention-first |
| Holdings/accounts | Very High | Aggregate/source/legacy/config → scoped collection/detail |
| Market | Very High | Movers/filters/columns/audit → search/detail |
| Finances | Very High | Inputs/tolerance/capacity/loans/versions → independent scopes |
| Goals | Very High | Projections/claims/budget/commitments → one goal story |
| Invest | High | Override/mix/purchases/checks → amount/readiness |
| Simulation | Very High | Cash flows/options/gates → intent/funding summary |
| Review | High | Issues/alternatives/audit/history → conclusion/reasons |
| Inbox | High | Resolution/deferral per item → one next step |
| Watchlist | High | Lists/prices/context/alerts/notes → monitoring then detail |
| Rationales | High | Conditions/assessments/audit → user conditions first |
| Research | Very High | Branch/quota/verification → question/report |
| Scorecard | Very High | Statistics/method registry → human trust summary |
| Settings | Low visual, High conceptual | Wrong profile authority |
| Onboarding | High | Long questionnaire/old scope → progressive relevant setup |
| Old dashboard | Moderate/High running | 13 stages → status/detail |
| Candidates/stock | High/Very High | Heuristic models/vintages → scoped evidence |
| Candidate portfolio | High | Hypothetical stats/charts → amount/cash/proposal |
| Old goals | High | Duplicate concept/snapshot funding → historical clarity |
| Catalogue | High | Types/support/fixtures → educational categories |
| Compare | High | Slots/unmatched rows → common metrics |
| Calculators | Moderate | Two questions/assumptions → explicit independent tools |
| Education | Moderate | Risk/liquidity tradeoffs; preserve |
| Diagnostics | Moderate operator | Familiar source/job concepts; actionable errors |

Validate with unaided task location, next-step explanation and data-basis comprehension. Observe wrong destinations and lost edits, not just clicks/neatness.

## 26. Recommended Design Principles

1. Start with the owner's current question, not computation pipeline.
2. Owned, proposed and historical remain visibly distinct.
3. Uncertainty stays beside the conclusion it qualifies.
4. One scoped current entry path for holdings/profile/goal funding.
5. No change needed is a valid successful result.
6. Editing includes reliable save/cancel/draft/conflict/recalculation behavior.
7. Selected account/goal/security identity survives transitions.
8. Advanced complexity appears when its task begins; blockers stay visible.
9. Human reasoning first; technical evidence reachable deeper.
10. Simplification preserves expert tables, details and direct access.

## 27. Quick Wins

Future work only:

- Align EMI wording/contract and show outgo arithmetic.
- Remove contradictory active legacy entry from normal Holdings.
- Correct shell/page names and Settings current-profile link.
- Explain disabled legacy analysis before request.
- Fix link/Button nesting, labels, current nav semantics and skip link.
- Header entry for account/goal/rationale creation.
- Inbox deferral controls only on request; close/delete secondary with consequence/undo.
- Mark edited proposal/scenario/comparison outdated.
- Explicit loading/error/empty in blank/silent screens.
- Coherent example research and human enum/action wording.
- Explain pause/stop updates recorded contributions only.

Some “copy” fixes affect financial meanings. Confirm contracts before treating them as cosmetic.

## 28. Structural Improvements

- Four-domain IA/current-history boundaries.
- Holdings/Accounts/detail/import reconciliation split.
- Canonical financial profile with independent safe edits.
- Goal outlook/funding plus revision/contribution management.
- Review versus Attention with exact entity resolution.
- Durable security/review/report/proposal/comparison detail.
- Job recovery/result invalidation/state taxonomy.
- Mobile task and accessibility contracts before restyling.

## 29. Long-Term Improvements

After clarity: cross-entity search, keyboard shortcuts, expert table presets, bulk watch organization, contextual education, restrained motion, reading widths, numeric alignment and meaningful charts.

Do not add visual dashboards/animations to compensate for ambiguous tasks. Browser broker login, complete personal performance, tax lots and public multi-user deployment are separate capability/product decisions; this audit does not promise them.

## 30. Priority Matrix

P0 structural/correctness; P1 major usability; P2 clarity/consistency; P3 polish. Effort is relative, not hours.

| ID | Priority | Recommendation | Impact | Effort | Acceptance/dependency |
|---|---|---|---|---|---|
| R01 | P0 | Current/historical model and IA | Very High | High | Owner can choose correct flow |
| R02 | P0 | Canonical profile | Very High | Medium | Settings affects intended review |
| R03 | P0 | One account entry/adoption | Very High | Medium | Intended current state updated |
| R04 | P0 | Expense/EMI contract | Very High | Low | Worked outgo example explainable |
| R05 | P1 | Draft/conflict/fresh summary | Very High | Medium | No unrelated edit loss |
| R06 | P1 | Import reconciliation | High | High | Removed/changed scope clear |
| R07 | P1 | Explicit data states | Very High | Medium | Outage never empty/healthy |
| R08 | P1 | Overview/Review/Attention loop | High | Medium | Five-second next step |
| R09 | P1 | Goal detail/revision | High | High | Outcome/funding together |
| R10 | P1 | Security context | High | High | Stock/origin retained |
| R11 | P1 | Dirty results/job recovery | High | Medium | No falsely current result |
| R12 | P1 | Mobile/keyboard/focus | High | High | Core journeys completed |
| R13 | P1 | Destructive/SIP semantics | High | Medium | Consequence/Undo and record scope |
| R14 | P1 | Historical evidence links | High | Medium | No silent current substitution |
| R15 | P2 | Shared interaction templates | High | Medium | Equivalent task behavior |
| R16 | P2 | Market filters/columns/state | High | Medium | Search priority and return |
| R17 | P2 | Report/source/example quality | High | Medium | Traceability/reopen limits |
| R18 | P2 | Method evidence placement | Medium | Low | Not personal performance |
| R19 | P2 | Terminology | Medium | Low | Same concept, precise scope |
| R20 | P2 | Saved result retrieval | High | Medium | Existing API/replay limits checked |
| R21 | P2 | Duplicate content/disclosure | Medium | Medium | No necessary fact lost |
| R22 | P3 | Type/contrast/chart polish | Medium | Medium | Manual rendering verified |
| R23 | P3 | Expert presets/shortcuts | Medium | Medium | Stable entities/IA first |
| R24 | P2 | Diagnostic route/context | Medium | Low | Proxy/runtime checked |

R06/R09/R10/R20 require contract/capability checks before exact UI commitment. Narrow correctness fixes can precede whole-shell implementation.

## 31. What Is Already Working Well

- No-action outcomes are legitimate; preserve this stance.
- Known value/unknowns/unmatched/coverage often honestly explicit.
- Import preview/conflict/confirmation/account-only scope/replay feedback.
- Immutable snapshots/revisions and historical reviews preserve traceability.
- Pending/historical review warnings.
- Watchlist simulation prefill.
- Market debounce/pagination/request-order guard.
- Earlier jobs survive reload with retry/backoff.
- User-owned rationale conditions not rewritten or silently applied to portfolio.
- Research opposing evidence/gaps instead of confidence alone.
- Focus-ring Button, wrapped labels, newer captions/scopes, accessible gauge/price summary.
- Theme tokens/shared primitives, avoiding a new design stack.
- Educational caveats distinguish illustrative terms from quotes.

## 32. Final Recommended Product Structure

Global shell: four domains, active section links, Attention unresolved count, Settings; contextual title/actions/search; detail breadcrumbs/return; source-specific dates. Setup mode avoids full navigation overload. Mobile same hierarchy with accessible smaller choice set.

| Primary/utility | Default | Secondary | Context work |
|---|---|---|---|
| Overview | Attention/conclusion | Setup when incomplete | Review/exact fix |
| Portfolio | Holdings | Accounts/Risk/Review/Plan investment | Import/holding/scenario/saved plan |
| Planning | Goals | Contributions/Profile/Calculators | Goal funding/revise/finance edits |
| Explore | Market | Watchlists/Research/Rationales/Learn | Security/watch/report/compare |
| Attention | Needs attention | Deferred/resolved/activity | Fix/snooze/dismiss |
| Settings | Connections | Profile link/Methods/Archive | Operator setup/evidence/adoption |

~~~text
First session: Welcome → source/account → preview/confirm → holdings
               → relevant facts → optional goal → review
Daily: Overview → review/issue → exact fix → pending/current result
Investment: Portfolio proposal → amount/readiness → mix/purchases/limits
            → optional comparison → saved result; execution external
Goal: Goals → detail → funding/target/contribution change → outlook
Explore: Market/Watchlist → security → research/rationale → evidence
         → optional simulation → originating context
Attention: Issue → affected entity → remedy/recheck or deliberate defer
Operator: Connections/Methods → instructions/evidence → source status
~~~

Always visible: owned/proposed/history scope, outcome, date, consequential missing data, unknown value, costs/execution limits. One interaction deeper: readiness dimensions, source selection, units, full scenarios/gates/branches. Dedicated history: imports/proposals/comparisons/reviews/assessments/reports. Settings/operator: CLI/env/policy/hash/statistics/earlier controls.

Use templates in Sections 9/11; do not create navigation per backend entity.

## 33. Recommended Redesign Sequence

1. **Meaning/correctness:** product promise, ownership/proposal/history, EMI contract, profile authority, recorded SIP and account replacement. Preserve existing records.
2. **Validate IA through representative tasks:** new import, routine review, goal funding and watched-stock comparison.
3. **Navigation/shell:** four domains, utilities, historical access, parent/mobile context after meanings stable.
4. **Page/state/interaction contracts:** templates, pending/error/stale, edit/cancel/conflict, keyboard/focus before visual components.
5. **Trustworthy inputs:** account imports and finances; eliminate wrong-system entry/lost drafts/misleading expenses.
6. **Goals and daily loop:** outlook/funding, Overview conclusion, Review reasoning, exact Attention resolution.
7. **Proposals/exploration:** shared identity, watchlists/rationales/reports, saved retrieval and dirty-result behavior.
8. **Consolidate/deepen:** redundant cards/tables and technical audit to intended depth, retaining required facts.
9. **Prove accessibility/responsive journeys:** narrow widths, zoom, keyboard, screen reader, reduced motion, long text and failures. Accessibility is designed earlier; this stage proves it.
10. **Polish/expert efficiency:** type/space/surfaces/charts, contrast and optional presets/shortcuts. Stop expansion at clear reliable defined tasks.

### Future acceptance criteria

- New owner locates current import/profile without API/version knowledge.
- Account replacement explains changed/removed data and goal consequences.
- Finance drafts survive unrelated actions/conflicts and saved summaries match accepted inputs.
- Essential outgo has no double-counted EMI and can be explained.
- Core pages pass location/purpose/main-information/next-step five-second test.
- Loading/outage/partial never imply healthy absence.
- Selected security/origin persists across investigation/simulation.
- Historical results remain dated/retrievable and do not silently swap current evidence.
- Changed inputs cannot leave falsely current results.
- Core tasks work at narrow widths/keyboard/zoom/reduced motion; advanced detail remains accessible.

### Read-only boundary and verification

This report is the sole authorized created artifact. No implementation, styling, routes, APIs, backend, dependencies, migrations, data or commits were changed by this audit. Pre-existing working-tree work is preserved. Final repository fingerprints and file inventory are verified after report creation.
