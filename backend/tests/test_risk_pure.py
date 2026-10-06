"""Phase 05 pure risk modules: exposures, liquidity, stress, volatility."""

import math
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.portfolio_intelligence.risk.exposure import compute_exposures, compute_liquidity
from app.portfolio_intelligence.risk.stress import CATALOG, resolve_scenario, run_scenario
from app.portfolio_intelligence.risk.volatility import portfolio_volatility

D = Decimal


def pos(pid, asset, value, *, label=None, resolution="resolved", inst=None, isin=None, sector=None, account="A", quality="fresh"):
    return {"position_id": pid, "account_label": account, "asset_type": asset, "resolution": resolution, "instrument_id": inst,
            "isin": isin, "label": label or pid, "value": None if value is None else D(value), "quality": quality,
            "sector": sector, "as_of": "2026-10-01"}


PORTFOLIO = [
    pos("rel", "listed_equity", "40000", inst="i1", sector="Oil Gas & Consumable Fuels", label="RELIANCE"),
    pos("hdfc", "listed_equity", "30000", inst="i2", sector="Financial Services", label="HDFCBANK"),
    pos("odd", "listed_equity", "10000", resolution="unresolved", label="MYSTERY", isin="INE999Z01011", account="B"),
    pos("etf", "etf", "10000", label="NIFTYBEES", account="B"),
    pos("cash", "cash", "5000", label="Cash", account="B"),
    pos("fd", "deposit", "5000", label="FD", account="B"),
    pos("coin", "gold", None, label="Gold coin", account="B"),
]


def test_buckets_reconcile_to_known_total_and_unknown_stays_unknown():
    r = compute_exposures(PORTFOLIO)
    rec = r["reconciliation"]
    assert rec["asset_classes_sum"] == rec["sectors_sum"] == rec["accounts_sum"] == rec["known_total"] == "100000"
    mix = r["asset_mix"]
    assert mix["unvalued_positions"] == 1 and mix["direct_equity_share"] == "0.8000"
    assert mix["equity_share_upper_bound"] == "0.9000"  # the ETF might hold equity: a range, not a guess
    assert mix["classes"]["equity"]["classification_basis"] == {"instrument_master": "70000", "user_declared": "10000"}
    buckets = {b["bucket"]: b["weight"] for b in r["sector"]["buckets"]}
    assert buckets["fund_lookthrough_unknown"] == "0.1000" and buckets["unclassified_equity"] == "0.1000"
    assert r["sector"]["unknown_weight"] == "0.2000"
    assert any("not looked through" in w for w in mix["warnings"])


def test_issuer_concentration_over_identified_slice_with_coverage():
    r = compute_exposures(PORTFOLIO)["issuer_concentration"]
    assert r["status"] == "ready" and r["largest_issuer"] == "RELIANCE" and r["largest_issuer_weight"] == "0.4000"
    assert r["coverage_fraction"] == "0.8000"  # all direct equity (incl. the unresolved ISIN) is identified; funds/cash are not
    # slice weights 40/30/10 of 80 -> HHI = .25 + .140625 + .015625 = 0.40625
    assert r["herfindahl_over_identified"] == "0.4063" and r["effective_positions_over_identified"] == "2.46"
    assert r["top5_weight"] == "0.8000"
    assert any("only the identified" in w for w in r["warnings"])


def test_same_issuer_in_two_accounts_aggregates():
    p = [pos("a", "listed_equity", "100", inst="i1", label="X", account="A"), pos("b", "listed_equity", "300", inst="i1", label="X", account="B")]
    r = compute_exposures(p)["issuer_concentration"]
    assert len(r["issuers"]) == 1 and r["issuers"][0]["weight"] == "1.0000" and r["issuers"][0]["accounts"] == ["A", "B"]


def test_no_equity_means_insufficient_not_zero():
    r = compute_exposures([pos("c", "cash", "100")])
    assert r["issuer_concentration"]["status"] == "insufficient_data"
    assert compute_exposures([])["asset_mix"]["status"] == "insufficient_data"


def test_liquidity_cash_after_claims_and_unknowns():
    cap = {"monthly_essential_outgo": "10000", "near_term_obligations_12m": "30000"}
    liq = compute_liquidity(PORTFOLIO, {"cash": D("2000")}, cap)
    assert liq["accessible_cash_after_claims"] == "3000" and liq["months_of_outgo"] == "0.3"
    assert liq["twelve_month_need"] == "150000" and liq["status"] == "ready"
    assert compute_liquidity(PORTFOLIO, {}, {"monthly_essential_outgo": None})["status"] == "insufficient_data"
    assert compute_liquidity(PORTFOLIO, {}, {"monthly_essential_outgo": "0"})["months_of_outgo"] is None  # undefined, not infinite
    assert compute_liquidity(PORTFOLIO, {}, {"monthly_essential_outgo": "10000", "near_term_obligations_12m": None})["status"] == "estimated"


