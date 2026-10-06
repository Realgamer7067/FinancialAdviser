"""Phase 05 API: /risk, scenarios, saved analyses."""

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument, MarketCandle
from app.models.user import User
from app.utils.time import utcnow

ISIN_A, ISIN_B = "INE002A01018", "INE467B01029"
TODAY = date.today().isoformat()


async def seed(db, *, candles=True, source="yfinance", days=320):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    a = Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=ISIN_A, sector="Oil Gas & Consumable Fuels")
    b = Instrument(symbol="TCS", name="TCS", exchange="NSE", isin=ISIN_B, sector="Information Technology")
    db.add_all([a, b])
    await db.flush()
    if candles:
        for inst, seed_ in ((a, 1), (b, 2)):
            rnd, price = random.Random(seed_), 100.0
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            for i in range(days):
                db.add(MarketCandle(instrument_id=inst.id, interval="1d", timestamp=start + timedelta(days=i), open=price, high=price,
                                    low=price, close=price, volume=1, source=source, retrieved_at=utcnow(), adjusted=True))
                price *= 1.0 + rnd.gauss(0.0003, 0.01)
    await db.commit()
    return a, b


async def acct(client, label):
    return (await client.post("/api/v4/accounts", json={"label": label})).json()


def eq(isin, value, units="10"):
    return {"asset_type": "listed_equity", "isin": isin, "units": units, "value": value, "valuation_date": TODAY}


async def imp(client, a, rows):
    r = await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": str(uuid.uuid4()),
                                                                  "rows": rows, "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text


async def setup(client, db, **kw):
    await seed(db, **kw)
    a, b = await acct(client, "Broker"), await acct(client, "Bank")
    await imp(client, a, [eq(ISIN_A, "60000"), eq(ISIN_B, "20000")])
    await imp(client, b, [{"asset_type": "cash", "description": "Savings", "value": "20000", "valuation_date": TODAY}])
    return a, b


async def test_risk_bound_to_state_valuation_idempotent_and_replayable(client, db_session):
    await setup(client, db_session)
    cur = (await client.get("/api/v4/state/current")).json()
    r1 = (await client.get("/api/v4/risk")).json()
    assert r1["state_id"] == cur["state"]["id"] and r1["valuation_id"] == cur["valuation"]["id"] and r1["created"] is True
    assert r1["asset_mix"]["direct_equity_share"] == "0.8000"
    sec = {b["bucket"]: b["weight"] for b in r1["sector"]["buckets"]}
    assert sec["Oil Gas & Consumable Fuels"] == "0.6000" and sec["Information Technology"] == "0.2000" and sec["non_equity"] == "0.2000"
    assert r1["issuer_concentration"]["largest_issuer"] == "RELIANCE" and r1["issuer_concentration"]["largest_issuer_weight"] == "0.6000"
    assert r1["correlation_clusters"]["status"] == "unsupported"
    r2 = (await client.get("/api/v4/risk")).json()
    assert r2["analysis_id"] == r1["analysis_id"] and r2["created"] is False
    replay = (await client.get(f"/api/v4/analysis/{r1['analysis_id']}")).json()
    assert replay["asset_mix"] == r1["asset_mix"] and replay["volatility"] == r1["volatility"]
    assert (await client.get(f"/api/v4/analysis/{uuid.uuid4()}")).status_code == 404


async def test_volatility_ready_only_with_real_adjusted_history(client, db_session):
    await setup(client, db_session)
    v = (await client.get("/api/v4/risk")).json()["volatility"]
    assert v["status"] == "ready" and v["observations"] >= 252 and v["coverage_fraction"] == "0.8000"  # equity is 80% of known value; cash has no price series
    assert any("covered" in w for w in v["warnings"])
    assert 0 < v["annualized_volatility"] < 1


async def test_demo_seed_candles_never_feed_risk(client, db_session):
    await setup(client, db_session, source="demo_seed")
    v = (await client.get("/api/v4/risk")).json()["volatility"]
    assert v["status"] == "insufficient_data" and "annualized_volatility" not in v


