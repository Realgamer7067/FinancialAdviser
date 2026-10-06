# Advisor plan (P0-P7): from "review my portfolio" to "tell a beginner what to do next"

Written 2026-10-01 after the research pass. The Portfolio Intelligence Engine (phases 00-09) reviews what the owner already holds. This plan adds the other half: a market they can browse, an allocator that can start from an EMPTY portfolio, and suggestions on the portfolio and watchlist pages. The app still only suggests; the owner executes manually in Angel One. College project on the owner's own money, Indian investor.

## Decisions made with the owner (2026-10-01)
- **Everything is in scope**: direct stocks AND ETFs AND mutual funds (and SIPs). Not ETFs-only.
- Mutual fund prices/NAVs: AMFI's official file is the primary source (free, no key, includes ISIN); mfapi.in only for NAV history if needed.
- Minimal AI. Nothing that renders a list or a suggestion calls a model. A model runs only when the owner clicks "ask why" on one item, and the answer is cached against the data it used.
- Highly parallel and rate-limit aware, with caching, so pages never wait on the broker.
- Stuck legacy job `7ecca60b...` marked failed (legacy pipeline stays off).

## What the research established (sources checked, not recalled)
- **Angel SmartAPI has no mutual fund endpoints** (official docs cover equity, derivatives, commodity, currency). Angel's app does sell 4,000+ direct schemes at 0% commission with SIPs from Rs 100, so funds are suggested here and bought manually there.
- **Angel rate limits** (SmartAPI forum thread "Changes in API Rate Limit"): quote 10/s, 500/min, 5000/h; getCandleData 3/s, 180/min, 5000/h; getAllHolding 1/s; login 1/s. The per-minute cap stacks on the per-second cap. Candle limits have false-positive reports, so we stay at about 1 request/s with backoff. WebSocket 2.0: 1000 token subscriptions per session (each mode counts), 3 connections per client.
- **April 2026 SmartAPI changes only affect order placement** (static IP, no market/IOC orders). We never place orders.
- **AMFI `NAVAll.txt`**: semicolon-separated, scheme code + ISINs + plan/option + NAV + date, with category and AMC header lines. Plan/Option columns are blank for old schemes.
- **NSE files** (`EQUITY_L.csv`, `eq_etfseclist.csv`) and **NSE Indices** `ind_niftytotalmarket_list.csv` (ISIN -> macro sector for ~750 stocks) download without keys or cookies.
- **NSE corporate-actions API** returns events with ex-dates and a free-text subject (`Bonus 1:1`, `Face Value Split ... From Rs 10/- ... To Re 1/-`, `Dividend - Rs 6 Per Share`, `Rights ...`, `Demerger`). It answered without cookies from the VPN IP; it is unofficial and can change, and it dropped connections when hit too fast.
- **Yahoo (yfinance) returned HTTP 429** from this IP during the check, so it is not a dependable adjustment source. **Correction found while building P1:** Angel's daily candles are already split/bonus-adjusted (checked live on RELIANCE, KOTAKBANK, TRENT, LICI), so applying NSE factors on top would double-adjust. P1 therefore audits each split/bonus against the stored prices and adjusts only events that are still raw.
- **Tax (verified on current pages)**: equity funds/ETFs 20% short-term (<12 months), 12.5% long-term above Rs 1.25 lakh a year; gold ETFs slab rate <12 months, 12.5% after; debt funds bought on/after 1 Apr 2023 at slab rate; the Income-tax Act 2025 renumbered sections from April 2026 with the same rates. To ship as a versioned table, not code.

## Architecture rules
1. **Deterministic first.** Screening, scoring, allocation, gates are plain Python. Specialist models (Kronos etc.) are one check among several, run in a nightly batch on a shortlist, never per page view and never on all ~2,600 stocks. The LLM only explains stored evidence on demand.
2. **Three cache tiers, every value dated.** Live (WebSocket LTP for what is on screen + shared in-memory price cache; batched REST fallback), daily (one full-market snapshot after close: about 50 quote requests for 2,600 stocks), history (one-time backfill, then one new day per instrument).
3. **Bulk fetching only in the worker.** The Angel client's rate limiter is per process; the API only enqueues jobs and does small on-demand calls. (Decision from advisor review.)
4. **ISIN is the spine** (`securities`), linked to Angel tokens by symbol+series and to the legacy Nifty-50 `instruments` by ISIN. Symbol alone never proves identity; ambiguous matches stay unlinked.
5. **Raw data is never rewritten.** Corporate actions are stored with the raw subject; adjustment factors are derived from them and re-derived whenever the parser improves. Anything needing judgement (rights, demerger, scheme of arrangement) is `needs_review`, never guessed.
6. **A model gains weight only after out-of-sample proof**, with a shadow ledger of suggestions and outcomes (P6). Confidence is measured by calibration, never asserted.

## Phases
- **P0 Data foundation (this slice)**: securities catalogue (stocks, ETFs, funds), sector map, corporate actions with split/bonus factors, worker job + nightly schedule, read API. See STATE.md for what was built and measured.
- **P1 Market page**: searchable/filterable list of everything, live prices for visible rows only (WebSocket LTP + shared cache), daily snapshot job, fund NAVs. Includes the full-market quote snapshot and Angel candle backfill with adjustment from corporate actions.
- **P2 Signals (no AI)**: DONE (see STATE.md): trend, volatility, drawdown, momentum rank, liquidity gate, independence measured; Kronos stored point-in-time, shown relative, counted 0 (biased upward in tests).
- **P3 Allocator**: DONE (see STATE.md): buy-only plan, band mix, instrument rules, engine-gated, saved immutably.
- **P4 Suggestions UI**: DONE (see STATE.md): what-changed lines on Holdings and Watchlist, hysteresis measured on real data, state-based information-only inbox items, immutable log.
- **P5 "Ask why"**: on demand, fed stored signals, cached, never invents a number.
- **P6 Shadow ledger**: DONE (see STATE.md): frozen registry, one registered backtest, insert-only live outcomes, scorecard. No signal has earned a weight.
- **P7 Data gaps**: DONE (see STATE.md): dividends/total return, fund expense ratios (strict matching), NSE holiday calendar, verified fund NAV history.
- **UI/UX audit slices A and B**: DONE (see STATE.md): correctness fixes and four-domain navigation; later slices listed there.

## Known limits (stated, not hidden)
- Sector data covers ~750 of ~2,600 stocks (NSE Indices Total Market); the rest show as unclassified.
- Rights, demergers and schemes of arrangement are flagged, not adjusted; history around those ex-dates is unreliable until reviewed.
- The NSE corporate-actions endpoint is unofficial and may change or throttle.
- Tax rules and fee/cost assumptions are placeholders until reviewed against current sources.
- Backtest numbers, when they exist, carry the survivorship-bias caveat from CLAUDE.md.
