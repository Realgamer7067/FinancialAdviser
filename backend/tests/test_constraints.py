"""Effective risk constraints (tolerance + capacity + goal horizon + restrictions)."""

from datetime import date, timedelta

from app.core.single_user import SINGLE_USER_ID
from app.models.user import User
from app.portfolio_intelligence.personal.constraints import compute_effective_constraints, short_horizon_funds
from app.portfolio_intelligence.personal.facts import compute_capacity, compute_tolerance

AGGRESSIVE = {"portfolio_drop_20pct_reaction": "buy_more", "priority": "maximum_growth", "loss_tolerance": "50_plus"}
FACTS = {"monthly_income": "100000", "monthly_essential_expenses": "40000", "emergency_reserve_amount": "400000",
         "emergency_reserve_months_target": "6"}


def cons(tol, facts, short=None, restrictions=None):
    return compute_effective_constraints(tolerance=compute_tolerance(tol), capacity=compute_capacity(facts, []),
                                         short_horizon=short or [], restrictions=restrictions or [])


def test_high_tolerance_with_low_capacity_binds_on_capacity():
    c = cons(AGGRESSIVE, {**FACTS, "emergency_reserve_amount": "50000"})  # reserve covers ~1.25 of 6 months
    assert c["risk_increasing_allowed"] is False
    assert "reserve_shortfall" in c["limiting_factors"]
    tol = next(x for x in c["ceilings"] if x["source"] == "tolerance")
    assert tol["band"] == "aggressive" and tol["blocks_risk_increasing"] is False  # tolerance never overrides capacity


def test_unknown_inputs_restrict_rather_than_permit():
    assert cons({}, FACTS)["limiting_factors"] == ["tolerance_unknown"]
    assert cons(AGGRESSIVE, {"monthly_income": "1"})["limiting_factors"] == ["capacity_unknown"]
    assert cons({}, {})["risk_increasing_allowed"] is False


def test_all_clear_allows_and_short_horizon_and_restrictions_listed():
    ok = cons(AGGRESSIVE, FACTS)
    assert ok["risk_increasing_allowed"] is True and ok["limiting_factors"] == []
    short = short_horizon_funds(
        [{"chain_id": "g1", "description": "Car", "target_date": date.today() + timedelta(days=200)},
         {"chain_id": "g2", "description": "Retire", "target_date": date.today() + timedelta(days=365 * 20)}],
        [{"goal_chain_id": "g1", "amount": __import__("decimal").Decimal("50000"), "status": "active"}])
    assert [s["goal"] for s in short] == ["Car"] and short[0]["claimed"] == "50000"
    c = cons(AGGRESSIVE, FACTS, short, [{"kind": "exclude_sector", "value": "tobacco"}])
    assert set(c["limiting_factors"]) == {"short_horizon_goal_funds", "user_restrictions"}
    assert c["risk_increasing_allowed"] is True  # these restrict WHICH money/assets, not new-money risk itself
    assert "never loosens" in c["note"]


async def test_endpoint_reflects_profile(client, db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db_session.commit()
    r = (await client.get("/api/v4/risk-constraints")).json()
    assert r["risk_increasing_allowed"] is False and r["profile_version"] == 0
    await client.put("/api/v4/profile", json={"expected_version": 0, "facts": {**FACTS, "tolerance_answers": AGGRESSIVE}})
    r2 = (await client.get("/api/v4/risk-constraints")).json()
    assert r2["risk_increasing_allowed"] is True and r2["limiting_factors"] == [] and r2["profile_version"] == 1
    await client.put("/api/v4/profile", json={"expected_version": 1, "facts": {**FACTS, "emergency_reserve_amount": "10000", "tolerance_answers": AGGRESSIVE}})
    r3 = (await client.get("/api/v4/risk-constraints")).json()
    assert r3["risk_increasing_allowed"] is False and r3["limiting_factors"] == ["reserve_shortfall"]