async def test_short_history_suppresses_precision(client, db_session):
    await setup(client, db_session, days=100)
    v = (await client.get("/api/v4/risk")).json()["volatility"]
    assert v["status"] == "insufficient_data" and "annualized_volatility" not in v


async def test_price_only_change_new_analysis_old_one_unchanged(client, db_session):
    a, _ = await setup(client, db_session)
    first = (await client.get("/api/v4/risk")).json()
    await imp(client, a, [eq(ISIN_A, "30000"), eq(ISIN_B, "20000")])  # same holdings, RELIANCE price fell
    second = (await client.get("/api/v4/risk")).json()
    assert second["state_id"] == first["state_id"] and second["valuation_id"] != first["valuation_id"]
    assert second["analysis_id"] != first["analysis_id"] and second["known_total"] == "70000"
    old = (await client.get(f"/api/v4/analysis/{first['analysis_id']}")).json()
    assert old["known_total"] == "100000"  # saved analysis never re-priced


async def test_liquidity_uses_unclaimed_cash_and_profile(client, db_session):
    await setup(client, db_session)
    assert (await client.get("/api/v4/risk")).json()["liquidity"]["status"] == "insufficient_data"
    await client.put("/api/v4/profile", json={"expected_version": 0, "facts": {"monthly_essential_expenses": "5000", "near_term_obligations": []}})
    g = (await client.post("/api/v4/goals", json={"description": "Car", "target_amount": "1000", "target_basis": "future_money",
                                                   "target_date": (date.today() + timedelta(days=900)).isoformat(), "priority": 1})).json()
    pos = (await client.get("/api/v4/state/current")).json()["state"]["positions"]
    cash = next(p for p in pos if p["asset_type"] == "cash")
    r = await client.post(f"/api/v4/goals/{g['chain_id']}/allocations",
                          json={"position_id": cash["position_id"], "amount": "5000", "expected_goal_version": 1})
    assert r.status_code == 201
    liq = (await client.get("/api/v4/risk")).json()["liquidity"]
    assert liq["accessible_cash_after_claims"] == "15000" and liq["months_of_outgo"] == "3.0" and liq["status"] == "ready"


async def test_scenario_evaluate_reproducible_and_validated(client, db_session):
    a, _ = await setup(client, db_session)
    cur = (await client.get("/api/v4/state/current")).json()
    body = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"], "scenario": {"id": "equity_broad_-20"}}
    s1 = (await client.post("/api/v4/scenarios/evaluate", json=body)).json()
    assert s1["modeled_change"] == "-16000.00" and s1["reconciles"] is True and s1["created"] is True
    assert Decimal(s1["outside_coverage"]["value"]) == 0
    s2 = (await client.post("/api/v4/scenarios/evaluate", json=body)).json()
    assert s2["analysis_id"] == s1["analysis_id"] and s2["created"] is False
    # prices change later; evaluating against the OLD valuation still gives the old answer
    await imp(client, a, [eq(ISIN_A, "30000"), eq(ISIN_B, "20000")])
    again = (await client.post("/api/v4/scenarios/evaluate", json=body)).json()
    assert again["modeled_change"] == "-16000.00"
    new_cur = (await client.get("/api/v4/state/current")).json()
    fresh = (await client.post("/api/v4/scenarios/evaluate", json={**body, "valuation_id": new_cur["valuation"]["id"]})).json()
    assert fresh["modeled_change"] == "-10000.00"  # equity 30000 + 20000 = 50000 * -20%; cash unshocked


async def test_scenario_errors(client, db_session):
    await setup(client, db_session)
    cur = (await client.get("/api/v4/state/current")).json()
    ids = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"]}
    assert (await client.post("/api/v4/scenarios/evaluate", json={**ids, "scenario": {"id": "rates_+150bp"}})).status_code == 422
    assert (await client.post("/api/v4/scenarios/evaluate", json={**ids, "scenario": {"kind": "broad_equity", "shock": "-0.9"}})).status_code == 422
    assert (await client.post("/api/v4/scenarios/evaluate", json={**ids, "scenario": {"id": "nope"}})).status_code == 422
    assert (await client.post("/api/v4/scenarios/evaluate", json={"state_id": ids["state_id"], "valuation_id": str(uuid.uuid4()), "scenario": {"id": "equity_broad_-20"}})).status_code == 404
    sec = await client.post("/api/v4/scenarios/evaluate", json={**ids, "scenario": {"kind": "sector", "sector": "Information Technology", "shock": "-0.25"}})
    assert sec.status_code == 200 and sec.json()["modeled_change"] == "-5000.00"  # TCS 20000 * -25%
    cat = (await client.get("/api/v4/scenarios/catalog")).json()
    assert any(c["status"] == "unsupported" for c in cat["scenarios"])


