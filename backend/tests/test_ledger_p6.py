"""P6: statistics, the retrospective study (no look-ahead, power, false positives), the verdict ladder."""

import math

import numpy as np
import pandas as pd
import pytest

from app.portfolio_intelligence.ledger import backtest as BT
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger import stats as S


# --- statistics -----------------------------------------------------------------------------------------------------------------

def test_t_distribution_matches_published_values():
    assert S.t_cdf(2.0, 10) == pytest.approx(0.96331, abs=2e-5)
    assert S.t_cdf(0.0, 7) == pytest.approx(0.5)
    assert S.t_cdf(-1.3, 20) == pytest.approx(1 - S.t_cdf(1.3, 20))
    assert S.t_ppf(0.975, 10) == pytest.approx(2.2281, abs=1e-3)
    assert S.t_ppf(0.975, 44) == pytest.approx(2.0154, abs=1e-3)
    assert S.t_ppf(0.99375, 44) == pytest.approx(2.6045, abs=2e-3)       # the Bonferroni critical value at K=4, about 45 dates
    assert S.t_ppf(0.975, 100000) == pytest.approx(1.95996, abs=1e-3)    # approaches the normal


def test_spearman_handles_gaps_ties_and_degenerate_input():
    x = list(range(30))
    assert S.spearman(x, [v * 2 for v in x]) == pytest.approx(1.0)
    assert S.spearman(x, [-v for v in x]) == pytest.approx(-1.0)
    assert S.spearman(x[:5], x[:5]) is None                                # fewer than 10 pairs
    assert S.spearman([1.0] * 20, list(range(20))) is None                 # no variation: no correlation, not zero
    y = [float("nan") if i % 3 == 0 else float(i) for i in x]
    assert S.spearman(x, y) == pytest.approx(1.0)


def test_summary_and_interval_over_dates():
    vals = [0.05, 0.02, 0.08, -0.01, 0.04, 0.06, 0.03, 0.07]
    s = S.summarize_dates(vals, 0.05)
    assert s["n_dates"] == 8 and s["mean_ic"] == pytest.approx(np.mean(vals))
    assert s["ci"][0] < s["mean_ic"] < s["ci"][1] and s["t"] == pytest.approx(s["mean_ic"] / (np.std(vals, ddof=1) / math.sqrt(8)))
    wide = S.summarize_dates(vals, 0.0125)
    assert wide["ci"][0] < s["ci"][0] and wide["ci"][1] > s["ci"][1]                # a stricter alpha gives a wider interval
    assert S.summarize_dates([0.1, 0.2], 0.05)["ci"] is None


def test_bootstrap_interval_is_reproducible_and_brackets_the_mean():
    rng = np.random.default_rng(1)
    vals = list(rng.normal(0.04, 0.12, 45))
    a = S.bootstrap_ci(vals, 0.0125, 2000, seed=5)
    assert a == S.bootstrap_ci(vals, 0.0125, 2000, seed=5) and a[0] < np.mean(vals) < a[1]
    assert S.bootstrap_ci([0.1, 0.2], 0.05, 100, 1) is None


def test_minimum_detectable_ic_shrinks_with_more_dates():
    small = S.minimum_detectable_ic(0.12, 45, R.ALPHA_PER_CLAIM)
    big = S.minimum_detectable_ic(0.12, 180, R.ALPHA_PER_CLAIM)
    assert big < small and 0.05 < small < 0.12 and S.minimum_detectable_ic(None, 45, 0.01) is None


def summ(mean, lo, hi, n=45):
    return {"n_dates": n, "mean_ic": mean, "ci": None if lo is None else [lo, hi]}


def test_the_verdict_ladder():
    v = lambda s, **k: S.verdict(s, mde=k.pop("mde", 0.04), evidence=k.pop("evidence", "backtest"), alpha_ok=True, min_dates=12, live_min_dates=24, **k)
    assert v(summ(None, None, None, 0)) == "no_data"
    assert v(summ(0.1, 0.0, 0.2, 8)) == "too_early"
    assert v(summ(-0.08, -0.12, -0.03)) == "negative"
    assert v(summ(0.06, 0.02, 0.10)) == "backtest_suggestive"                      # the best a backtest can ever say
    assert v(summ(0.01, -0.03, 0.05), mde=0.04) == "no_evidence"
    assert v(summ(0.01, -0.07, 0.09), mde=0.11) == "underpowered"                # "no evidence" would overclaim: this study could not have seen a small effect
    assert v(summ(0.06, 0.02, 0.10), evidence="live", net_lower=0.01) == "earned"
    assert v(summ(0.06, 0.02, 0.10, 20), evidence="live", net_lower=0.01) == "promising"        # too few live dates
    assert v(summ(0.06, 0.02, 0.10), evidence="live", net_lower=-0.01) == "promising"           # does not survive costs
    assert v(summ(0.06, 0.02, 0.10), evidence="live", net_lower=None) == "promising"
    assert "earned" not in {v(summ(0.2, 0.15, 0.25), evidence="backtest", net_lower=0.1)}        # a backtest can NEVER earn


