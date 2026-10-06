"""Phase 04b: goals, allocation claims, commitments, projections."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument
from app.models.user import User
from app.portfolio_intelligence.goals.projection import project_goal

ISIN = "INE002A01018"
TODAY = date.today()
FUTURE = (TODAY + timedelta(days=365 * 5)).isoformat()


async def _seed(db):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    db.add(Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=ISIN))
    await db.commit()


async def acct(client, label):
    return (await client.post("/api/v4/accounts", json={"label": label})).json()


def eq(value="100000", units="10", isin=ISIN):
    return {"asset_type": "listed_equity", "isin": isin, "units": units, "value": value, "valuation_date": TODAY.isoformat()}


async def imp(client, a, rows):
    r = await client.post("/api/v4/imports/manual/confirm", json={
        "account_id": a["id"], "rows": rows, "idempotency_key": str(uuid.uuid4()), "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text


def goal_body(**kw):
    b = {"description": "House", "target_amount": "1000000", "target_basis": "future_money", "target_date": FUTURE,
         "priority": 1, "flexibility": "fixed"}
    b.update(kw)
    return b


async def mk_goal(client, **kw):
    r = await client.post("/api/v4/goals", json=goal_body(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def positions(client):
    return (await client.get("/api/v4/state/current")).json()["state"]["positions"]


async def claim(client, goal, position_id, amount):
    """position_id: a position id, or an account label; ids change whenever the twin is rebuilt,
    so labels are resolved against the CURRENT snapshot."""
    pos = await positions(client)
    if position_id is None or position_id in {p["account_label"] for p in pos}:
        position_id = next(p["position_id"] for p in pos if position_id is None or p["account_label"] == position_id)
    return await client.post(f"/api/v4/goals/{goal['chain_id']}/allocations",
                             json={"position_id": position_id, "amount": amount, "expected_goal_version": goal.get("version", 1)})


async def goals(client):
    return {g["description"]: g for g in (await client.get("/api/v4/goals")).json()}


async def setup_basic(client, db):
    await _seed(db)
    a = await acct(client, "Broker")
    await imp(client, a, [eq()])
    return a, None  # None = "the only/first position" (resolved fresh at claim time)


async def test_goal_validation_and_edit_keeps_chain_and_claims(client, db_session):
    a, pid = await setup_basic(client, db_session)
    for bad in ({"target_amount": "0"}, {"target_basis": "tomorrow"}, {"inflation_assumption": "6"}, {"priority": 0}):
        assert (await client.post("/api/v4/goals", json=goal_body(**bad))).status_code == 422, bad
    g = await mk_goal(client)
    assert (await claim(client, g, pid, "40000")).status_code == 201
    edit = await client.put(f"/api/v4/goals/{g['chain_id']}", json={**goal_body(target_amount="1200000"), "expected_version": 1})
    assert edit.status_code == 200 and edit.json()["version"] == 2 and edit.json()["chain_id"] == g["chain_id"]
    assert (await client.put(f"/api/v4/goals/{g['chain_id']}", json={**goal_body(), "expected_version": 1})).status_code == 409
    after = (await goals(client))["House"]
    assert after["version"] == 2 and Decimal(after["allocated_total"]) == 40000  # claim survived the edit
    assert after["allocations"][0]["status"] == "active"


async def test_same_rupee_cannot_support_two_goals(client, db_session):
    a, pid = await setup_basic(client, db_session)
    g1, g2 = await mk_goal(client, description="House"), await mk_goal(client, description="Car", priority=2)
    assert (await claim(client, g1, pid, "60000")).status_code == 201
    r = await claim(client, g2, pid, "50000")
    assert r.status_code == 422 and Decimal(r.json()["detail"]["unclaimed"]) == 40000
    assert (await claim(client, g2, pid, "40000")).status_code == 201
    assert (await claim(client, g1, pid, "1")).status_code == 409  # one claim per goal+holding
    summary = (await client.get("/api/v4/allocations/summary")).json()
    assert Decimal(summary[0]["claimed"]) == 100000 and Decimal(summary[0]["unclaimed"]) == 0
    assert (await claim(client, g1, str(uuid.uuid4()), "1")).status_code == 422  # not in the snapshot


async def test_unknown_value_holding_cannot_be_claimed(client, db_session):
    await _seed(db_session)
    a = await acct(client, "A")
    await imp(client, a, [{"asset_type": "gold", "description": "coin", "units": "3", "valuation_date": TODAY.isoformat()}])
    g = await mk_goal(client)
    r = await claim(client, g, None, "10")
    assert r.status_code == 422 and "no known value" in r.json()["detail"]


async def test_value_drop_flags_all_claims_conservatively_and_is_sticky(client, db_session):
    a, pid = await setup_basic(client, db_session)
    g1, g2 = await mk_goal(client, description="House"), await mk_goal(client, description="Car", priority=2)
    await claim(client, g1, pid, "60000")
    await claim(client, g2, pid, "40000")
    await imp(client, a, [eq(value="70000")])  # price fell below the 100000 claimed
    gs = await goals(client)
    for name in ("House", "Car"):
        al = gs[name]["allocations"][0]
        assert al["status"] == "needs_review" and al["reason"] == "value_below_claims"
        assert Decimal(gs[name]["allocated_total"]) == 0 and Decimal(gs[name]["needs_review_total"]) > 0
    summary = (await client.get("/api/v4/allocations/summary")).json()
    assert Decimal(summary[0]["claimed"]) == 100000  # still reserved, not released
    proj = {p["description"]: p for p in (await client.get("/api/v4/goals/projections")).json()}
    assert proj["House"]["status"] == "blocked_needs_review"
    st = (await client.get("/api/v4/state/current")).json()
    assert any("need review" in m for m in st["readiness"]["suitability_status"]["missing"])

    await imp(client, a, [eq(value="200000")])  # value recovers
    still = (await goals(client))["House"]["allocations"][0]
    assert still["status"] == "needs_review"  # sticky: never auto-restored

    chain = still["chain_id"]
    ok = await client.put(f"/api/v4/goal-allocations/{chain}", json={"expected_version": still["version"], "action": "confirm"})
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    assert (await client.put(f"/api/v4/goal-allocations/{chain}", json={"expected_version": still["version"], "action": "confirm"})).status_code == 409


async def test_confirm_refused_while_value_still_below_and_resize_rules(client, db_session):
    a, pid = await setup_basic(client, db_session)
    g = await mk_goal(client)
    await claim(client, g, pid, "90000")
    await imp(client, a, [eq(value="50000")])
    al = (await goals(client))["House"]["allocations"][0]
    assert al["status"] == "needs_review"
    chain, ver = al["chain_id"], al["version"]
    assert (await client.put(f"/api/v4/goal-allocations/{chain}", json={"expected_version": ver, "action": "confirm"})).status_code == 422
    assert (await client.put(f"/api/v4/goal-allocations/{chain}", json={"expected_version": ver, "action": "resize", "amount": "10"})).status_code == 422
    rel = await client.put(f"/api/v4/goal-allocations/{chain}", json={"expected_version": ver, "action": "release"})
    assert rel.status_code == 200 and rel.json()["status"] == "released"
    assert (await goals(client))["House"]["allocations"] == []


async def test_removed_or_excluded_holding_needs_review_and_claim_never_moves_accounts(client, db_session):
    await _seed(db_session)
    a, b = await acct(client, "A"), await acct(client, "B")
    await imp(client, a, [eq(value="100000")])
    await imp(client, b, [eq(value="100000")])
    pos_a = "A"
    g = await mk_goal(client)
    await claim(client, g, pos_a, "50000")
    await imp(client, a, [{"asset_type": "deposit", "description": "FD", "value": "1000", "valuation_date": TODAY.isoformat()}])
    al = (await goals(client))["House"]["allocations"][0]
    # B still holds the same ISIN, but the claim must NOT silently move there
    assert al["status"] == "needs_review" and al["reason"] == "holding_not_found" and al["account_id"] == a["id"]
    assert (await client.put(f"/api/v4/goal-allocations/{al['chain_id']}", json={"expected_version": al["version"], "action": "confirm"})).status_code == 422

    g2 = await mk_goal(client, description="Car", priority=2)
    pos_b = "B"
    await claim(client, g2, pos_b, "10000")
    await client.put(f"/api/v4/accounts/{b['id']}", json={"expected_version": 1, "included": False})
    assert (await goals(client))["Car"]["allocations"][0]["reason"] == "holding_not_found"


async def test_closing_goal_releases_claims_with_audit(client, db_session):
    a, pid = await setup_basic(client, db_session)
    g = await mk_goal(client)
    await claim(client, g, pid, "40000")
    await client.put(f"/api/v4/goals/{g['chain_id']}", json={**goal_body(), "expected_version": 1, "status": "closed"})
    assert "House" not in await goals(client)
    summary = (await client.get("/api/v4/allocations/summary")).json()
    assert Decimal(summary[0]["claimed"]) == 0 and Decimal(summary[0]["unclaimed"]) == 100000
    assert (await claim(client, g, pid, "1")).status_code == 404  # closed goal takes no claims


async def test_goal_and_claim_changes_make_new_twin_states(client, db_session):
    a, pid = await setup_basic(client, db_session)
    v0 = (await client.get("/api/v4/state/current")).json()["state"]["version"]
    g = await mk_goal(client)
    s1 = (await client.get("/api/v4/state/current")).json()["state"]
    assert s1["version"] == v0 + 1 and s1["bound_facts"]["goal_count"] == 1
    await claim(client, g, pid, "1000")
    s2 = (await client.get("/api/v4/state/current")).json()["state"]
    assert s2["version"] == s1["version"] + 1 and s2["bound_facts"]["allocation_count"] == 1
    r = (await client.post("/api/v4/state/refresh")).json()
    assert r["state_created"] is False  # converged; reconcile is idempotent


def commit_body(goal=None, **kw):
    b = {"goal_chain_id": goal, "description": "SIP", "amount": "5000", "frequency": "monthly",
         "start_date": (TODAY - timedelta(days=30)).isoformat(), "source": "existing_user_reported",
         "budget_interpretation": "includes_existing_commitments"}
    b.update(kw)
    return b


async def test_commitment_revisions_duplicates_and_validation(client, db_session):
    await _seed(db_session)
    g = await mk_goal(client)
    for bad in ({"amount": "0"}, {"frequency": "daily"}, {"goal_chain_id": str(uuid.uuid4())},
                {"end_date": (TODAY - timedelta(days=90)).isoformat()}, {"budget_interpretation": None}):
        assert (await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], **bad))).status_code in (404, 422), bad
    c = (await client.post("/api/v4/commitments", json=commit_body(g["chain_id"]))).json()
    assert c["monthly_equivalent"] == "5000"
    assert (await client.post("/api/v4/commitments", json=commit_body(g["chain_id"]))).status_code == 409  # no duplicated SIP stream
    paused = await client.put(f"/api/v4/commitments/{c['chain_id']}", json={**commit_body(g["chain_id"]), "expected_version": 1, "status": "paused"})
    assert paused.status_code == 200 and paused.json()["version"] == 2 and paused.json()["status"] == "paused"
    assert (await client.put(f"/api/v4/commitments/{c['chain_id']}", json={**commit_body(g["chain_id"]), "expected_version": 1})).status_code == 409
    ended = await client.put(f"/api/v4/commitments/{c['chain_id']}", json={**commit_body(g["chain_id"]), "expected_version": 2, "status": "ended"})
    assert ended.status_code == 200
    assert (await client.get("/api/v4/commitments")).json() == []
    assert (await client.put(f"/api/v4/commitments/{c['chain_id']}", json={**commit_body(g["chain_id"]), "expected_version": 3})).status_code == 422
    q = (await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], amount="3000", frequency="quarterly"))).json()
    assert q["monthly_equivalent"] == "1000"


async def test_projection_counts_only_active_started_existing_contributions(client, db_session):
    a, pid = await setup_basic(client, db_session)
    g = await mk_goal(client, target_amount="600000")
    await claim(client, g, pid, "100000")
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"]))
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="Proposed", amount="9999", source="proposed"))
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="Later", amount="777",
                                                             start_date=(TODAY + timedelta(days=60)).isoformat()))
    p = (await client.get("/api/v4/goals/projections")).json()[0]
    assert p["status"] == "ready" and Decimal(p["starting_value"]) == 100000
    assert Decimal(p["monthly_contribution_counted"]) == 5000
    assert len(p["excluded_contributions"]) == 2
    sc = p["scenarios"]
    assert Decimal(sc["low"]["projected_value"]) < Decimal(sc["base"]["projected_value"]) < Decimal(sc["high"]["projected_value"])
    assert "probab" not in str(p).lower().replace("not forecasts or probabilities", "")


def test_projection_edge_cases():
    # today's-money target without inflation: refuse rather than guess
    r = project_goal(target_amount=Decimal("100"), target_basis="today_money", target_date=TODAY + timedelta(days=700),
                     inflation=None, starting_value=Decimal(0), monthly_contribution=Decimal(0))
    assert r["status"] == "needs_input"
    # already funded
    f = project_goal(target_amount=Decimal("1000"), target_basis="future_money", target_date=TODAY + timedelta(days=700),
                     inflation=None, starting_value=Decimal("5000"), monthly_contribution=Decimal(0))
    assert f["scenarios"]["low"]["funded"] is True and f["scenarios"]["low"]["required_monthly_contribution"] == "0.00"
    # no time left and unfunded: gap reported, no required contribution invented
    z = project_goal(target_amount=Decimal("1000"), target_basis="future_money", target_date=TODAY - timedelta(days=40),
                     inflation=None, starting_value=Decimal("100"), monthly_contribution=Decimal("50"))
    assert z["months"] == 0 and z["scenarios"]["base"]["required_monthly_contribution"] is None
    assert Decimal(z["scenarios"]["base"]["gap_to_target"]) == 900


async def test_claim_on_stale_goal_version_refused(client, db_session):
    a, _ = await setup_basic(client, db_session)
    g = await mk_goal(client)
    await client.put(f"/api/v4/goals/{g['chain_id']}", json={**goal_body(target_amount="1100000"), "expected_version": 1})
    pos = await positions(client)
    stale = await client.post(f"/api/v4/goals/{g['chain_id']}/allocations",
                              json={"position_id": pos[0]["position_id"], "amount": "10", "expected_goal_version": 1})
    assert stale.status_code == 409 and "stale version" in stale.json()["detail"]
    ok = await client.post(f"/api/v4/goals/{g['chain_id']}/allocations",
                           json={"position_id": pos[0]["position_id"], "amount": "10", "expected_goal_version": 2})
    assert ok.status_code == 201


def test_required_return_and_revision_signal():
    t = TODAY + timedelta(days=365 * 5)
    easy = project_goal(target_amount=Decimal("1000000"), target_basis="future_money", target_date=t, inflation=None,
                        starting_value=Decimal("2000000"), monthly_contribution=Decimal(0))
    assert easy["required_annual_return"] == "0" and easy["assessment"] == "reachable_under_base"
    mid = project_goal(target_amount=Decimal("600000"), target_basis="future_money", target_date=t, inflation=None,
                       starting_value=Decimal("300000"), monthly_contribution=Decimal("3000"))
    assert Decimal("0.04") < Decimal(mid["required_annual_return"]) <= Decimal("0.11")
    assert mid["assessment"] in ("reachable_under_base", "needs_higher_return_or_contribution")
    hopeless = project_goal(target_amount=Decimal("10000000"), target_basis="future_money", target_date=t, inflation=None,
                            starting_value=Decimal("100000"), monthly_contribution=Decimal("1000"))
    assert hopeless["assessment"] == "target_needs_revision" and hopeless["risk_permission_effect"] == "none"
    assert "not a fix" in hopeless["assessment_message"]
    # no time left and unfunded: no required return invented
    late = project_goal(target_amount=Decimal("1000"), target_basis="future_money", target_date=TODAY - timedelta(days=40),
                        inflation=None, starting_value=Decimal("100"), monthly_contribution=Decimal("50"))
    assert late["required_annual_return"] is None and late["assessment"] == "target_needs_revision"


async def test_budget_uses_budget_interpretation(client, db_session):
    await _seed(db_session)
    g = await mk_goal(client)
    await client.put("/api/v4/profile", json={"expected_version": 0, "facts": {
        "monthly_income": "100000", "monthly_essential_expenses": "40000", "monthly_investable_surplus": "30000"}})
    unknown = (await client.get("/api/v4/budget")).json()
    assert unknown["status"] == "known" and unknown["remaining_for_new_monthly"] == "30000"
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="Inside", amount="10000"))
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="On top", amount="25000",
                                                             budget_interpretation="additional_to_existing_commitments"))
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="Idea", amount="99999", source="proposed"))
    b = (await client.get("/api/v4/budget")).json()
    assert b["monthly_committed_included_in_surplus"] == "10000" and b["monthly_committed_on_top_of_surplus"] == "25000"
    assert b["remaining_for_new_monthly"] == "20000"  # 30000 stated - 10000 already inside it
    assert b["exceeds_income_after_essentials"] is False  # 30000 + 25000 on top = 55000 <= 60000 income left after essentials
    await client.post("/api/v4/commitments", json=commit_body(g["chain_id"], description="Big on top", amount="10000",
                                                             budget_interpretation="additional_to_existing_commitments"))
    assert (await client.get("/api/v4/budget")).json()["exceeds_income_after_essentials"] is True  # 30000 + 35000 > 60000
    assert [e["description"] for e in b["excluded_streams"]] == ["Idea"]


async def test_budget_unknown_surplus_stays_unknown(client, db_session):
    await _seed(db_session)
    b = (await client.get("/api/v4/budget")).json()
    assert b["status"] == "unknown" and b["remaining_for_new_monthly"] is None and "monthly_investable_surplus" in b["missing"]
