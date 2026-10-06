"""Phase 06 API: /actions/evaluate, saved simulations, replay."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument, MarketCandle
from app.models.user import User
from app.utils.time import utcnow

TODAY = date.today().isoformat()
ISIN_REL, ISIN_TCS, ISIN_HDFC = "INE002A01018", "INE467B01029", "INE040A01034"

PROFILE = {"monthly_income": "100000", "monthly_essential_expenses": "30000", "emergency_reserve_amount": "300000",
           "emergency_reserve_months_target": "6", "monthly_investable_surplus": "20000", "near_term_obligations": [],
           "tolerance_answers": {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "20_30"}}


async def seed(db, *, hdfc_source="yfinance", hdfc_age_days=1):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    rel = Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=ISIN_REL, sector="Oil Gas & Consumable Fuels")
    tcs = Instrument(symbol="TCS", name="TCS", exchange="NSE", isin=ISIN_TCS, sector="Information Technology")
    hdfc = Instrument(symbol="HDFCBANK", name="HDFC", exchange="NSE", isin=ISIN_HDFC, sector="Financial Services", lot_size=1)
    db.add_all([rel, tcs, hdfc])
    await db.flush()
    ts = datetime.now(timezone.utc) - timedelta(days=hdfc_age_days)
    db.add(MarketCandle(instrument_id=hdfc.id, interval="1d", timestamp=ts, open=1500, high=1500, low=1500, close=1500, volume=1,
                        source=hdfc_source, retrieved_at=utcnow(), adjusted=True))
    await db.commit()
    return hdfc


def eq(isin, value, units="10"):
    return {"asset_type": "listed_equity", "isin": isin, "units": units, "value": value, "valuation_date": TODAY}


async def acct(client, label):
    return (await client.post("/api/v4/accounts", json={"label": label})).json()


async def imp(client, a, rows):
    r = await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": str(uuid.uuid4()),
                                                                  "rows": rows, "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text


async def setup(client, db, *, profile=True, **kw):
    hdfc = await seed(db, **kw)
    broker, bank = await acct(client, "Broker"), await acct(client, "Bank")
    await imp(client, broker, [eq(ISIN_REL, "30000"), eq(ISIN_TCS, "30000")])
    await imp(client, bank, [{"asset_type": "deposit", "description": "FD", "value": "30000", "valuation_date": TODAY},
                             {"asset_type": "cash", "description": "Savings", "value": "10000", "valuation_date": TODAY}])
    if profile:
        r = await client.put("/api/v4/profile", json={"expected_version": 0, "facts": PROFILE})
        assert r.status_code == 200, r.text
    cur = (await client.get("/api/v4/state/current")).json()
    return hdfc, broker, bank, {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}


def buy(hdfc, broker, amount="20000", funding="new_money"):
    return {"type": "BUY", "instrument_id": str(hdfc.id), "account_id": broker["id"], "amount": amount, "funding": funding}


async def run(client, ids, actions, **kw):
    return await client.post("/api/v4/actions/evaluate", json={**ids, "external_contribution": "20000", "actions": actions, **kw})


async def test_same_flows_hold_and_buy_conserve_and_nothing_is_published(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    r = (await run(client, ids, [buy(hdfc, broker)])).json()
    assert r["published"] is False and r["default"] == "HOLD" and r["created"] is True
    assert r["hold"]["accounting"]["assets_before"] == "100000" and r["hold"]["accounting"]["assets_after"] == "120000"
    a = r["alternatives"][0]
    assert a["accounting"]["external_contribution"] == "20000" and a["accounting"]["conserved"] is True
    assert a["accounting"]["assets_before"] == "100000" and a["cost"]["units"] == 13  # 20000 / (1500 * 1.003) = 13.29
    assert Decimal(a["accounting"]["assets_after"]) + Decimal(a["accounting"]["friction"]) == Decimal("120000")
    assert a["status"] in ("tradeoff", "worse_than_hold", "dominates_hold", "no_material_benefit")
    cur = (await client.get("/api/v4/state/current")).json()
    assert cur["state"]["id"] == ids["state_id"]  # a simulation never changes the twin


async def test_idempotent_replayable_and_listed(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    r1 = (await run(client, ids, [buy(hdfc, broker)])).json()
    r2 = (await run(client, ids, [buy(hdfc, broker)])).json()
    assert r2["analysis_id"] == r1["analysis_id"] and r2["created"] is False
    r3 = (await run(client, ids, [buy(hdfc, broker, amount="15000")])).json()
    assert r3["analysis_id"] != r1["analysis_id"]
    replay = (await client.get(f"/api/v4/analysis/{r1['analysis_id']}")).json()
    assert replay["alternatives"][0]["candidate_state_hash"] == r1["alternatives"][0]["candidate_state_hash"]
    assert replay["hold"] == r1["hold"]
    hist = (await client.get("/api/v4/actions/evaluations")).json()
    assert {h["analysis_id"] for h in hist} == {r1["analysis_id"], r3["analysis_id"]}


async def test_validation_errors_and_no_half_saved_runs(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    assert (await run(client, ids, [{"type": "BUY", "amount": "100"}])).status_code == 422
    assert (await run(client, ids, [buy(hdfc, broker, amount="-5")])).status_code == 422
    bad_inst = {**buy(hdfc, broker), "instrument_id": str(uuid.uuid4())}
    assert (await run(client, ids, [bad_inst])).status_code == 422
    assert (await run(client, ids, [], fee_pct="0.9")).status_code == 422
    assert (await client.post("/api/v4/actions/evaluate", json={**ids, "external_contribution": "-1"})).status_code == 422
    assert (await run(client, {**ids, "valuation_id": str(uuid.uuid4())}, [])).status_code == 404
    other = {**buy(hdfc, broker), "account_id": str(uuid.uuid4())}
    assert (await run(client, ids, [other])).status_code == 422
    assert (await client.get("/api/v4/actions/evaluations")).json() == []  # nothing saved for any failed request


async def test_prices_come_from_real_adjusted_candles_only(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session, hdfc_source="demo_seed")
    a = (await run(client, ids, [buy(hdfc, broker)])).json()["alternatives"][0]
    assert a["status"] == "rejected" and any(g["gate_id"] == "price_available" and g["result"] == "fail" for g in a["gates"])
    assert a["accounting"]["conserved"] is True


async def test_stale_price_needs_input(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session, hdfc_age_days=40)
    a = (await run(client, ids, [buy(hdfc, broker)])).json()["alternatives"][0]
    assert a["status"] == "needs_input" and any(g["gate_id"] == "price_available" and g["result"] == "unknown" for g in a["gates"])


async def test_unknown_profile_restricts_added_risk(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session, profile=False)
    cur = (await client.get("/api/v4/state/current")).json()
    ids = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    a = (await run(client, ids, [buy(hdfc, broker)])).json()["alternatives"][0]
    assert any(g["gate_id"] == "risk_capacity" and g["result"] in ("unknown", "fail") for g in a["gates"])
    assert a["status"] in ("needs_input", "rejected")


async def test_restriction_rejects_and_capacity_shortfall_blocks(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    await client.post("/api/v4/preferences", json={"kind": "exclude_isin", "value": ISIN_HDFC, "confirmed": True})
    cur = (await client.get("/api/v4/state/current")).json()
    ids = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    a = (await run(client, ids, [buy(hdfc, broker)])).json()["alternatives"][0]
    assert a["status"] == "rejected" and any(g["gate_id"] == "user_restrictions" and g["result"] == "fail" for g in a["gates"])
    # reserve far below target: capacity binds even though the questionnaire is fine
    await client.put("/api/v4/profile", json={"expected_version": 1, "facts": {**PROFILE, "emergency_reserve_amount": "20000"}})
    cur = (await client.get("/api/v4/state/current")).json()
    ids2 = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    b = (await run(client, ids2, [buy(hdfc, broker)])).json()["alternatives"][0]
    assert any(g["gate_id"] == "risk_capacity" and g["result"] == "fail" and "reserve_shortfall" in g["observed"] for g in b["gates"])


async def test_reduce_preview_is_review_only_and_respects_claims(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    pos = (await client.get("/api/v4/state/current")).json()["state"]["positions"]
    rel = next(p for p in pos if p["raw_identifier"] == ISIN_REL)
    a = (await run(client, ids, [{"type": "REDUCE_PREVIEW", "position_id": rel["position_id"], "amount": "10000"}])).json()["alternatives"][0]
    assert a["status"] == "review_required" and a["cost"]["tax"].startswith("unknown") and a["accounting"]["conserved"] is True
    g = (await client.post("/api/v4/goals", json={"description": "Car", "target_amount": "100000", "target_basis": "future_money",
                                                   "target_date": (date.today() + timedelta(days=900)).isoformat(), "priority": 1})).json()
    pos2 = (await client.get("/api/v4/state/current")).json()
    rel2 = next(p for p in pos2["state"]["positions"] if p["raw_identifier"] == ISIN_REL)
    await client.post(f"/api/v4/goals/{g['chain_id']}/allocations", json={"position_id": rel2["position_id"], "amount": "25000", "expected_goal_version": 1})
    cur = (await client.get("/api/v4/state/current")).json()
    ids2 = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    rel3 = next(p for p in cur["state"]["positions"] if p["raw_identifier"] == ISIN_REL)
    b = (await run(client, ids2, [{"type": "REDUCE_PREVIEW", "position_id": rel3["position_id"], "amount": "10000"}])).json()["alternatives"][0]
    assert b["status"] == "rejected" and any(x["gate_id"] == "not_claimed_for_goals" and x["result"] == "fail" for x in b["gates"])


async def test_contribution_adjustment_through_api(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    g = (await client.post("/api/v4/goals", json={"description": "House", "target_amount": "1000000", "target_basis": "future_money",
                                                   "target_date": (date.today() + timedelta(days=365 * 5)).isoformat(), "priority": 1})).json()
    c = (await client.post("/api/v4/commitments", json={
        "goal_chain_id": g["chain_id"], "description": "SIP", "amount": "5000", "frequency": "monthly",
        "start_date": (date.today() - timedelta(days=30)).isoformat(), "source": "existing_user_reported",
        "budget_interpretation": "includes_existing_commitments"})).json()
    cur = (await client.get("/api/v4/state/current")).json()
    ids2 = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    up = (await run(client, ids2, [{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": c["chain_id"], "new_monthly_amount": "8000"}],
                    external_contribution="0")).json()["alternatives"][0]
    rows = {r["metric"]: r for r in up["comparison_vs_hold"]["rows"]}
    assert rows["goal_shortfall_base"]["verdict"] == "improved" and Decimal(rows["goal_shortfall_base"]["delta"]) < 0
    too = (await run(client, ids2, [{"type": "ADJUST_CONTRIBUTION", "commitment_chain_id": c["chain_id"], "new_monthly_amount": "90000"}],
                     external_contribution="0")).json()["alternatives"][0]
    assert too["status"] == "rejected"


async def test_old_valuation_replays_unchanged_after_price_change(client, db_session):
    hdfc, broker, bank, ids = await setup(client, db_session)
    first = (await run(client, ids, [buy(hdfc, broker)])).json()
    await imp(client, broker, [eq(ISIN_REL, "20000"), eq(ISIN_TCS, "30000")])  # price-only move
    again = (await run(client, ids, [buy(hdfc, broker)])).json()
    assert again["analysis_id"] == first["analysis_id"]  # same frozen inputs => the same saved simulation
    cur = (await client.get("/api/v4/state/current")).json()
    fresh = (await run(client, {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}, [buy(hdfc, broker)])).json()
    assert fresh["analysis_id"] != first["analysis_id"] and fresh["hold"]["accounting"]["assets_before"] == "90000"


async def test_instrument_master_listing(client, db_session):
    await seed(db_session)
    allv = (await client.get("/api/v4/instruments")).json()
    assert {i["symbol"] for i in allv} == {"RELIANCE", "TCS", "HDFCBANK"}
    assert [i["symbol"] for i in (await client.get("/api/v4/instruments?q=hdf")).json()] == ["HDFCBANK"]
