# Permitted source registry (V3 Phase 02)

Small, explicit corpus of data sources this application actually uses.
Deliberately NOT widened just to fill this table (per Phase 02 instruction
6: "do not widen acquisition merely to fill a table") — every row below is a
source already wired into a provider in `backend/app/providers/`.

| Source | Used for | Access | Freshness | Rights/notes | Parser/version |
|---|---|---|---|---|---|
| Yahoo Finance (`yfinance` package, unofficial) | Daily OHLCV candles (`yfinance_market_data.py`), fundamentals snapshot (`fundamentals.py`) | Free, unofficial, rate-limited, no key | Live, `auto_adjust=True` (adjusted closes) | Provisional MVP choice only — README/CLAUDE.md already flag this as unsuitable for a licensed advisory product; swap before any production use | `yfinance` pinned version per `requirements.txt`; no parser beyond the library's own `.history()`/`.info` |
| Synthetic demo seed (`demo_market_data.py`, `demo_fundamentals.py`) | Offline fallback when `DEMO_MODE=true` (default) | Local, generated, no network | N/A — synthetic, `adjusted=False` (no real corporate actions to adjust for) | Never presented as real; `source="demo_seed"` tagged on every row | In-repo generator, versioned with the app itself |
| Economic Times RSS, RBI RSS (`rss_news.py`) | News headlines/sentiment input | Free, public RSS, no key | Polled per pipeline run (`NEWS_WINDOW_DAYS=14` window) | Public syndicated feed; only headline/URL/summary retrieved, no full-article scraping | Standard RSS/XML parsing via the feed library already in `requirements.txt` |
| NSE constituent list + Upstox instrument master (`scripts/sync_instruments.py`) | Nifty50 universe seed (`providers/nifty50_seed.py`) | One-time sync script, not live-polled | As of last manual sync run | Cross-checked against 3 wrong hand-typed ISINs per CLAUDE.md — verify before reusing sync output uncritically | Script-local, no external library beyond the HTTP client already used |
| TrueData (historical cache only) | One-time historical price cache (`scripts/sync_truedata_history.py`) | NDA-covered — see `.gitignore`'s TrueData exclusions and this repo's memory rule: **never push TrueData-derived artifacts to GitHub** | One-time snapshot, not live-refreshed | NDA scope: historical cache only, no live streaming (per project memory) | Script-local |

## Not in scope (explicitly not sourced, per Phase 02's "do not widen" instruction)

- NSE shareholding-pattern filings (true promoter-holding %) — `FundamentalSnapshot.promoter_holding` stays `None` until this is sourced (see `docs/V2-RETHINK.md` P1, `docs/v3-execution/CONTRACTS.md`).
- RBI DBIE / MoSPI macro vintages — not wired into any provider.
- BRSR disclosures — not wired into any provider.
- Point-in-time historical fundamentals (XBRL/annual reports) — the backtester (`backend/app/backtesting/engine.py`) explicitly documents this gap and stays technical-only as a result.

Adding a new source means: (1) add a provider behind the existing `MarketDataProvider`/`FundamentalDataProvider`/`NewsProvider` interface in `backend/app/providers/base.py`, (2) add a row to this table with real access/rights/freshness answers (not placeholders), (3) never widen this table speculatively ahead of an actual provider being wired in.

## Phase 06 addendum: synthetic fixture corpus (fixture-only, not a real source)

Phase 06 built a small representative document/fixture corpus plus hostile
test fixtures for the parallel retrieval-fetcher and claim-ledger workers,
per V3-IMPLEMENTATION-PLAN.md Section 9.1 ("Start with 10-15 representative
companies..."). This is **not** a new document-acquisition source and does
**not** widen real acquisition -- no live scraping, no real filing
downloads occurred or are authorized. It is added here only because it is
corpus-shaped and future readers should not mistake it for real data.

| Source | Used for | Access | Freshness | Rights/notes | Parser/version |
|---|---|---|---|---|---|
| Synthetic fixture corpus (`backend/app/services/source_corpus_fixtures.py`) | 12 synthetic filing/news/factsheet/macro-release excerpts (banks, non-financial, non-bank-financial) plus hostile fixtures (malformed-PDF bytes, oversized-response generator, prompt-injection text, SSRF-attempt URL list) for retrieval/claim-ledger test suites | Local, in-repo Python module, no network | N/A -- fully synthetic, static, versioned with the app | Fictional entities/URLs only (`(SYNTHETIC)` suffix, `fixtures.internal.example` domain); never presented as real; not connected to any live provider or the claim ledger itself | In-repo module, no external parser; `backend/tests/test_source_corpus_fixtures.py` covers shape/content invariants |

This corpus does not satisfy Section 9.1's "extend to the existing Nifty50
universe after parser and coverage tests pass" step -- that still requires
a real, reviewed document source, which remains unresolved (see
`docs/v3-execution/STATE.md`).