# --- stress -------------------------------------------------------------------------

def test_broad_equity_scenario_ledger_reconciles_and_gaps_reported():
    s = run_scenario(resolve_scenario({"id": "equity_broad_-20"}), PORTFOLIO)
    # equity 80000 * -20% = -16000; cash/deposit 10000 modeled at 0; ETF 10000 unmodeled; gold unvalued
    assert s["modeled_change"] == "-16000.00" and s["modeled_value"] == "90000" and s["reconciles"] is True
    assert s["modeled_change_pct_of_modeled_value"] == "-0.1778" and s["modeled_change_pct_of_known_total"] == "-0.1600"
    assert s["outside_coverage"]["value"] == "10000" and s["outside_coverage"]["unvalued_positions"] == 1
    reasons = {r["holding"]: r["reason"] for r in s["ledger"] if not r["modeled"]}
    assert "no look-through" in reasons["NIFTYBEES"] and "no value" in reasons["Gold coin"]
    assert "not a forecast" in s["label"]


def test_sector_scenario_shocks_only_verified_members_and_never_stacks():
    s = run_scenario(resolve_scenario({"id": "sector_financial_services_-20"}), PORTFOLIO)
    assert s["modeled_change"] == "-6000.00"  # HDFCBANK only
    by = {r["holding"]: r for r in s["ledger"]}
    assert by["RELIANCE"]["modeled_return"] == "0" and by["HDFCBANK"]["modeled_return"] == "-0.2"
    assert by["MYSTERY"]["modeled"] is False and "unverified" in by["MYSTERY"]["reason"]  # unmatched equity: gap, not flat
    assert s["outside_coverage"]["value"] == "20000"  # unmatched equity 10000 + ETF 10000


def test_custom_scenarios_bounded_and_unsupported_refused():
    assert resolve_scenario({"kind": "broad_equity", "shock": "-0.35"})["shock"] == "-0.35"
    for bad in ({"kind": "broad_equity", "shock": "0.2"}, {"kind": "broad_equity", "shock": "-0.9"}, {"kind": "broad_equity", "shock": "NaN"},
                {"kind": "sector", "shock": "-0.1"}, {"kind": "oil", "shock": "-0.1"}, {"id": "nope"}, {"id": "rates_+150bp"}):
        with pytest.raises(ValueError):
            resolve_scenario(bad)
    assert {c["status"] for c in CATALOG if c["kind"] in ("rates", "oil", "fx")} == {"unsupported"}


# --- volatility -----------------------------------------------------------------------

def series(n, seed, start=date(2024, 1, 1), drift=0.0003, vol=0.01):
    rnd = random.Random(seed)
    out, price, d = [], 100.0, start
    for _ in range(n):
        out.append((d, price))
        price *= 1.0 + rnd.gauss(drift, vol)
        d += timedelta(days=1)
    return out


def test_volatility_ready_with_enough_aligned_history_and_coverage():
    v = portfolio_volatility({"a": series(400, 1), "b": series(400, 2)}, {"a": D(60), "b": D(40)}, D(100))
    assert v["status"] == "ready" and v["observations"] == 399 and v["coverage_fraction"] == "1.0000"
    assert 0.05 < v["annualized_volatility"] < 0.4 and -1 < v["max_drawdown_in_window"] <= 0
    assert "not a forecast" in " ".join(v["warnings"])


def test_volatility_suppressed_when_history_or_coverage_insufficient():
    short = portfolio_volatility({"a": series(100, 1)}, {"a": D(100)}, D(100))
    assert short["status"] == "insufficient_data" and "annualized_volatility" not in short
    # one holding has history but covers only 50% of value -> no precise figure
    half = portfolio_volatility({"a": series(400, 1)}, {"a": D(50)}, D(100))
    assert half["status"] == "insufficient_data" and half["coverage_fraction"] == "0.5000" and "annualized_volatility" not in half
    # misaligned windows: common dates too few
    mis = portfolio_volatility({"a": series(400, 1, date(2020, 1, 1)), "b": series(400, 2, date(2025, 1, 1))}, {"a": D(50), "b": D(50)}, D(100))
    assert mis["status"] == "insufficient_data" and "aligned daily returns" in mis["reason"]
    assert portfolio_volatility({}, {}, D(0))["status"] == "insufficient_data"


def test_volatility_ignores_bad_prices_and_is_deterministic():
    s = series(400, 3)
    s[10] = (s[10][0], float("nan"))
    s[20] = (s[20][0], 0.0)
    a = portfolio_volatility({"a": s}, {"a": D(100)}, D(100))
    b = portfolio_volatility({"a": s}, {"a": D(100)}, D(100))
    assert a == b and a["status"] in ("ready", "insufficient_data") and not math.isnan(a.get("annualized_volatility", 0.0))
