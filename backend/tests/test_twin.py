"""Phase 03: Portfolio Twin state/valuation."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceImport
from app.models.market import Instrument
from app.models.twin import PortfolioState, ValuationSnapshot
from app.models.user import User
from app.portfolio_intelligence.state.build import refresh_state
from app.utils.time import utcnow

ISIN = "INE002A01018"
TODAY = date.today().isoformat()


async def _seed(db):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    db.add(Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=ISIN))
    await db.commit()


async def _acct(client, label):
    r = await client.post("/api/v4/accounts", json={"label": label})
    assert r.status_code == 201
    return r.json()


def eq(units="10", value="25000", d=None, isin=ISIN):
    return {"asset_type": "listed_equity", "isin": isin, "units": units, "value": value, "valuation_date": d or TODAY}


def dep(value="100000", name="FD", d=None):
    return {"asset_type": "deposit", "description": name, "value": value, "valuation_date": d or TODAY}


async def imp(client, acct, rows, key=None):
    r = await client.post("/api/v4/imports/manual/confirm",
                          json={"account_id": acct["id"], "rows": rows, "idempotency_key": key or str(uuid.uuid4()),
                                "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text
    return r.json()


async def cur(client):
    return (await client.get("/api/v4/state/current")).json()


async def test_no_accounts_no_state(client, db_session):
    await _seed(db_session)
    c = await cur(client)
    assert c["state"] is None and c["readiness"]["holdings_status"]["status"] == "unusable"
    assert (await client.post("/api/v4/state/refresh")).status_code == 409


async def test_sources_coexist_and_reimport_replaces_only_its_account(client, db_session):
    await _seed(db_session)
    a, b = await _acct(client, "Broker"), await _acct(client, "Bank")
    await imp(client, a, [eq()])
    await imp(client, b, [dep()])
    s2 = await cur(client)
    assert {p["account_label"] for p in s2["state"]["positions"]} == {"Broker", "Bank"}
    await imp(client, a, [eq(units="20", value="50000")])  # A changes; B untouched
    s3 = await cur(client)
    by_acct = {p["account_label"]: p for p in s3["state"]["positions"]}
    assert Decimal(by_acct["Broker"]["units"]) == 20 and by_acct["Bank"]["asset_type"] == "deposit"
    assert s3["state"]["version"] > s2["state"]["version"]


async def test_sold_position_leaves_latest_but_history_keeps_it(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "Broker")
    await imp(client, a, [eq(), dep(name="Gold coin", value="5000")])
    before = await cur(client)
    await imp(client, a, [dep(name="Gold coin", value="5000")])  # equity sold
    after = await cur(client)
    assert len(after["state"]["positions"]) == 1
    old = (await client.get(f"/api/v4/states/{before['state']['id']}")).json()
    assert len(old["state"]["positions"]) == 2  # immutable history


async def test_refresh_is_idempotent(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "Broker")
    await imp(client, a, [eq()])
    c1 = await cur(client)
    r = (await client.post("/api/v4/state/refresh")).json()
    assert r["state_created"] is False and r["valuation_created"] is False
    assert r["state"]["id"] == c1["state"]["id"] and r["valuation"]["id"] == c1["valuation"]["id"]


async def test_price_only_change_new_valuation_same_state(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "Broker")
    await imp(client, a, [eq(value="25000")])
    c1 = await cur(client)
    await imp(client, a, [eq(value="26000")])  # same units/identity, new price
    c2 = await cur(client)
    assert c2["state"]["id"] == c1["state"]["id"]
    assert c2["valuation"]["id"] != c1["valuation"]["id"]
    assert Decimal(c2["valuation"]["known_total"]) == 26000
    old = (await client.get(f"/api/v4/valuations/{c1['valuation']['id']}")).json()
    assert Decimal(old["known_total"]) == 25000  # the older valuation is untouched
    assert old["selections"][0]["position_id"] == c1["state"]["positions"][0]["position_id"]


async def test_units_change_or_value_only_change_makes_new_state(client, db_session):
    await _seed(db_session)
    a, b = await _acct(client, "Broker"), await _acct(client, "Bank")
    await imp(client, a, [eq()])
    await imp(client, b, [dep(value="100000")])
    v1 = (await cur(client))["state"]["version"]
    await imp(client, b, [dep(value="110000")])  # a deposit IS its value
    assert (await cur(client))["state"]["version"] == v1 + 1


async def test_unknown_value_stays_unknown_not_zero(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "Broker")
    await imp(client, a, [eq(), {"asset_type": "gold", "description": "coin", "units": "3", "valuation_date": TODAY}])
    c = await cur(client)
    v = c["valuation"]
    assert Decimal(v["known_total"]) == 25000 and v["unknown_value_count"] == 1
    assert [s["value"] for s in v["selections"]].count(None) == 1
    assert c["readiness"]["valuation_status"]["status"] == "partial"
    assert c["state"]["positions"][0]["cost_basis"] is None


async def test_same_isin_two_accounts_both_kept_and_valued(client, db_session):
    await _seed(db_session)
    a, b = await _acct(client, "A"), await _acct(client, "B")
    await imp(client, a, [eq(units="10", value="25000")])
    await imp(client, b, [eq(units="4", value="10000")])
    c = await cur(client)
    assert len(c["state"]["positions"]) == 2
    assert Decimal(c["valuation"]["known_total"]) == 35000
    assert all(p["resolution"] == "resolved" for p in c["state"]["positions"])
    assert Decimal(c["valuation"]["coverage"]["identity_resolved_value_share"]) == 1


async def test_excluded_account_leaves_state_and_versions_are_monotonic(client, db_session):
    await _seed(db_session)
    a, b = await _acct(client, "A"), await _acct(client, "B")
    await imp(client, a, [eq()])
    await imp(client, b, [dep()])
    v_full = (await cur(client))["state"]["version"]
    r = await client.put(f"/api/v4/accounts/{b['id']}", json={"expected_version": 1, "included": False})
    assert r.status_code == 200
    c = await cur(client)
    assert {p["account_label"] for p in c["state"]["positions"]} == {"A"} and c["state"]["version"] > v_full
    await client.put(f"/api/v4/accounts/{b['id']}", json={"expected_version": 2, "included": True})
    versions = [s["version"] for s in (await client.get("/api/v4/states")).json()]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)


async def test_coverage_attestation_changes_state_and_headline(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "A")
    await imp(client, a, [eq()])
    c1 = await cur(client)
    assert c1["headline_label"] == "Known portfolio value"
    assert c1["readiness"]["account_coverage_status"]["status"] == "partial"
    await client.put("/api/v4/account-coverage", json={"expected_version": 0, "status": "complete"})
    c2 = await cur(client)
    assert c2["state"]["version"] == c1["state"]["version"] + 1
    assert c2["headline_label"] == "Portfolio value" and c2["readiness"]["account_coverage_status"]["status"] == "complete"


async def test_partial_import_never_used_and_stale_flag(client, db_session):
    await _seed(db_session)
    a, b = await _acct(client, "A"), await _acct(client, "B")
    await imp(client, a, [eq()])
    await imp(client, b, [dep()])
    c1 = await cur(client)
    # a newer PARTIAL import must be ignored by the twin
    db_session.add(SourceImport(account_id=uuid.UUID(a["id"]), idempotency_key="p", content_hash="h", schema_version="x",
                                status="partial", row_count=0, created_at=utcnow() + timedelta(seconds=5)))
    await db_session.commit()
    res = await refresh_state(db_session, SINGLE_USER_ID)
    assert res.state.id == uuid.UUID(c1["state"]["id"]) and not res.state_created
    # inputs changed behind the twin's back => is_stale until refreshed
    from app.models.accounts import SourceAccount
    acct = await db_session.get(SourceAccount, uuid.UUID(a["id"]))
    acct.included = False
    await db_session.commit()
    assert (await cur(client))["is_stale"] is True
    assert (await client.post("/api/v4/state/refresh")).status_code == 200
    assert (await cur(client))["is_stale"] is False


async def test_freshness_and_valid_empty_account(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "A")
    old = (date.today() - timedelta(days=30)).isoformat()
    await imp(client, a, [eq(d=old), dep(d=old)])
    v = (await cur(client))["valuation"]
    by_source = {x["source"]: x["quality"] for x in v["selections"]}
    assert by_source["user_entered_value"] == "stale"  # listed row older than 5 days
    assert by_source["user_reported_value"] == "fresh"  # deposit within its 90-day window
    assert Decimal(v["coverage"]["fresh_value_share"]) < 1


async def test_all_accounts_excluded_keeps_last_state_flagged_stale(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "A")
    await imp(client, a, [eq()])
    await client.put(f"/api/v4/accounts/{a['id']}", json={"expected_version": 1, "included": False})
    c = await cur(client)
    assert c["state"] is not None and c["is_stale"] is True  # no silent empty portfolio
    assert (await client.post("/api/v4/state/refresh")).status_code == 409


async def test_matched_holdings_show_the_symbol_not_the_isin(client, db_session):
    await _seed(db_session)
    a = await _acct(client, "Broker")
    await imp(client, a, [eq(units="10", value="25000"), {"asset_type": "gold", "description": "coin", "units": "2", "valuation_date": TODAY}])
    pos = {p["asset_type"]: p for p in (await client.get("/api/v4/state/current")).json()["state"]["positions"]}
    assert pos["listed_equity"]["display_name"] == "RELIANCE" and pos["listed_equity"]["raw_identifier"] == ISIN  # raw input is kept
    assert pos["gold"]["display_name"] == "coin"  # unmatched holdings keep the owner's own wording
    acct_pos = (await client.get(f"/api/v4/accounts/{a['id']}/positions")).json()["positions"]
    assert {p["display_name"] for p in acct_pos} == {"RELIANCE", "coin"}
    summary = (await client.get("/api/v4/allocations/summary")).json()
    assert "RELIANCE" in {s["holding"] for s in summary}


async def test_catalogue_isin_gives_a_symbol_and_flag_even_when_not_in_the_nifty_50_table(client, db_session):
    from app.models.securities import Security

    await _seed(db_session)
    etf_isin = "INF204KB14I2"
    db_session.add(Security(source_key="t:nb", kind="etf", symbol="NIFTYBEES", isin=etf_isin, name="Nippon Nifty BeES", series="EQ",
                            source="test", is_active=True, seen_at=utcnow()))
    await db_session.commit()
    a = await _acct(client, "A")
    await imp(client, a, [eq(), eq(isin=etf_isin, units="5", value="1300")])
    pos = {p["isin"]: p for p in (await cur(client))["state"]["positions"]}
    assert pos[ISIN]["display_name"] == "RELIANCE" and pos[ISIN]["in_catalogue"] is False       # old table, not in the test catalogue
    assert pos[etf_isin]["display_name"] == "NIFTYBEES" and pos[etf_isin]["in_catalogue"] is True
    assert pos[etf_isin]["resolution"] in ("unresolved", "ambiguous")                           # identity status itself is not rewritten


async def test_holding_links_to_its_market_page_only_when_the_isin_names_one_security(client, db_session):
    from app.models.securities import Security

    await _seed(db_session)
    uniq, dup = "INF204KB14I2", "INE000A01010"
    now = utcnow()
    db_session.add_all([
        Security(source_key="t:u", kind="etf", symbol="NIFTYBEES", isin=uniq, name="Nippon", series="EQ", source="test", is_active=True, seen_at=now),
        Security(source_key="t:d1", kind="stock", symbol="DUPA", isin=dup, name="Dup A", series="EQ", source="test", is_active=True, seen_at=now),
        Security(source_key="t:d2", kind="stock", symbol="DUPB", isin=dup, name="Dup B", series="BE", source="test", is_active=True, seen_at=now),
    ])
    await db_session.commit()
    a = await _acct(client, "A")
    await imp(client, a, [eq(isin=uniq, units="1", value="100"), eq(isin=dup, units="1", value="100")])
    pos = {p["isin"]: p for p in (await cur(client))["state"]["positions"]}
    assert pos[uniq]["security_id"] is not None
    assert pos[dup]["security_id"] is None            # two securities share it: no link rather than a guess


async def test_identity_readiness_counts_a_catalogue_isin_as_identified_but_not_an_unknown_one(client, db_session):
    from app.models.securities import Security

    await _seed(db_session)
    known, unknown = "INF204KB14I2", "INE467B01029"      # second one is in neither the Nifty 50 table nor the catalogue
    db_session.add(Security(source_key="t:k", kind="etf", symbol="NIFTYBEES", isin=known, name="Nippon", series="EQ", source="test", is_active=True, seen_at=utcnow()))
    await db_session.commit()
    a = await _acct(client, "A")
    await imp(client, a, [eq(isin=known, units="1", value="100")])
    t = await cur(client)
    assert t["readiness"]["identity_status"]["status"] == "complete"
    assert t["valuation"]["coverage"]["identity_resolved_value_share"] == "1.0000"
    b = await _acct(client, "B")
    await imp(client, b, [eq(isin=unknown, units="1", value="100")])
    t = await cur(client)
    assert t["readiness"]["identity_status"]["status"] == "partial" and "1 holding(s) not matched" in t["readiness"]["identity_status"]["missing"][0]
    assert t["valuation"]["coverage"]["identity_resolved_value_share"] == "0.5000"


async def test_an_etf_listed_by_nse_and_mirrored_by_amfi_is_still_one_known_security(client, db_session):
    from app.models.securities import Security

    await _seed(db_session)
    isin, now = "INF204KB14I2", utcnow()
    db_session.add_all([
        Security(source_key="nse:nb", kind="etf", symbol="NIFTYBEES", isin=isin, name="NIPINDETFNIFTYBEES", series="EQ", source="nse_etf_list", is_active=True, seen_at=now),
        Security(source_key="amfi:nb", kind="mutual_fund", scheme_code="1", isin=isin, name="Nippon India ETF Nifty 50 BeES", source="amfi_navall", is_active=True, seen_at=now),
    ])
    await db_session.commit()
    a = await _acct(client, "A")
    await imp(client, a, [eq(isin=isin, units="1", value="100")])
    t = await cur(client)
    p = t["state"]["positions"][0]
    assert p["display_name"] == "NIFTYBEES" and p["identity"] == "catalogue" and p["security_id"] is not None
    assert t["readiness"]["identity_status"]["status"] == "complete"
