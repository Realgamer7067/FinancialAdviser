"""End-to-end: the plan's direct stocks follow the value / quality / momentum ranking, with caps, whole units and cash reconciliation intact."""

from decimal import Decimal

from tests.test_allocation_p3 import seed_market_with_user
from tests.test_stock_ranking import _ranked_market

D = Decimal


async def test_a_large_what_if_plan_picks_ranked_candidates_and_still_reconciles(client, db_session):
    await seed_market_with_user(db_session)
    await _ranked_market(db_session, 12)
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "500000", "what_if_band": "aggressive"})).json()
    sr = p["stock_ranking"]
    rows = {r["symbol"]: r for r in sr["rows"]}
    legs = [l for l in p["legs"] if l["role"] == "satellite"]
    assert 3 <= len(legs) <= 5 and all(isinstance(l["units"], int) and l["units"] > 0 for l in legs)
    assert all(rows[l["symbol"]]["status"] == "picked" and rows[l["symbol"]]["composite"] >= sr["floor"] for l in legs)        # only above-floor, ranked stocks
    assert not any(r["status"] in ("below_floor", "not_ranked") and r["symbol"] in {l["symbol"] for l in legs} for r in sr["rows"])
    sectors = [rows[l["symbol"]]["sector"] for l in legs]
    assert max(sectors.count(s) for s in set(sectors)) <= 2
    portfolio = D(p["base_total_after_plan"])
    assert all(D(l["planned_debit"]) <= portfolio * D("0.03") + D("0.01") for l in legs)                                          # the 3% cap
    assert D(p["spent"]) + D(p["leftover_cash"]) == D(500000)                                                                     # cash reconciles to the paisa
    picked = rows[legs[0]["symbol"]]
    assert picked["cost"]["units"] == legs[0]["units"] and D(picked["cost"]["assumed_charges"]) > 0 and "not a quote" in picked["cost"]["note"]
    assert picked["strengths"] is not None and picked["dates"]["fundamentals_as_of"] and set(picked["components"]) == {"value", "quality", "momentum"}
    assert "does not mean the stock is expected to make money" in sr["safety_note"] and sr["weights"]["value"] > 0
    assert "stock_screen" not in p                                                                                                 # the earlier checklist is no longer what picks
    low = [r for r in sr["rows"] if r["status"] == "below_floor"]
    assert low and all("below the 60 floor" in r["note"] for r in low)


async def test_with_fewer_than_three_candidates_there_is_no_forced_stock_and_the_plan_says_why(client, db_session, monkeypatch):
    from app.core.config import settings

    await seed_market_with_user(db_session)
    await _ranked_market(db_session, 12)
    monkeypatch.setattr(settings, "stock_rank_floor", 99.0)                                       # nobody clears this floor
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "500000", "what_if_band": "aggressive"})).json()
    assert not [l for l in p["legs"] if l["role"] == "satellite"] and D(p["spent"]) + D(p["leftover_cash"]) == D(500000)
    assert p["stock_ranking"]["no_stock_reason"] == "fewer than three stocks are candidates" and p["stock_ranking"]["candidates"] == 0
    assert any("fewer than three stocks clear the ranking floor" in w or "too small" in w for w in p["warnings"]) or p["stock_ranking"]["candidates"] == 0


async def test_the_standalone_ranking_endpoint_and_configurable_weights(client, db_session, monkeypatch):
    from app.core.config import settings

    await seed_market_with_user(db_session)
    await _ranked_market(db_session, 12)
    r = (await client.get("/api/v4/allocation/stock-ranking")).json()
    assert r["version"] == "stock-rank-p3-unvalidated" and r["weights"]["quality"] == __import__("pytest").approx(1 / 3) and "unvalidated" in r["policy_note"]
    assert {x["status"] for x in r["rows"]} <= {"candidate", "below_floor", "not_ranked", "excluded"} and any(x["status"] == "candidate" for x in r["rows"])
    monkeypatch.setattr(settings, "stock_rank_weights", "value:2,quality:1,momentum:1")
    r2 = (await client.get("/api/v4/allocation/stock-ranking")).json()
    assert r2["weights"]["value"] == __import__("pytest").approx(0.5) and r2["weights"] != r["weights"]


