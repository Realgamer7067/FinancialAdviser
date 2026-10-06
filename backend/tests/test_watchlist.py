"""Angel master, quotes, watchlists, alerts and personal context."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.v4 import watchlist as wl_api
from app.core.single_user import SINGLE_USER_ID
from app.main import app
from app.models.living import InboxIssue
from app.models.market import Instrument
from app.models.user import User
from app.models.watchlist import BrokerInstrument, MarketQuote, WatchAlert
from app.portfolio_intelligence.decisions import inbox as inbox_mod
from app.portfolio_intelligence.market import master as master_mod
from app.portfolio_intelligence.market import quotes as quotes_mod
from app.portfolio_intelligence.market.context import build_context
from app.portfolio_intelligence.sources.angel import client as client_mod
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AuthExpired
from app.utils.time import utcnow
from tests.angel_fixtures import ok, transport
from tests.test_decisions import acct, complete_setup, eq, imp, seed  # noqa: F401

D = Decimal
IST_OPEN = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)    # Wed 11:30 IST
IST_CLOSED = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)  # Wed 17:30 IST
SAT = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)

MASTER = [
    {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "exch_seg": "NSE", "instrumenttype": "", "lotsize": "1", "tick_size": "5.000000"},
    {"token": "11536", "symbol": "TCS-EQ", "name": "TCS", "exch_seg": "NSE", "instrumenttype": "", "lotsize": "1", "tick_size": "5"},
    {"token": "999", "symbol": "SMALLCO-EQ", "name": "SMALL CO", "exch_seg": "NSE", "instrumenttype": "", "lotsize": "1"},
    {"token": "50", "symbol": "NIFTY", "name": "NIFTY", "exch_seg": "NSE", "instrumenttype": "AMXIDX"},          # index
    {"token": "51", "symbol": "RELIANCE26OCTFUT", "name": "RELIANCE", "exch_seg": "NFO", "instrumenttype": "FUTSTK"},  # derivative
    {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "exch_seg": "NSE", "instrumenttype": ""},      # duplicate token
    {"token": "7", "symbol": "WEIRD-BE", "name": "WEIRD", "exch_seg": "NSE", "instrumenttype": ""},               # not the EQ series
    "garbage", {"exch_seg": "NSE"},
]


# --- pure -------------------------------------------------------------------------------------------

def test_master_parse_keeps_only_nse_cash_equity():
    rows = master_mod.parse_master(MASTER)
    assert [r["symbol"] for r in rows] == ["RELIANCE", "TCS", "SMALLCO"]
    assert rows[0]["tick_size"] == D("0.05") and rows[2]["tick_size"] is None and rows[0]["lot_size"] == 1


def test_quote_parsing_never_invents_a_price():
    full = quotes_mod.parse_quote({"symbolToken": "2885", "ltp": 1500.5, "close": 1480, "open": 1490, "high": 1510, "low": 1485, "percentChange": 1.38,
                                   "tradeVolume": 1234567, "52WeekHigh": 1600, "52WeekLow": 1100, "exchTradeTime": "30-Sep-2026 15:29:59"})
    docs_names = quotes_mod.parse_quote({"symbolToken": "1", "ltp": 10, "52WeekHighPrice": 12, "52WeekLowPrice": 8})  # the documented names still work
    assert docs_names["week52_high"] == D("12") and docs_names["week52_low"] == D("8")
    assert full["ltp"] == D("1500.5") and full["percent_change"] == D("1.38") and full["volume"] == 1234567
    assert full["exchange_time"].hour == 15 and full["week52_high"] == D("1600")
    ltp_only = quotes_mod.parse_quote({"symbolToken": "2885", "ltp": "100"})
    assert ltp_only["percent_change"] is None and ltp_only["exchange_time"] is None and ltp_only["prev_close"] is None
    derived = quotes_mod.parse_quote({"symbolToken": "1", "ltp": 110, "close": 100})
    assert derived["percent_change"] == D("10")  # our own arithmetic when the broker omits it
    for bad in ({"ltp": 0}, {"ltp": -1}, {"ltp": "nan"}, {"ltp": None}, {}, "x", None):
        assert quotes_mod.parse_quote(bad) is None


def test_market_hours_and_freshness_labels():
    assert quotes_mod.market_status(IST_OPEN)["open"] is True
    assert quotes_mod.market_status(IST_CLOSED)["open"] is False and "last session" in quotes_mod.market_status(IST_CLOSED)["label"]
    assert quotes_mod.market_status(SAT)["open"] is False
    assert quotes_mod.quote_freshness(IST_OPEN - timedelta(seconds=30), IST_OPEN) == "live"
    assert quotes_mod.quote_freshness(IST_OPEN - timedelta(minutes=10), IST_OPEN) == "delayed"
    assert quotes_mod.quote_freshness(SAT - timedelta(days=1), SAT) == "last_session"  # a weekend quote is never "live"
    assert quotes_mod.quote_freshness(None) == "none"


LIMITS = {"max_single_issuer_weight": D("0.25"), "max_sector_weight": D("0.40")}


def test_context_is_facts_about_the_owners_own_limits():
    c = build_context(symbol="RELIANCE", instrument_id="i1", sector="Energy", isin="INE1", holdings={"i1": {"value": D(30000), "accounts": {"B", "A"}}},
                      total=D(100000), sector_values={"Energy": D(30000)}, restrictions=[{"kind": "exclude_sector", "value": "energy"}],
                      thesis={"status": "weakened"}, limits=LIMITS)
    assert c["owned"] and c["owned_weight"] == "0.3000" and c["accounts"] == ["A", "B"]
    assert c["issuer_room_rupees"] == "0" and c["sector_room_rupees"] == "10000"  # 40% of 100000 - 30000
    assert any("above your 25.0% single-company limit" in f for f in c["facts"]) and c["restriction_conflicts"]
    assert any("weakened" in f for f in c["facts"])
    text = " ".join(c["facts"]).lower()
    assert "buy" not in text and "sell" not in text and "recommend" not in text  # facts, never advice
    out = build_context(symbol="X", instrument_id=None, sector=None, isin=None, holdings={}, total=D(100), sector_values={}, restrictions=[], thesis=None, limits=LIMITS)
    assert out["context_available"] is False
    empty = build_context(symbol="X", instrument_id="i", sector=None, isin=None, holdings={}, total=D(0), sector_values={}, restrictions=[], thesis=None, limits=LIMITS)
    assert empty["owned_weight"] is None


# --- DB-backed ---------------------------------------------------------------------------------------------

async def load_master(db):
    stats = await master_mod.upsert_master(db, master_mod.parse_master(MASTER))
    return stats


async def setup(client, db):
    await seed(db)
    await load_master(db)


async def bi(db, symbol):
    return (await db.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == symbol))).scalar_one()


async def mk_list(client, name="Ideas"):
    r = await client.post("/api/v4/watchlists", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def add(client, wl, b, **kw):
    r = await client.post(f"/api/v4/watchlists/{wl['id']}/items", json={"broker_instrument_id": str(b.id), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def quote_entry(token, ltp, close=100, pct=None):
    e = {"exchange": "NSE", "tradingSymbol": "X-EQ", "symbolToken": token, "ltp": ltp, "close": close, "open": close, "high": ltp, "low": close,
         "tradeVolume": 1000, "52WeekHigh": ltp * 2, "52WeekLow": ltp / 2}
    if pct is not None:
        e["percentChange"] = pct
    return e


@pytest.fixture
def fake_angel(monkeypatch):
    """Dependency override: a read-only client over a mock transport whose quote payload the test controls."""
    state = {"fetched": [], "unfetched": [], "session": True, "calls": 0, "error": None}

    def handler(request):
        import httpx
        state["calls"] += 1
        if state["error"] is not None:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=ok({"fetched": state["fetched"], "unfetched": state["unfetched"]}))

    async def factory():
        if not state["session"]:
            raise AuthExpired("no valid Angel session")
        return AngelClient(api_key="k", jwt="j", transport=transport({"market/v1/quote": handler}))

    app.dependency_overrides[wl_api.get_client_factory] = lambda: factory
    monkeypatch.setattr(client_mod, "MIN_INTERVAL_SECONDS", 0.0)
    wl_api._last_refresh.clear()
    yield state
    app.dependency_overrides.pop(wl_api.get_client_factory, None)


async def test_master_upsert_matches_universe_and_is_idempotent(db_session):
    await seed(db_session)
    s1 = await load_master(db_session)
    assert s1 == {"rows": 3, "added": 3, "updated": 0, "matched_to_universe": 2}
    s2 = await load_master(db_session)
    assert s2["added"] == 0 and s2["updated"] == 3
    assert (await db_session.execute(select(func.count()).select_from(BrokerInstrument))).scalar_one() == 3
    rel, small = await bi(db_session, "RELIANCE"), await bi(db_session, "SMALLCO")
    assert rel.instrument_id is not None and rel.match_basis == "symbol_series_match" and small.instrument_id is None


async def test_search_and_validation(client, db_session):
    await seed(db_session)
    assert (await client.get("/api/v4/market/search?q=rel")).json() == {"needs_master": True, "results": []}
    await load_master(db_session)
    r = (await client.get("/api/v4/market/search?q=rel")).json()
    assert r["needs_master"] is False and [x["symbol"] for x in r["results"]] == ["RELIANCE"] and r["results"][0]["in_universe"] is True
    assert [x["symbol"] for x in (await client.get("/api/v4/market/search?q=small")).json()["results"]] == ["SMALLCO"]
    assert (await client.get("/api/v4/market/search?q=r")).status_code == 422


async def test_watchlist_crud_limits_and_ownership(client, db_session):
    await setup(client, db_session)
    wl = await mk_list(client)
    assert (await client.post("/api/v4/watchlists", json={"name": "Ideas"})).status_code == 409
    rel = await bi(db_session, "RELIANCE")
    it = await add(client, wl, rel, note="Retail growth", why_watching="Waiting for a lower price")
    assert (await client.post(f"/api/v4/watchlists/{wl['id']}/items", json={"broker_instrument_id": str(rel.id)})).status_code == 409
    assert (await client.post(f"/api/v4/watchlists/{wl['id']}/items", json={"broker_instrument_id": str(uuid.uuid4())})).status_code == 422
    assert (await client.post(f"/api/v4/watchlists/{uuid.uuid4()}/items", json={"broker_instrument_id": str(rel.id)})).status_code == 404
    upd = await client.put(f"/api/v4/watchlists/items/{it['item_id']}", json={"note": "Updated", "why_watching": None})
    assert upd.json()["note"] == "Updated" and upd.json()["why_watching"] is None
    got = (await client.get("/api/v4/watchlists")).json()
    assert got["lists"][0]["items"][0]["symbol"] == "RELIANCE" and got["lists"][0]["items"][0]["quote"] is None  # no quote yet: not a fake 0
    assert (await client.put(f"/api/v4/watchlists/{wl['id']}", json={"name": "Core ideas"})).json()["name"] == "Core ideas"
    assert (await client.delete(f"/api/v4/watchlists/items/{it['item_id']}")).status_code == 204
    assert (await client.delete(f"/api/v4/watchlists/items/{it['item_id']}")).status_code == 404
    assert (await client.delete(f"/api/v4/watchlists/{wl['id']}")).status_code == 204
    assert (await client.get("/api/v4/watchlists")).json()["lists"] == []


async def test_refresh_saves_dated_quotes_reports_gaps_and_throttles(client, db_session, fake_angel):
    await setup(client, db_session)
    wl = await mk_list(client)
    rel, tcs, small = await bi(db_session, "RELIANCE"), await bi(db_session, "TCS"), await bi(db_session, "SMALLCO")
    for b in (rel, tcs, small):
        await add(client, wl, b)
    fake_angel["fetched"] = [quote_entry("2885", 1500.5, 1480, 1.38), quote_entry("11536", 3900, 4000, -2.5), {"symbolToken": "999", "ltp": 0}]
    fake_angel["unfetched"] = [{"symbolToken": "12345"}]
    r = (await client.post("/api/v4/watchlist/refresh")).json()
    assert r["throttled"] is False and r["requested"] == 3 and r["refreshed"] == 2 and r["unfetched"] == ["12345"] and len(r["unparsed"]) == 1
    again = (await client.post("/api/v4/watchlist/refresh")).json()
    assert again["throttled"] is True and fake_angel["calls"] == 1  # coalesced: no second broker call
    forced = (await client.post("/api/v4/watchlist/refresh?force=true")).json()
    assert forced["throttled"] is False and fake_angel["calls"] == 2
    items = {i["symbol"]: i for i in (await client.get("/api/v4/watchlists")).json()["lists"][0]["items"]}
    q = items["RELIANCE"]["quote"]
    assert q["ltp"] == "1500.5" and q["day_change_pct"] == "1.38" and q["freshness"] in ("live", "delayed", "last_session") and q["retrieved_at"]
    assert 0 < q["position_in_52w_range"] < 1
    assert items["TCS"]["quote"]["day_change_pct"] == "-2.5" and items["SMALLCO"]["quote"] is None  # the unusable quote stays "no price"


async def test_refresh_without_session_or_on_broker_trouble_keeps_last_quotes(client, db_session, fake_angel):
    await setup(client, db_session)
    wl = await mk_list(client)
    await add(client, wl, await bi(db_session, "RELIANCE"))
    fake_angel["fetched"] = [quote_entry("2885", 1500)]
    assert (await client.post("/api/v4/watchlist/refresh")).status_code == 200
    fake_angel["session"] = False
    r = await client.post("/api/v4/watchlist/refresh?force=true")
    assert r.status_code == 409 and "reconnect_required" in str(r.json())
    fake_angel["session"], fake_angel["error"] = True, True
    assert (await client.post("/api/v4/watchlist/refresh?force=true")).status_code == 503
    assert (await client.get("/api/v4/watchlists")).json()["lists"][0]["items"][0]["quote"]["ltp"] == "1500"  # last good price survives


async def test_alerts_become_one_deduplicated_inbox_item_that_clears(client, db_session, fake_angel):
    await setup(client, db_session)
    wl = await mk_list(client)
    it = await add(client, wl, await bi(db_session, "RELIANCE"))
    for bad in ({"kind": "price_above", "threshold": "0"}, {"kind": "price_above", "threshold": "-5"}, {"kind": "day_move_up", "threshold": "75"},
                {"kind": "bogus", "threshold": "1"}):
        assert (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json=bad)).status_code == 422
    alert = (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_above", "threshold": "1600"})).json()
    assert alert["triggered"] is False and alert["text"] == "is at or above ₹1600"
    fake_angel["fetched"] = [quote_entry("2885", 1650)]
    assert (await client.post("/api/v4/watchlist/refresh")).json()["alerts"]["triggered"] == 1
    for i in range(3):  # the condition stays true across refreshes: still ONE item
        fake_angel["fetched"] = [quote_entry("2885", 1650 + i)]
        await client.post("/api/v4/watchlist/refresh?force=true")
    items = (await client.get("/api/v4/inbox")).json()["items"]
    mine = [i for i in items if i["kind"] == "watch_alert"]
    assert len(mine) == 1 and mine[0]["category"] == "information" and "not a recommendation" in mine[0]["detail"] and "RELIANCE" in mine[0]["title"]
    # a review must not resolve it (reviews own different issues)
    from types import SimpleNamespace
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, SimpleNamespace(id=uuid.uuid4(), state_version=1, result={"issues": []}), utcnow())
    await db_session.commit()
    assert [i["status"] for i in (await client.get("/api/v4/inbox?status=all")).json()["items"] if i["kind"] == "watch_alert"] == ["open"]
    fake_angel["fetched"] = [quote_entry("2885", 1500)]  # falls back below the level
    r = (await client.post("/api/v4/watchlist/refresh?force=true")).json()
    assert r["alerts"]["cleared"] == 1
    assert (await client.get("/api/v4/inbox?status=resolved")).json()["items"][0]["kind"] == "watch_alert"
    shown = (await client.get("/api/v4/watchlists")).json()["lists"][0]["items"][0]["alerts"][0]
    assert shown["triggered"] is False


async def test_dismissed_alert_stays_dismissed_and_removing_resolves(client, db_session, fake_angel):
    await setup(client, db_session)
    wl = await mk_list(client)
    it = await add(client, wl, await bi(db_session, "TCS"))
    a = (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "day_move_down", "threshold": "3"})).json()
    fake_angel["fetched"] = [quote_entry("11536", 3800, 4000, -5.0)]
    await client.post("/api/v4/watchlist/refresh")
    item = (await client.get("/api/v4/inbox")).json()["items"][0]
    assert (await client.post(f"/api/v4/inbox/{item['id']}/dismiss", json={"expected_version": item["version"], "reason": "I know"})).status_code == 200
    fake_angel["fetched"] = [quote_entry("11536", 3790, 4000, -5.2)]
    await client.post("/api/v4/watchlist/refresh?force=true")
    assert (await client.get("/api/v4/inbox")).json()["counts"]["open"] == 0  # respected the dismissal
    assert (await client.delete(f"/api/v4/watchlists/alerts/{a['id']}")).status_code == 204
    assert (await db_session.execute(select(func.count()).select_from(WatchAlert))).scalar_one() == 0
    # removing a stock also clears its alert items
    a2 = (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_below", "threshold": "4000"})).json()
    await client.post("/api/v4/watchlist/refresh?force=true")
    assert [i for i in (await client.get("/api/v4/inbox")).json()["items"] if i["kind"] == "watch_alert"]
    await client.delete(f"/api/v4/watchlists/items/{it['item_id']}")
    assert [i for i in (await client.get("/api/v4/inbox")).json()["items"] if i["kind"] == "watch_alert"] == []
    for _ in range(5):
        pass


async def test_alert_limit_per_stock(client, db_session):
    await setup(client, db_session)
    wl = await mk_list(client)
    it = await add(client, wl, await bi(db_session, "TCS"))
    for i in range(5):
        assert (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_above", "threshold": str(5000 + i)})).status_code == 201
    assert (await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_above", "threshold": "9999"})).status_code == 422


async def test_watchlist_shows_personal_context_from_the_real_portfolio(client, db_session, fake_angel):
    a, b = await complete_setup(client, db_session)  # seeds RELIANCE/TCS instruments + a portfolio holding both
    await load_master(db_session)
    wl = await mk_list(client)
    await add(client, wl, await bi(db_session, "RELIANCE"))
    await add(client, wl, await bi(db_session, "SMALLCO"))
    items = {i["symbol"]: i for i in (await client.get("/api/v4/watchlists")).json()["lists"][0]["items"]}
    rel = items["RELIANCE"]["context"]
    assert rel["owned"] is True and rel["accounts"] == ["Broker"] and Decimal(rel["owned_weight"]) > 0
    assert rel["sector"] == "Oil Gas & Consumable Fuels" and Decimal(rel["sector_room_rupees"]) > 0
    assert any("You hold" in f for f in rel["facts"])
    small = items["SMALLCO"]["context"]
    assert small["owned"] is False and small["context_available"] is False
    # a confirmed restriction shows up as a plain fact on the row
    await client.post("/api/v4/preferences", json={"kind": "exclude_sector", "value": "Oil Gas & Consumable Fuels", "confirmed": True})
    rel2 = {i["symbol"]: i for i in (await client.get("/api/v4/watchlists")).json()["lists"][0]["items"]}["RELIANCE"]["context"]
    assert rel2["restriction_conflicts"]


async def test_market_status_endpoint(client, db_session):
    await setup(client, db_session)
    s = (await client.get("/api/v4/market/status")).json()
    assert s["instrument_master_rows"] == 3 and s["data_source"].startswith("Angel One") and "open" in s


async def test_close_pass_refreshes_watched_prices_and_fires_alerts(client, db_session, fake_angel, monkeypatch):
    from app.portfolio_intelligence import scheduler

    await setup(client, db_session)
    wl = await mk_list(client)
    it = await add(client, wl, await bi(db_session, "RELIANCE"))
    await client.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_above", "threshold": "1600"})
    fake_angel["fetched"] = [quote_entry("2885", 1700)]
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())

    async def factory():
        return AngelClient(api_key="k", jwt="j", transport=transport({"market/v1/quote": lambda r: __import__("httpx").Response(200, json=ok({"fetched": fake_angel["fetched"], "unfetched": []}))}))

    r = await scheduler.tick(db_session, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc), client_factory=factory)
    assert r["ran"] and r["watchlist"]["refreshed"] == 1 and r["watchlist"]["alerts"]["triggered"] == 1
    assert [i for i in (await client.get("/api/v4/inbox")).json()["items"] if i["kind"] == "watch_alert"]


async def test_close_pass_skips_watchlist_without_a_session(client, db_session, monkeypatch):
    from app.portfolio_intelligence import scheduler

    await setup(client, db_session)
    wl = await mk_list(client)
    await add(client, wl, await bi(db_session, "RELIANCE"))
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: None)
    r = await scheduler.tick(db_session, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))
    assert r["ran"] and r["watchlist"] == {"skipped": "no valid broker session"}