async def test_risk_without_snapshot_is_409(client, db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db_session.commit()
    assert (await client.get("/api/v4/risk")).status_code == 409


async def test_catalogue_identity_reclassifies_etfs_and_supplies_sectors_but_never_guesses(client, db_session):
    from app.models.securities import Security

    await seed(db_session, candles=False)
    etf_isin, stock_isin, dup_isin, nowhere = "INF204KB14I2", "INE154A01025", "INE000A01010", "INE009A01021"
    now = utcnow()
    db_session.add_all([
        Security(source_key="t:etf", kind="etf", symbol="NIFTYBEES", isin=etf_isin, name="Nippon BeES", series="EQ", source="t", is_active=True, seen_at=now),
        Security(source_key="t:etf-amfi", kind="mutual_fund", scheme_code="9", isin=etf_isin, name="Nippon India ETF Nifty 50 BeES", source="t", is_active=True, seen_at=now),  # AMFI's mirror row of the same ETF
        Security(source_key="t:itc", kind="stock", symbol="ITC", isin=stock_isin, name="ITC", sector="Fast Moving Consumer Goods", series="EQ", source="t", is_active=True, seen_at=now),
        Security(source_key="t:d1", kind="stock", symbol="DUPA", isin=dup_isin, name="Dup A", sector="Power", series="EQ", source="t", is_active=True, seen_at=now),
        Security(source_key="t:d2", kind="stock", symbol="DUPB", isin=dup_isin, name="Dup B", sector="Metals & Mining", series="BE", source="t", is_active=True, seen_at=now),
    ])
    await db_session.commit()
    a = await acct(client, "Broker")
    await imp(client, a, [eq(ISIN_A, "40000"), eq(etf_isin, "20000"), eq(stock_isin, "20000"), eq(dup_isin, "10000"), eq(nowhere, "10000")])
    r = (await client.get("/api/v4/risk")).json()
    classes = r["asset_mix"]["classes"]
    assert classes["fund_or_etf"]["value"] == "20000" and classes["equity"]["value"] == "80000"       # the ETF is a fund, not a company
    sec = {b["bucket"]: b["value"] for b in r["sector"]["buckets"]}
    assert sec["Oil Gas & Consumable Fuels"] == "40000"                                                # instrument master, unchanged
    assert sec["Fast Moving Consumer Goods"] == "20000"                                                # market catalogue by ISIN
    assert sec["unclassified_equity"] == "20000"                                                       # shared ISIN + unknown ISIN: not guessed
    assert sec["fund_lookthrough_unknown"] == "20000"
    issuers = {i["issuer"] for i in r["issuer_concentration"]["issuers"]}
    assert "NIFTYBEES" not in issuers and "ITC" in issuers                                             # label is the symbol, not an ISIN

    cur = (await client.get("/api/v4/state/current")).json()
    body = {"state_id": cur["state"]["id"], "valuation_id": cur["valuation"]["id"], "scenario": {"id": "sector_financial_services_-20"}}
    ok = (await client.post("/api/v4/scenarios/evaluate", json=body)).json()
    assert ok["modeled_change"] == "0.00" or Decimal(ok["modeled_change"]) == 0                         # nothing in Financial Services held
    body["scenario"] = {"kind": "sector", "shock": "-0.30", "sector": "Fast Moving Consumer Goods"}
    fmcg = (await client.post("/api/v4/scenarios/evaluate", json=body)).json()
    assert Decimal(fmcg["modeled_change"]) == Decimal("-6000")                                          # ITC 20000 * -30%, from the catalogue sector
