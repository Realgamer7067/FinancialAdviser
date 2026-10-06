"""The FROZEN design of the scoring study: which claims are tested, how, and what counts as a result. Written and hashed BEFORE the
study is run; any change to anything below is a new `STUDY_VERSION`, and the scorecard shows how many versions have been tried (so
nobody can tune horizons or filters until something looks significant).

A claim here is a statement about a stored signal's definition (`signals-v1`, exactly as stored), not about stock-picking:
"stocks ranked higher on X earned higher returns over the next month". Evidence has THREE grades, never mixed:
- backtest: computed on past dates from today's stored history. Survivorship-biased and partly in-sample; it can only ever reach
  `backtest_suggestive`, never `earned`.
- live: signals logged at the time and scored after their horizon elapsed. The only evidence that can lead to `earned`.
- accounting: arithmetic about a plan (did it beat leaving the cash) is NOT skill evidence and is labelled so."""

import hashlib
import json

STUDY_VERSION = "study-v1"
SIGNAL_METHOD = "signals-v1"

PRIMARY_HORIZON = 21          # sessions; monthly rebalance dates, so the observations are non-overlapping
SECONDARY_HORIZON = 63        # descriptive only (every third month: non-overlapping); never produces a verdict
WARMUP_SESSIONS = 253         # same minimum history as the signals themselves
MIN_NAMES_PER_DATE = 100      # a date with fewer eligible stocks is skipped, not scored
LIQUIDITY_FLOOR_RUPEES = 10_000_000   # point-in-time at each date (median 20-day traded value), same floor as the signals
ENTRY = "close of the session AFTER the rebalance date (the signal is only known after that close)"
EXIT = "close of the session `horizon` sessions after entry; scored only once the full horizon exists in stored candles"
FORWARD_VOL_WINDOW = 21
BOOTSTRAP = {"resamples": 5000, "seed": 20261001, "block": 1}

CLAIMS = [
    {"id": "C1_trend_return", "family": "trend", "kind": "return", "feature": "sma200_ratio", "sign": 1,
     "statement": "Stocks further above their 200-day average earned higher returns over the next month (rank IC > 0)."},
    {"id": "C2_momentum_return", "family": "trend", "kind": "return", "feature": "mom_12_1", "sign": 1,
     "statement": "Stocks with a stronger 12-1 month return earned higher returns over the next month (rank IC > 0)."},
    {"id": "C3_lowvol_return", "family": "risk", "kind": "return", "feature": "vol_252", "sign": -1,
     "statement": "Calmer stocks (lower 1-year volatility) earned higher returns over the next month (rank IC of the negated volatility > 0)."},
    {"id": "C4_vol_persistence", "family": "risk", "kind": "risk", "feature": "vol_252", "sign": 1, "outcome": "forward_vol",
     "statement": "Stocks that were more volatile over the past year were more volatile over the next month (rank IC with realized volatility > 0). A RISK claim, not a return claim."},
]
K = len(CLAIMS)                       # the multiple-testing family
ALPHA = 0.05
ALPHA_PER_CLAIM = ALPHA / K           # Bonferroni

VERDICTS = {
    "no_data": "nothing has been measured",
    "too_early": "too few dates to say anything",
    "underpowered": "the confidence interval includes zero AND the study could not have detected an effect smaller than the minimum detectable IC",
    "no_evidence": "the confidence interval includes zero and the study was able to detect an effect of reasonable size",
    "negative": "the whole confidence interval is below zero",
    "backtest_suggestive": "BACKTEST ONLY: the lower bound is above zero after the Bonferroni correction. Biased evidence: it can never earn a weight",
    "promising": "LIVE: the lower bound is above zero but there are too few dates or it fails the correction",
    "earned": "LIVE and out of sample: enough dates, the lower bound is above zero after the correction and after an assumed round-trip cost. Changes nothing by itself: it lets the owner review a weight",
}
LIVE_MIN_DATES = 24                   # distinct live as-of dates before a live claim can be `earned`
MIN_DATES_FOR_ANY_VERDICT = 12
ROUND_TRIP_COST = 0.006               # 0.3% each way, the engine's illustrative friction

BIASES = [
    "Universe chosen from today's lists: the stocks scored are those in today's classified Total Market list, watched names and ETFs that have 5 years of history. Names that were delisted, merged or dropped are absent, so winners are over-represented (flatters trend and momentum).",
    "Price returns, not total returns: dividends are missing from every stock and from the benchmark.",
    "Partly in-sample: the 200-day margin and dwell used by the suggestions were picked on this same history, for flip rate and not for returns; this study scores the signals exactly as stored.",
    "Gross of costs and tax: no transaction cost, slippage or tax is deducted from any backtest number. A top-versus-bottom spread is not something a retail investor can trade.",
    "Only about five years, one market regime: monthly dates give roughly 45 observations, so only fairly large effects are detectable (the minimum detectable effect is reported).",
]


