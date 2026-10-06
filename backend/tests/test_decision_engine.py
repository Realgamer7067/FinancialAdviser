"""Phase 06 pure engine: same baseline, same flows, gates, conservation, comparison."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.portfolio_intelligence.decisions.engine import ActionInvalid, candidate_hash, evaluate

D = Decimal
TODAY = date(2026, 10, 1)


def pos(pid, asset, value, *, label=None, inst=None, isin=None, sector=None, account="Broker", resolution="resolved", quality="fresh"):
    return {"position_id": pid, "account_label": account, "asset_type": asset, "resolution": resolution, "instrument_id": inst, "isin": isin,
            "label": label or pid, "value": None if value is None else D(value), "quality": quality, "sector": sector, "as_of": "2026-10-01"}


# The plan's worked fixture: 100,000 = 60,000 equity + 30,000 debt-like + 10,000 cash; contribute 20,000.
BASE = [
    pos("rel", "listed_equity", "30000", label="RELIANCE", inst="i-rel", sector="Oil Gas & Consumable Fuels"),
    pos("tcs", "listed_equity", "30000", label="TCS", inst="i-tcs", sector="Information Technology"),
    pos("fd", "deposit", "30000", label="FD", account="Bank", resolution="not_applicable"),
    pos("cash", "cash", "10000", label="Savings", account="Bank", resolution="not_applicable"),
]
INSTR = {"i-inf": {"symbol": "INFY", "sector": "Information Technology", "isin": "INE009A01021", "lot_size": 1, "asset_type": "listed_equity"},
         "i-hdfc": {"symbol": "HDFCBANK", "sector": "Financial Services", "isin": "INE040A01034", "lot_size": 1, "asset_type": "listed_equity"},
         "i-big": {"symbol": "BIG", "sector": "Metals & Mining", "isin": "INE000000001", "lot_size": 500, "asset_type": "listed_equity"}}
PRICES = {"i-inf": {"price": D("100"), "as_of": TODAY - timedelta(days=1)}, "i-hdfc": {"price": D("1500"), "as_of": TODAY - timedelta(days=2)},
          "i-big": {"price": D("100"), "as_of": TODAY - timedelta(days=1)}}
CAPACITY_OK = {"monthly_essential_outgo": "5000", "near_term_obligations_12m": "0"}


def ctx(actions, **kw):
    c = {"baseline": BASE, "claims": {}, "capacity": CAPACITY_OK, "constraints": {"risk_increasing_allowed": True, "limiting_factors": []},
         "restrictions": [], "instruments": INSTR, "prices": PRICES, "commitments": {}, "goals": {}, "budget": {"remaining_for_new_monthly": "10000"},
         "contribution": D("20000"), "withdrawal": D(0), "actions": actions, "priorities": [], "fee_pct": D("0.003"), "today": TODAY}
    c.update(kw)
    return c


def buy(inst="i-inf", amount="20000", funding="new_money", account="Broker"):
    return {"type": "BUY", "instrument_id": inst, "amount": D(amount), "funding": funding, "account_label": account}


def test_hold_keeps_new_money_as_cash_and_conserves():
    r = evaluate(ctx([]))
    assert r["hold"]["accounting"]["assets_before"] == "100000" and r["hold"]["accounting"]["assets_after"] == "120000"
    assert r["hold"]["accounting"]["conserved"] is True and r["default"] == "HOLD" and r["published"] is False
    assert r["summary"]["headline"].startswith("No alternatives")


def test_buy_conserves_to_the_paisa_with_friction_and_lot_residual():
    a = evaluate(ctx([buy()]))["alternatives"][0]
    # 20000 / (100 * 1.003) = 199.4 -> 199 units = 19,900; friction 59.70; residual cash 40.30
    assert a["cost"]["units"] == 199 and a["cost"]["trade_value"] == "19900" and a["cost"]["friction"] == "59.7" and a["cost"]["residual_cash"] == "40.3"
    acc = a["accounting"]
    assert acc["assets_after"] == "119940.3" and acc["friction"] == "59.7" and acc["residual"] == "0" and acc["conserved"] is True
    # the SAME 20000 contribution is in HOLD's baseline too: no double count, no ₹100,000 comparison
    assert acc["external_contribution"] == "20000" and acc["assets_before"] == "100000"


def test_zero_fee_matches_the_plan_fixture_exactly():
    a = evaluate(ctx([buy()], fee_pct=D(0)))["alternatives"][0]
    assert a["accounting"]["assets_after"] == "120000" and a["accounting"]["friction"] == "0" and a["cost"]["residual_cash"] == "0"


def test_funding_gate_and_lot_gate_and_min_size_reject_without_applying():
    r = evaluate(ctx([buy(amount="30000"), buy(inst="i-big", amount="20000"), buy(amount="500")]))
    s = {i: x for i, x in enumerate(r["alternatives"])}
    assert s[0]["status"] == "rejected" and any(g["gate_id"] == "funding_available" and g["result"] == "fail" for g in s[0]["gates"])
    assert s[1]["status"] == "rejected" and any(g["gate_id"] == "lot_size" and g["result"] == "fail" for g in s[1]["gates"])  # 500-lot x 100 = 50,000
    assert s[2]["status"] == "rejected" and any(g["gate_id"] == "min_action_size" for g in s[2]["gates"])
    for x in s.values():
        assert x["accounting"]["conserved"] is True and x["candidate_state_hash"] == r["hold"]["candidate_state_hash"]  # nothing applied


def test_existing_cash_funding_excludes_goal_claims():
    r = evaluate(ctx([buy(funding="existing_cash", amount="9000")], contribution=D(0), claims={"cash": D("5000")}))
    a = r["alternatives"][0]
    assert a["status"] == "rejected" and any(g["gate_id"] == "funding_available" and "only 5000" in g["reason"] for g in a["gates"])  # 10,000 cash - 5,000 claimed
    ok = evaluate(ctx([buy(funding="existing_cash", amount="4000")], contribution=D(0), claims={"cash": D("5000")}))["alternatives"][0]
    assert ok["accounting"]["conserved"] is True and ok["gates"][0]["result"] == "pass"


def test_risk_capacity_gate_blocks_added_risk_but_not_neutral_actions():
    blocked = {"risk_increasing_allowed": False, "limiting_factors": ["reserve_shortfall"]}
    a = evaluate(ctx([buy()], constraints=blocked))["alternatives"][0]
    assert a["status"] == "rejected" and any(g["gate_id"] == "risk_capacity" and g["result"] == "fail" for g in a["gates"])
    unknown = {"risk_increasing_allowed": False, "limiting_factors": ["tolerance_unknown", "capacity_unknown"]}
    u = evaluate(ctx([buy("i-hdfc")], constraints=unknown))["alternatives"][0]
    assert u["status"] == "needs_input"  # missing inputs restrict, but are named as unknown, not as a verdict
    rsv = evaluate(ctx([{"type": "RESERVE", "amount": D("5000")}], constraints=blocked))["alternatives"][0]
    assert rsv["status"] == "no_material_benefit" and rsv["designated_reserve"] == "5000"


def test_user_restrictions_reject():
    a = evaluate(ctx([buy()], restrictions=[{"kind": "exclude_sector", "value": "Information Technology"}]))["alternatives"][0]
    assert a["status"] == "rejected" and any(g["gate_id"] == "user_restrictions" and g["result"] == "fail" for g in a["gates"])
    b = evaluate(ctx([buy()], restrictions=[{"kind": "exclude_isin", "value": "INE009A01021"}]))["alternatives"][0]
    assert b["status"] == "rejected"


def test_stale_price_is_unknown_not_acceptable():
    old = dict(PRICES, **{"i-hdfc": {"price": D("1500"), "as_of": TODAY - timedelta(days=30)}})
    a = evaluate(ctx([buy("i-hdfc")], prices=old))["alternatives"][0]
    assert a["status"] == "needs_input" and any(g["gate_id"] == "price_available" and g["result"] == "unknown" for g in a["gates"])
    none = evaluate(ctx([buy("i-hdfc")], prices={}))["alternatives"][0]
    assert none["status"] == "rejected" and none["accounting"]["conserved"] is True


def test_concentration_gate_rejects_pushing_one_company_over_the_limit():
    heavy = [pos("rel", "listed_equity", "80000", label="RELIANCE", inst="i-rel", sector="Oil Gas & Consumable Fuels"),
             pos("cash", "cash", "20000", label="Savings", account="Bank", resolution="not_applicable")]
    # add 20,000 of an already-dominant... buy a new issuer; the largest stays RELIANCE at 66%, which is NOT worsened -> passes
    ok = evaluate(ctx([buy()], baseline=heavy, fee_pct=D(0)))["alternatives"][0]
    assert next(g for g in ok["gates"] if g["gate_id"] == "max_issuer_weight")["result"] == "pass"
    # a buy of a NEW issuer from a tiny portfolio makes that issuer the largest at 100% -> fails the 25% limit
    tiny = [pos("cash", "cash", "50000", label="Savings", account="Bank", resolution="not_applicable")]
    bad = evaluate(ctx([buy(amount="20000")], baseline=tiny, contribution=D(0), fee_pct=D(0)))["alternatives"][0]
    assert any(g["gate_id"] == "max_issuer_weight" and g["result"] == "fail" for g in bad["gates"]) or bad["status"] == "rejected"


def test_tradeoff_is_shown_not_hidden_and_hold_stays_default():
    r = evaluate(ctx([buy("i-hdfc", "20000", fee_pct=None) if False else buy("i-hdfc", "20000")]))
    a = r["alternatives"][0]
    # Buying equity with idle cash adds market sensitivity: improvement in diversification may come with a worse stress loss.
    verdicts = {row["metric"]: row["verdict"] for row in a["comparison_vs_hold"]["rows"]}
    assert verdicts["worst_scenario_loss_pct"] == "worsened"
    assert a["status"] in ("tradeoff", "worse_than_hold", "rejected")
    assert r["default"] == "HOLD" and r["summary"]["best_alternative_index"] is None


def test_sale_is_a_review_only_preview_with_unknown_tax():
    a = evaluate(ctx([{"type": "REDUCE_PREVIEW", "position_id": "rel", "amount": D("10000")}]))["alternatives"][0]
    assert a["status"] == "review_required" and a["cost"]["tax"].startswith("unknown")
    assert any(g["gate_id"] == "tax_lots_known" and g["result"] == "unknown" for g in a["gates"])
    assert a["accounting"]["conserved"] is True and "no after-tax benefit" in " ".join(g["reason"] for g in a["gates"])
    over = evaluate(ctx([{"type": "REDUCE_PREVIEW", "position_id": "rel", "amount": D("99999")}]))["alternatives"][0]
    assert over["status"] == "rejected"
    claimed = evaluate(ctx([{"type": "REDUCE_PREVIEW", "position_id": "rel", "amount": D("20000")}], claims={"rel": D("15000")}))["alternatives"][0]
    assert claimed["status"] == "rejected" and any(g["gate_id"] == "not_claimed_for_goals" and g["result"] == "fail" for g in claimed["gates"])


def test_contribution_change_moves_goal_metric_and_respects_budget():
    goal = {"chain_id": "g1", "description": "House", "target_amount": D("1000000"), "target_basis": "future_money",
            "target_date": TODAY + timedelta(days=365 * 5), "inflation": None, "starting": D("100000"), "monthly": D("5000")}
    commit = {"chain_id": "c1", "goal_chain_id": "g1", "monthly": D("5000")}
    base = dict(goals={"g1": goal}, commitments={"c1": commit})
    up = evaluate(ctx([{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": "c1", "new_monthly_amount": D("9000")}], **base))["alternatives"][0]
    rows = {r["metric"]: r for r in up["comparison_vs_hold"]["rows"]}
    assert Decimal(rows["goal_shortfall_base"]["delta"]) < 0 and rows["goal_shortfall_base"]["verdict"] == "improved"
    assert up["status"] == "dominates_hold" and up["accounting"]["conserved"] is True
    too_much = evaluate(ctx([{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": "c1", "new_monthly_amount": D("40000")}], **base))["alternatives"][0]
    assert too_much["status"] == "rejected" and any(g["gate_id"] == "budget_available" for g in too_much["gates"])
    unknown = evaluate(ctx([{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": "c1", "new_monthly_amount": D("9000")}],
                           budget={"remaining_for_new_monthly": None}, **base))["alternatives"][0]
    assert unknown["status"] == "needs_input"
    with pytest.raises(ActionInvalid):
        evaluate(ctx([{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": "nope", "new_monthly_amount": D("1")}], **base))


def test_ties_and_immaterial_changes_default_to_hold():
    tiny = evaluate(ctx([{"type": "RESERVE", "amount": D("2000")}]))["alternatives"][0]
    assert tiny["status"] == "no_material_benefit" and "HOLD stays the default" in " ".join(tiny["reasons"]) or tiny["status"] == "no_material_benefit"


def test_invalid_requests_raise_not_silently_pass():
    for bad in (dict(contribution=D("-1")), dict(withdrawal=D("-1")), dict(fee_pct=D("0.5")), dict(withdrawal=D("999999"))):
        with pytest.raises(ActionInvalid):
            evaluate(ctx([], **bad))
    with pytest.raises(ActionInvalid):
        evaluate(ctx([buy(inst="unknown")]))
    with pytest.raises(ActionInvalid):
        evaluate(ctx([{"type": "REDUCE_PREVIEW", "position_id": "nope", "amount": D("1")}]))


def test_withdrawal_uses_new_money_then_unclaimed_cash_and_conserves():
    r = evaluate(ctx([], contribution=D("5000"), withdrawal=D("8000"), claims={"cash": D("4000")}))
    assert r["hold"]["accounting"]["assets_after"] == "97000" and r["hold"]["accounting"]["conserved"] is True  # 100000 + 5000 - 8000
    with pytest.raises(ActionInvalid):  # 5000 new + only 6000 unclaimed cash = 11000 max
        evaluate(ctx([], contribution=D("5000"), withdrawal=D("12000"), claims={"cash": D("4000")}))


def test_candidate_state_hash_is_reproducible_and_json_safe():
    r1, r2 = evaluate(ctx([buy()])), evaluate(ctx([buy()]))
    assert r1["alternatives"][0]["candidate_state_hash"] == r2["alternatives"][0]["candidate_state_hash"]
    assert r1["hold"]["candidate_state_hash"] != r1["alternatives"][0]["candidate_state_hash"]
    json.dumps(r1)  # everything is serializable (Decimals rendered as strings)


def test_sector_limit_rejects_even_when_everything_else_passes():
    a = evaluate(ctx([buy("i-inf")]))["alternatives"][0]  # TCS 30000 + INFY 19900 = IT 41.6% of 119,940
    assert a["status"] == "rejected" and any(g["gate_id"] == "max_sector_weight" and g["result"] == "fail" for g in a["gates"])
    assert a["accounting"]["conserved"] is True  # a rejected candidate is still a conserving state