def test_the_registry_is_frozen_and_hashed():
    h = R.registry_hash()
    assert h == "0d94bfdddb822762470496cadc812e90940267d80d9e62854a249eb638787896"            # changing the design requires a new study version AND this constant
    assert R.K == 4 and R.ALPHA_PER_CLAIM == pytest.approx(0.0125) and R.PRIMARY_HORIZON == 21 and R.STUDY_VERSION == "study-v1"
    assert len(R.BIASES) >= 5 and set(R.VERDICTS) >= {"earned", "backtest_suggestive", "underpowered"}


# --- the study on synthetic markets -------------------------------------------------------------------------------------------------

def market(n_names=150, sessions=900, seed=0, kappa=0.0, sigmas=True):
    """Daily returns = own volatility * noise (+ a drift that continues trailing 12-1 month leaders when kappa > 0). Volume is large, so liquidity passes."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=sessions)
    sig = rng.uniform(0.008, 0.03, n_names) if sigmas else np.full(n_names, 0.015)
    close = np.empty((sessions, n_names))
    close[0] = 100.0
    for t in range(1, sessions):
        drift = np.zeros(n_names)
        if kappa and t > 252:
            mom = close[t - 21] / close[t - 252] - 1.0
            drift = kappa * (pd.Series(mom).rank(pct=True).to_numpy() - 0.5)
        close[t] = close[t - 1] * np.exp(rng.normal(0.0002, 1.0, n_names) * sig + drift)
    cols = [f"s{i}" for i in range(n_names)]
    return pd.DataFrame(close, index=idx, columns=cols), pd.DataFrame(np.full((sessions, n_names), 5e7), index=idx, columns=cols)


def claim(res, cid):
    return next(c for c in res["claims"] if c["id"] == cid)


def test_a_planted_momentum_effect_is_detected_and_the_risk_claim_is_confirmed():
    c, v = market(seed=1, kappa=0.0012)
    res = BT.run_study(c, v)
    mom = claim(res, "C2_momentum_return")
    assert mom["primary"]["mean_ic"] > 0.04 and mom["verdict"] == "backtest_suggestive", mom["primary"]
    vol = claim(res, "C4_vol_persistence")
    assert vol["primary"]["mean_ic"] > 0.5 and vol["verdict"] == "backtest_suggestive"                      # each stock really does have its own volatility
    assert claim(res, "C3_lowvol_return")["verdict"] in ("no_evidence", "underpowered")                     # volatility was not given any return effect
    assert mom["top_quintile_minus_universe"]["gross_of_costs"] is True and "secondary_63" in mom and mom["secondary_63"]["descriptive_only"] is True


def test_with_no_planted_effect_the_return_claims_are_not_declared_significant():
    flagged = 0
    for seed in range(6):
        c, v = market(seed=100 + seed, kappa=0.0)
        res = BT.run_study(c, v)
        flagged += sum(1 for cid in ("C1_trend_return", "C2_momentum_return", "C3_lowvol_return") if claim(res, cid)["verdict"] == "backtest_suggestive")
    assert flagged <= 1, f"{flagged} false positives in 18 tests at a 1.25% level each"                    # expected 0.2; a handful would mean the statistics are broken
    assert claim(res, "C4_vol_persistence")["verdict"] == "backtest_suggestive"                           # the planted risk persistence is still found


def test_the_study_reports_how_small_an_effect_it_could_have_seen():
    c, v = market(seed=3)
    res = BT.run_study(c, v)
    m = claim(res, "C2_momentum_return")["primary"]
    assert m["minimum_detectable_ic"] is not None and 0 < m["minimum_detectable_ic"] < 0.5 and m["n_dates"] >= 15
    assert res["names_per_date"]["min"] >= R.MIN_NAMES_PER_DATE and res["registry_hash"] == R.registry_hash() and len(res["biases"]) >= 5


def test_no_look_ahead_features_ignore_the_future_and_outcomes_ignore_the_past():
    c, v = market(n_names=20, sessions=700, seed=9)
    base = BT.feature_frames(c, v, horizon=21, vol_window=21)
    t = c.index[400]
    future = c.copy()
    future.iloc[401:] *= 1.37                                                           # change everything AFTER t
    f2 = BT.feature_frames(future, v, horizon=21, vol_window=21)
    for k in ("sma200_ratio", "mom_12_1", "vol_252", "liquidity"):
        pd.testing.assert_series_equal(base[k].loc[t], f2[k].loc[t])                       # features at t cannot see it
    assert not base["fwd_21"].loc[t].equals(f2["fwd_21"].loc[t])                          # outcomes do
    past = c.copy()
    past.iloc[:401] *= 1.5                                                              # change everything up to and INCLUDING t
    f3 = BT.feature_frames(past, v, horizon=21, vol_window=21)
    pd.testing.assert_series_equal(base["fwd_21"].loc[t], f3["fwd_21"].loc[t])                # the outcome starts at the NEXT close: the past cannot move it
    entry_moved = c.copy()
    entry_moved.iloc[401] *= 1.1                                                         # the entry close itself
    assert not base["fwd_21"].loc[t].equals(BT.feature_frames(entry_moved, v, horizon=21, vol_window=21)["fwd_21"].loc[t])


def test_rebalance_dates_are_month_ends_with_history_behind_and_future_ahead():
    idx = pd.bdate_range("2021-01-04", periods=900)
    ds = BT.rebalance_dates(idx, warmup=253, tail=64)
    pos = {d: i for i, d in enumerate(idx)}
    assert all(pos[d] >= 252 and pos[d] + 64 < len(idx) for d in ds) and len(ds) > 20
    assert all((idx[pos[d] + 1].month != d.month) for d in ds)                            # each really is the last session of its month
    assert len({(d.year, d.month) for d in ds}) == len(ds)


def test_too_few_stocks_on_a_date_skips_it_rather_than_scoring_it():
    c, v = market(n_names=60, sessions=700, seed=4)
    res = BT.run_study(c, v)
    assert res["dates"]["n"] == 0 and len(res["dates"]["skipped_for_too_few_names"]) > 5
    assert all(cl["verdict"] in ("no_data", "too_early") for cl in res["claims"])


def test_study_v2_is_frozen_and_only_the_outcome_basis_differs():
    assert R.registry_hash_v2() == "f1ea1c51e2b17f20458c860a0809ec5c4d41c5e78a22cae28d432b69367d2f7c"
    v1, v2 = R.registry(), R.registry_v2()
    assert v2["study_version"] == "study-v2" and v2["outcome_basis"] == "total_return" and v2["supersedes"] == "study-v1"
    assert {k: v2[k] for k in v1 if k != "study_version"} == {k: v1[k] for k in v1 if k != "study_version"}      # claims, horizons, dates, statistic, ladder: identical
    assert R.registry_hash() == "0d94bfdddb822762470496cadc812e90940267d80d9e62854a249eb638787896"                # v1 untouched


def test_v2_scores_total_return_outcomes_while_features_stay_price_based():
    c, v = market(seed=11, kappa=0.0)
    tr = c.copy()
    tr.iloc[:, :60] = tr.iloc[:, :60] * np.linspace(1.0, 1.4, len(tr))[:, None]            # the first 60 stocks pay a steady dividend: their TOTAL return runs ahead of price
    a = BT.feature_frames(c, v, horizon=21, vol_window=21)
    b = BT.feature_frames(c, v, horizon=21, vol_window=21, outcome=tr)
    for k in ("sma200_ratio", "mom_12_1", "vol_252", "liquidity"):
        pd.testing.assert_frame_equal(a[k], b[k])                                           # signals are untouched
    t = c.index[500]
    assert float(b["fwd_21"].loc[t].iloc[:60].mean()) > float(a["fwd_21"].loc[t].iloc[:60].mean())              # outcomes include the dividends
    r1, r2 = BT.run_study(c, v), BT.run_study(c, v, tr)
    assert r1["study_version"] == "study-v1" and r1["outcome_basis"] == "price" and r2["study_version"] == "study-v2" and r2["outcome_basis"] == "total_return"
    assert r1["registry_hash"] == R.registry_hash() and r2["registry_hash"] == R.registry_hash_v2()