def registry() -> dict:
    return {"study_version": STUDY_VERSION, "signal_method": SIGNAL_METHOD, "primary_horizon": PRIMARY_HORIZON, "secondary_horizon": SECONDARY_HORIZON,
            "warmup_sessions": WARMUP_SESSIONS, "min_names_per_date": MIN_NAMES_PER_DATE, "liquidity_floor_rupees": LIQUIDITY_FLOOR_RUPEES, "entry": ENTRY, "exit": EXIT,
            "forward_vol_window": FORWARD_VOL_WINDOW, "bootstrap": BOOTSTRAP, "claims": CLAIMS, "k": K, "alpha": ALPHA, "alpha_per_claim": ALPHA_PER_CLAIM,
            "verdicts": VERDICTS, "live_min_dates": LIVE_MIN_DATES, "min_dates_for_any_verdict": MIN_DATES_FOR_ANY_VERDICT, "round_trip_cost": ROUND_TRIP_COST, "biases": BIASES}


def registry_hash() -> str:
    return hashlib.sha256(json.dumps(registry(), sort_keys=True).encode()).hexdigest()


# --- study-v2: the SAME claims on TOTAL-RETURN outcomes ------------------------------------------------------------------------------------------------------
# Features stay exactly as stored in `signals-v1` (price-based). Only the forward return (and the forward volatility) being scored now includes
# dividends (market/total_return.py, verified on 3,669 NSE dividend events). study-v1 is kept and shown beside it; the scorecard counts versions.
STUDY_VERSION_V2 = "study-v2"


def registry_v2() -> dict:
    r = registry()
    r.update({"study_version": STUDY_VERSION_V2, "supersedes": STUDY_VERSION, "outcome_basis": "total_return", "tr_method": "total-return-v1",
              "reason": "study-v1 scored price returns, which omit dividends. Dividends are paid by the calmer, cheaper stocks, so price-only outcomes understate them. "
                        "Everything else (claims, features, horizons, dates, statistic, correction, ladder) is unchanged."})
    return r


def registry_hash_v2() -> str:
    return hashlib.sha256(json.dumps(registry_v2(), sort_keys=True).encode()).hexdigest()


REGISTRIES = {STUDY_VERSION: (registry, registry_hash), STUDY_VERSION_V2: (registry_v2, registry_hash_v2)}


# --- LIVE claims: scored from signals/forecasts/observations logged AS THEY HAPPENED, once their horizon has elapsed ----------------------------------------
# A separate frozen list with its own hash, so adding live claims never changes the backtest registry above.
LIVE_MIN_NAMES = 30                 # a live cross-section needs at least this many scored names on a date
LIVE_CLAIMS = [
    {"id": "L1_trend_return", "type": "ic", "source": "signal", "feature": "sma200_ratio", "sign": 1, "horizon": 21, "outcome": "return"},
    {"id": "L2_momentum_return", "type": "ic", "source": "signal", "feature": "mom_12_1", "sign": 1, "horizon": 21, "outcome": "return"},
    {"id": "L3_lowvol_return", "type": "ic", "source": "signal", "feature": "vol_252", "sign": -1, "horizon": 21, "outcome": "return"},
    {"id": "L4_vol_persistence", "type": "ic", "source": "signal", "feature": "vol_252", "sign": 1, "horizon": 21, "outcome": "forward_vol"},
    {"id": "L5_kronos_ic", "type": "ic", "source": "forecast", "feature": "predicted_return", "sign": 1, "horizon": 30, "outcome": "return"},
    {"id": "L6_trend_break_held", "type": "event_excess", "source": "suggestion", "kind": "trend_below", "contexts": ["held", "both"], "direction": -1, "horizon": 21},
    {"id": "L8_checklist_return", "type": "ic", "source": "score", "feature": "score", "sign": 1, "horizon": 21, "outcome": "return"},
    {"id": "L9_rank_return", "type": "ic", "source": "rank", "feature": "score", "sign": 1, "horizon": 21, "outcome": "return"},
    {"id": "L7_plan_accounting", "type": "accounting", "source": "plan_leg", "horizon": 21,
     "note": "ACCOUNTING, not skill evidence: what an owner plan's purchases returned against the same money in the market ETF; it says nothing about whether the rules have an edge."},
]


# live-v3 (2026-10-02) adds the stock checklist score as a live claim (L8) and so raises the number of claims corrected for (k). Made before the first live
# outcome of any claim exists (the earliest is due around 2026-11-04), so no result could have influenced it.
# live-v4 (2026-10-02) adds the value / quality / momentum composite (L9) the same way, again before any live outcome exists.
LIVE_VERSION = "live-v4"
LIVE_OUTCOME_BASIS = "total_return"   # live-v1 (price returns) was never used: it was superseded on 2026-10-01, before the first live outcome existed (about 2026-11-02)


def live_registry_hash() -> str:
    return hashlib.sha256(json.dumps({"version": LIVE_VERSION, "outcome_basis": LIVE_OUTCOME_BASIS, "claims": LIVE_CLAIMS, "min_names": LIVE_MIN_NAMES, "live_min_dates": LIVE_MIN_DATES, "alpha": ALPHA,
                                      "k": sum(1 for c in LIVE_CLAIMS if c["type"] != "accounting"), "cost": ROUND_TRIP_COST}, sort_keys=True).encode()).hexdigest()