async def test_a_nifty_50_index_fund_is_looked_through_approximately_and_a_capped_stock_is_left_out():
    from app.portfolio_intelligence.allocation import overlap as O

    assert O.is_nifty50_product("Nippon India ETF Nifty 50 BeES", "Nifty 50", "etf") and O.is_nifty50_product("Navi Nifty 50 Index Fund", None, "mutual_fund")
    for name in ("Nifty 50 Equal Weight Index Fund", "Nifty Next 50 Index Fund", "Nifty 50 Value 20 Index Fund", "Nifty Midcap 150 Index Fund", "Nifty 50 Arbitrage Fund"):
        assert not O.is_nifty50_product(name, None, "mutual_fund")
    w = O.lookthrough_weights([60_000.0], {"A": 600.0, "B": 300.0, "C": 100.0}, 200_000.0)
    assert w["A"] == __import__("pytest").approx(0.18) and w["B"] == __import__("pytest").approx(0.09) and sum(w.values()) == __import__("pytest").approx(0.30)
    assert O.lookthrough_weights([60_000.0], {}, 200_000.0) == {} and O.lookthrough_weights([60_000.0], {"A": 1.0}, 0.0) == {}


async def test_exposure_combines_direct_holdings_and_a_nifty_50_fund_and_skips_untrusted_market_caps(db_session):
    import pytest

    from app.models.securities import Security
    from app.portfolio_intelligence.allocation.overlap import exposure
    from tests.test_signals_p2 import NOW

    db_session.add_all([Security(source_key="t:nb", kind="etf", symbol="NIFTYBEES", isin="INF204KB14I2", name="Nippon India ETF Nifty 50 BeES", category="Nifty 50", series="EQ", source="t", is_active=True, seen_at=NOW),
                        Security(source_key="t:eq", kind="etf", symbol="EQWT", isin="INF000000EQW", name="Nifty 50 Equal Weight ETF", category="Nifty 50 Equal Weight", series="EQ", source="t", is_active=True, seen_at=NOW)])
    await db_session.commit()
    ranking_rows = {"A": {"market_cap": 600.0}, "B": {"market_cap": 300.0}, "C": {"market_cap": None}, "D": {"market_cap": 100.0}}     # C failed the market-cap consistency check
    positions = [{"asset_type": "etf", "isin": "INF204KB14I2", "value": D(60000), "label": "NIFTYBEES"},
                 {"asset_type": "etf", "isin": "INF000000EQW", "value": D(40000), "label": "EQWT"},                                         # equal weight: not a plain Nifty 50 product
                 {"asset_type": "listed_equity", "isin": None, "value": D(10000), "label": "A"}]
    out = await exposure(db_session, positions, ranking_rows, D(200000))
    assert out["A"]["direct"] == pytest.approx(0.05) and out["A"]["lookthrough"] == pytest.approx(0.30 * 0.6) and out["A"]["total"] == pytest.approx(0.23)
    assert "C" not in out and out["B"]["lookthrough"] == pytest.approx(0.30 * 0.3) and out["D"]["direct"] == 0.0


async def test_the_plan_carries_a_shrunk_covariance_description_beside_the_rank(client, db_session):
    await seed_market_with_user(db_session)
    await _ranked_market(db_session, 12)
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "500000", "what_if_band": "aggressive"})).json()
    risk = p["stock_ranking"]["risk_beside_rank"]
    assert risk["status"] == "ready" and "Ledoit-Wolf" in risk["method"] and set(risk["stocks"]) == {l["symbol"] for l in p["legs"] if l["role"] == "satellite"}
    assert 0 < risk["equal_weight_volatility"] < 1 and -1 <= risk["average_pairwise_correlation"] <= 1
