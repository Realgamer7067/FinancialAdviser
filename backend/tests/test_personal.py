"""Phase 04a: profile, liabilities, preferences, tolerance and capacity."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.user import User
from app.portfolio_intelligence.personal.facts import compute_capacity, compute_tolerance, missing_fields

TODAY = date.today()


# --- pure ---------------------------------------------------------------------

def test_tolerance_unknown_until_all_three_answers_and_ignores_horizon():
    assert compute_tolerance({"priority": "balanced_growth"})["status"] == "unknown"
    a = {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "20_30"}
    t = compute_tolerance(a)
    assert t["status"] == "ready" and t["score"] == 53 and t["band"] == "moderate"
    assert "not adjusted for horizon" in t["note"]


def full_facts(**kw):
    f = {"monthly_income": "100000", "monthly_essential_expenses": "40000", "emergency_reserve_amount": "240000",
         "emergency_reserve_months_target": "6", "monthly_investable_surplus": "20000", "near_term_obligations": []}
    f.update(kw)
    return f


def test_capacity_unknown_blocks_and_names_missing():
    c = compute_capacity({"monthly_income": "100000"}, [])
    assert c["status"] == "capacity_unknown" and c["blocks_risk_increasing_actions"] is True
    assert "monthly_essential_expenses" in c["missing"]
    assert c["reserve_coverage_months"] is None and c["computed_monthly_surplus"] is None


def test_capacity_metrics_and_reserve_shortfall_binds():
    c = compute_capacity(full_facts(), [{"monthly_payment": "10000", "rate_type": "fixed"}])
    assert c["monthly_essential_outgo"] == "50000"  # 40k expenses + 10k debt payments
    assert c["reserve_coverage_months"] == "4.8" and c["reserve_target_amount"] == "300000.00"
    assert c["debt_service_ratio"] == "0.1000"
    assert [b["rule"] for b in c["binding_constraints"]] == ["reserve_shortfall"] and c["blocks_risk_increasing_actions"]
    ok = compute_capacity(full_facts(emergency_reserve_amount="400000"), [])
    assert ok["binding_constraints"] == [] and ok["blocks_risk_increasing_actions"] is False
    assert ok["status"] == "raw_constraints_available"  # a raw status, never a low/moderate/high label


def test_capacity_flags_not_guesses():
    c = compute_capacity(full_facts(monthly_investable_surplus="70000"),
                         [{"monthly_payment": None, "rate_type": "floating", "next_reset_date": None}])
    assert c["stated_surplus_exceeds_computed"] is True  # 70k stated vs 60k computed: flagged, not overwritten
    assert c["debt_payments_incomplete"] is True and c["floating_rate_liabilities_without_reset_date"] == 1
    z = compute_capacity(full_facts(monthly_essential_expenses="0"), [])
    assert z["reserve_coverage_months"] is None  # zero outgo: undefined, not infinite/zero


def test_near_term_obligations_window():
    obl = [{"description": "school", "amount": "50000", "due_date": (TODAY + timedelta(days=100)).isoformat()},
           {"description": "car", "amount": "900000", "due_date": (TODAY + timedelta(days=700)).isoformat()}]
    assert compute_capacity(full_facts(near_term_obligations=obl), [])["near_term_obligations_12m"] == "50000"
    assert compute_capacity(full_facts(near_term_obligations=None), [])["near_term_obligations_12m"] is None


# --- API ----------------------------------------------------------------------

async def _seed(db):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db.commit()


async def put_profile(client, version, **facts):
    return await client.put("/api/v4/profile", json={"expected_version": version, "facts": facts})


async def test_profile_versioning_validation_and_unknown_preserved(client, db_session):
    await _seed(db_session)
    g = (await client.get("/api/v4/profile")).json()
    assert g["version"] == 0 and "monthly_income" in g["missing_fields"] and g["capacity"]["status"] == "capacity_unknown"
    r = await put_profile(client, 0, monthly_income="100000", dependents=2)
    assert r.status_code == 200 and r.json()["version"] == 1
    assert r.json()["facts"]["monthly_essential_expenses"] is None  # unknown stays null, not 0
    assert (await put_profile(client, 0, monthly_income="1")).status_code == 409
    for bad in ({"monthly_income": "-5"}, {"income_stability": "rich"}, {"dependents": -1}, {"surprise": 1},
                {"tolerance_answers": {"priority": "yolo"}}, {"monthly_income": "NaN"}):
        assert (await put_profile(client, 1, **bad)).status_code == 422, bad
    assert (await client.get("/api/v4/profile")).json()["version"] == 1  # rejected writes changed nothing


async def test_profile_edit_makes_new_twin_state_without_holdings_change(client, db_session):
    await _seed(db_session)
    a = (await client.post("/api/v4/accounts", json={"label": "A"})).json()
    await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": "k", "rows": [
        {"asset_type": "deposit", "description": "FD", "value": "1000", "valuation_date": TODAY.isoformat()}]})
    s1 = (await client.get("/api/v4/state/current")).json()
    assert s1["readiness"]["suitability_status"]["status"] == "unusable"
    await put_profile(client, 0, monthly_income="100000")
    s2 = (await client.get("/api/v4/state/current")).json()
    assert s2["state"]["version"] == s1["state"]["version"] + 1
    assert s2["state"]["bound_facts"]["profile_version"] == 1
    assert s2["readiness"]["suitability_status"]["status"] == "partial"
    assert any("goals" in m for m in s2["readiness"]["suitability_status"]["missing"])
    assert len(s2["state"]["positions"]) == 1 and s2["valuation"]["known_total"] == s1["valuation"]["known_total"]
    # an identical PUT is still a new revision (explicit user action) => new state; a no-op refresh is not
    r = (await client.post("/api/v4/state/refresh")).json()
    assert r["state_created"] is False


def liab(**kw):
    b = {"kind": "home_loan", "outstanding_amount": "2500000", "as_of": TODAY.isoformat(), "monthly_payment": "25000",
         "rate_type": "floating", "annual_rate": "0.09", "next_reset_date": (TODAY + timedelta(days=90)).isoformat()}
    b.update(kw)
    return b


async def test_liability_validation_revisions_and_capacity_effect(client, db_session):
    await _seed(db_session)
    for bad in ({"outstanding_amount": "0"}, {"outstanding_amount": "-1"}, {"annual_rate": "9"}, {"kind": "yacht"},
                {"maturity_date": (TODAY - timedelta(days=1)).isoformat()}, {"monthly_payment": "-1"}):
        assert (await client.post("/api/v4/liabilities", json=liab(**bad))).status_code == 422, bad
    created = (await client.post("/api/v4/liabilities", json=liab())).json()
    assert created["version"] == 1 and created["rate_sensitivity_known"] is True
    unknown_reset = (await client.post("/api/v4/liabilities", json=liab(next_reset_date=None, monthly_payment=None))).json()
    assert unknown_reset["rate_sensitivity_known"] is False  # flagged, never assumed zero sensitivity

    await put_profile(client, 0, monthly_income="200000", monthly_essential_expenses="40000",
                      emergency_reserve_amount="500000", emergency_reserve_months_target="6")
    cap = (await client.get("/api/v4/profile")).json()["capacity"]
    assert cap["monthly_essential_outgo"] == "65000" and cap["debt_payments_incomplete"] is True

    cid = created["chain_id"]
    upd = await client.put(f"/api/v4/liabilities/{cid}", json={**liab(outstanding_amount="2400000"), "expected_version": 1})
    assert upd.status_code == 200 and upd.json()["version"] == 2 and upd.json()["chain_id"] == cid
    assert (await client.put(f"/api/v4/liabilities/{cid}", json={**liab(), "expected_version": 1})).status_code == 409
    assert (await client.put(f"/api/v4/liabilities/{uuid.uuid4()}", json={**liab(), "expected_version": 1})).status_code == 404
    closed = await client.put(f"/api/v4/liabilities/{cid}", json={**liab(), "expected_version": 2, "status": "closed"})
    assert closed.status_code == 200
    active = (await client.get("/api/v4/liabilities")).json()
    assert [l["chain_id"] for l in active] == [unknown_reset["chain_id"]]


async def test_liability_change_creates_new_state_and_binds_revision(client, db_session):
    await _seed(db_session)
    a = (await client.post("/api/v4/accounts", json={"label": "A"})).json()
    await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": "k", "rows": [
        {"asset_type": "deposit", "description": "FD", "value": "1000", "valuation_date": TODAY.isoformat()}]})
    v1 = (await client.get("/api/v4/state/current")).json()["state"]["version"]
    await client.post("/api/v4/liabilities", json=liab())
    s = (await client.get("/api/v4/state/current")).json()["state"]
    assert s["version"] == v1 + 1 and s["bound_facts"]["liability_count"] == 1


async def test_preferences_need_confirmation_and_can_be_revoked_or_expire(client, db_session):
    await _seed(db_session)
    body = {"kind": "exclude_sector", "value": "tobacco"}
    assert (await client.post("/api/v4/preferences", json=body)).status_code == 422  # never inferred
    assert (await client.post("/api/v4/preferences", json={**body, "kind": "exclude_planet", "confirmed": True})).status_code == 422
    p = (await client.post("/api/v4/preferences", json={**body, "confirmed": True})).json()
    expired = await client.post("/api/v4/preferences", json={"kind": "exclude_isin", "value": "INE002A01018", "confirmed": True,
                                                              "expires_on": (TODAY - timedelta(days=1)).isoformat()})
    assert expired.status_code == 201
    assert [x["value"] for x in (await client.get("/api/v4/preferences")).json()] == ["tobacco"]  # expired excluded
    assert (await client.put(f"/api/v4/preferences/{p['chain_id']}", json={"expected_version": 9, "status": "revoked"})).status_code == 409
    assert (await client.put(f"/api/v4/preferences/{p['chain_id']}", json={"expected_version": 1, "status": "revoked"})).status_code == 200
    assert (await client.get("/api/v4/preferences")).json() == []


def test_missing_fields_lists_tolerance_subfields():
    m = missing_fields({"monthly_income": "1", "tolerance_answers": {"priority": "balanced_growth"}})
    assert "tolerance_answers.loss_tolerance" in m and "tolerance_answers.priority" not in m
