"""Securities catalogue (P0): public-file parsers, upserts, linking, corporate actions. Fixture files only, no network.
(The older V3 product-catalogue tests live in test_catalogue.py.)"""

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.market import Instrument
from app.models.securities import CorporateAction, Security
from app.models.watchlist import BrokerInstrument
from app.portfolio_intelligence.catalogue import corporate_actions as ca
from app.portfolio_intelligence.catalogue import parse, sources
from app.portfolio_intelligence.catalogue import sync as sync_mod

FX = Path(__file__).parent / "fixtures" / "catalogue"
D = Decimal
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


TEXTS = {"equity_l": text("equity_l.csv"), "etf_list": text("etf_list.csv"), "sector_map": text("nifty_total_market.csv"), "amfi": text("amfi_navall.txt")}


# --- parsers -------------------------------------------------------------------------------------------------

def test_equity_l_keeps_all_series_and_validates_isin():
    rows, bad = parse.parse_equity_l(TEXTS["equity_l"])
    by = {r["symbol"]: r for r in rows}
    assert bad == 0 and by["RELIANCE"]["isin"] == "INE002A01018" and by["RELIANCE"]["face_value"] == D(10)
    assert {r["series"] for r in rows} == {"EQ", "BE", "BZ"}
    broken = TEXTS["equity_l"] + "BAD,Bad Co,EQ,01-JAN-2020,10,1,INE000000000,10\nNOISIN,No Isin Co,EQ,01-JAN-2020,10,1,,10\n"
    rows2, bad2 = parse.parse_equity_l(broken)
    assert bad2 == 2 and len(rows2) == len(rows)  # bad checksum and missing ISIN are skipped, not guessed


def test_etf_asset_classes_split_gold_silver_from_commodity():
    rows, _ = parse.parse_etf_list(TEXTS["etf_list"])
    assert {r["symbol"]: r["asset_class"] for r in rows} == {
        "NIFTYBEES": "equity", "JUNIORBEES": "equity", "LIQUIDBEES": "debt", "GOLDBEES": "gold", "MON100": "international", "SILVERBEES": "silver"}


def test_sector_map_is_isin_keyed():
    m = parse.parse_sector_map(TEXTS["sector_map"])
    assert m["INE002A01018"] == "Oil Gas & Consumable Fuels" and m["INE467B01029"] == "Information Technology"


def test_amfi_parses_headers_blank_plans_missing_isins_and_stale_schemes():
    rows, bad, newest = parse.parse_amfi_navall(TEXTS["amfi"])
    parse.mark_stale_funds(rows, newest)
    by = {r["scheme_code"]: r for r in rows}
    assert bad == 0 and newest == date(2026, 9, 30) and len(rows) == 14
    d = by["119091"]
    assert (d["plan"], d["option"], d["amc"], d["category"], d["asset_class"]) == ("direct", "growth", "HDFC Mutual Fund", "Debt Scheme - Liquid Fund", "debt")
    assert by["100875"]["isin"] == "INF179KB1IC5" and by["100875"]["isin_reinvest"] is None  # only the reinvestment ISIN exists
    assert by["119088"]["isin"] is None  # both ISINs are '-'
    assert by["100878"]["plan"] is None and by["100878"]["is_active"] is False  # 2015 NAV: stale, never suggested
    assert by["120585"]["is_active"] is True and by["108467"]["is_active"] is False


def test_amfi_skips_unusable_nav_rows():
    bad_text = TEXTS["amfi"] + "999999;INF179KB1HP9;-;Broken Fund;Direct Plan;Growth;N.A.;30-Sep-2026\r\nnot;a;row\r\n"
    rows, bad, _ = parse.parse_amfi_navall(bad_text)
    assert bad == 2 and len(rows) == 14  # "N.A." NAV rejected, and 'not;a;row' is not an 8-field data line


def test_fund_asset_class_uses_word_boundaries():
    f = parse._fund_asset_class
    assert f("Equity Scheme - Large Cap Fund", "Goldman Sachs Nifty 50 Index Fund") == "equity"
    assert f("Other Scheme - FoF Domestic", "HDFC Gold ETF Fund of Fund") == "gold"
    assert f("Other Scheme - Index Funds", "Motilal Oswal Nasdaq 100 FoF") == "international"
    assert f("Other Scheme - Index Funds", "Aditya Birla Sun Life Crisil IBX 50:50 Gilt Plus SDL Apr 2028 Index Fund") == "debt"
    assert f("Other Scheme - Index Funds", "UTI Nifty 50 Index Fund") == "equity"
    assert f("Income/Debt Oriented Schemes - Liquid Fund", "X Liquid Fund") == "debt"
    assert f("Growth/Equity Oriented Schemes - Large Cap", "Y Bluechip") == "equity"
    assert f("Other Scheme - FoF Domestic", "Some Opaque Fund of Funds") == "other"   # undecidable stays unclassified


# --- corporate actions ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("subject,kind,factor,amount,review", [
    ("Bonus 1:1", "bonus", D("0.5"), None, False),
    (" Bonus 1:2", "bonus", D(2) / D(3), None, False),
    ("Bonus 4:1", "bonus", D("0.2"), None, False),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", "split", D("0.1"), None, False),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Rs 2/- Per Share", "split", D("0.4"), None, False),
    ("Dividend - Rs 5.5 Per Share", "dividend", None, D("5.5"), False),
    ("Interim Dividend - Rs 10.50/- Per Share (Purpose Revised)", "dividend", None, D("10.50"), False),
    ("Dividend Rs. 9.50 Per Equity Share", "dividend", None, D("9.50"), False),
    ("Special Dividend - Rs 5 And Final Dividend Rs 3", "dividend", None, None, True),   # two amounts: ambiguous
    ("Annual General Meeting/Dividend - Rs 15 Per Share/Special Dividend - Rs 5 Per Share", "dividend", None, D(20), False),  # each "per share": cash adds up
    ("Dividend - Rs 5 Per Share (Face Value Rs 10)", "dividend", None, None, True),   # a second amount that is not a payment: ambiguous
    ("Annual General Meeting", "meeting", None, None, False),
    ("Extra Ordinary General Meeting", "meeting", None, None, False),
    ("Rights 1:15 @ Premium Rs 1247", "rights", None, None, True),
    ("Demerger", "demerger", None, None, True),
    ("Scheme Of Arrangement - Bonus Ncrps 4:1", "other", None, None, True),            # not an equity bonus
    ("Buy Back of Shares", "buyback", None, None, False),
    ("Distribution - Rs 2.5 Per Unit", "other", None, None, False),
    ("something we have never seen", "other", None, None, True),
])
def test_subject_parsing(subject, kind, factor, amount, review):
    r = ca.parse_subject(subject)
    assert (r["kind"], r["amount"], r["needs_review"]) == (kind, amount, review)
    assert (r["price_factor"] is None) if factor is None else abs(r["price_factor"] - factor) < D("1e-12")


def test_degenerate_ratios_are_never_turned_into_factors():
    for s in ("Bonus 0:1", "Bonus 1:0", "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 10/- Per Share"):
        r = ca.parse_subject(s)
        assert r["price_factor"] is None and r["needs_review"] is True


def test_normalize_records_drops_junk_and_dedupes_whitespace_variants():
    ev = ca.normalize_records(json.loads(text("nse_actions.json")))
    assert len(ev) == 5  # junk x3 dropped, the two Kotak rows differ only in whitespace -> one
    assert [e["kind"] for e in ev if e["symbol"] == "KOTAKBANK"] == ["split"]


def test_adjustment_reads_a_bonus_as_no_crash():
    # Reliance 1:1 bonus, ex 2024-10-28: the raw series halves overnight; adjusted, it is flat.
    events = ca.normalize_records(json.loads(text("nse_actions.json")))
    rel = [e for e in events if e["symbol"] == "RELIANCE"]
    raw = [(date(2024, 10, 25), D("2600")), (date(2024, 10, 28), D("1300"))]
    adj = ca.adjust_closes(raw, rel)
    assert adj == [(date(2024, 10, 25), D("1300.0")), (date(2024, 10, 28), D("1300"))]


def test_cumulative_factor_multiplies_split_and_bonus_and_respects_as_of():
    acts = [{"ex_date": date(2024, 1, 10), "price_factor": D("0.5")}, {"ex_date": date(2025, 1, 10), "price_factor": D("0.1")},
            {"ex_date": date(2025, 6, 1), "price_factor": None}]
    assert ca.cumulative_price_factor(acts, date(2023, 12, 1)) == D("0.05")
    assert ca.cumulative_price_factor(acts, date(2024, 1, 10)) == D("0.1")  # ex-date itself is already on the new basis
    assert ca.cumulative_price_factor(acts, date(2023, 12, 1), as_of=date(2024, 6, 1)) == D("0.5")


def test_review_events_flag_unadjustable_history():
    ev = ca.normalize_records(json.loads(text("nse_actions.json")))
    flagged = ca.review_events_between(ev, date(2023, 1, 1), date(2023, 12, 31))
    assert [e["kind"] for e in flagged] == ["demerger"]


def test_date_chunks_cover_range_without_gaps_or_overlap():
    chunks = sources.date_chunks(date(2021, 10, 1), date(2026, 10, 1))
    assert chunks[0][0] == date(2021, 10, 1) and chunks[-1][1] == date(2026, 10, 1)
    for (a, b), (c, d) in zip(chunks, chunks[1:]):
        assert (c - b).days == 1 and a <= b


# --- sync (DB) --------------------------------------------------------------------------------------------------

async def seed_universe(db):
    inst = Instrument(symbol="RELIANCE", exchange="NSE", isin="INE002A01018", name="Reliance", sector="Energy")
    db.add(inst)
    db.add_all([BrokerInstrument(provider="angel_one", exchange="NSE", token="2885", trading_symbol="RELIANCE-EQ", symbol="RELIANCE", name="RELIANCE", series="EQ", seen_at=NOW),
                BrokerInstrument(provider="angel_one", exchange="NSE", token="999", trading_symbol="GOLDBEES-EQ", symbol="GOLDBEES", name="GOLDBEES", series="EQ", seen_at=NOW),
                BrokerInstrument(provider="angel_one", exchange="NSE", token="1", trading_symbol="NOSUCH-EQ", symbol="NOSUCH", name="NOSUCH", series="EQ", seen_at=NOW)])
    await db.commit()
    return inst


async def test_sync_catalogue_builds_spine_and_links(db_session):
    inst = await seed_universe(db_session)
    report = await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    assert report["stocks"]["added"] == 9 and report["etfs"]["added"] == 6 and report["funds"]["added"] == 14
    rel = (await db_session.execute(select(Security).where(Security.symbol == "RELIANCE"))).scalar_one()
    assert rel.sector == "Oil Gas & Consumable Fuels" and rel.instrument_id == inst.id and rel.source_key == "isin:INE002A01018"
    brokers = {b.symbol: b for b in (await db_session.execute(select(BrokerInstrument))).scalars()}
    gold = (await db_session.execute(select(Security).where(Security.symbol == "GOLDBEES"))).scalar_one()
    assert brokers["RELIANCE"].security_id == rel.id and brokers["GOLDBEES"].security_id == gold.id and brokers["NOSUCH"].security_id is None
    assert report["linked_broker"] == {"linked": 2, "ambiguous": 0}
    # BE-series stocks are in the catalogue but never linked to an Angel -EQ token
    assert (await db_session.execute(select(Security.series).where(Security.symbol == "3IINFOLTD"))).scalar_one() == "BE"


async def test_sync_is_idempotent_and_keeps_sector_across_refreshes(db_session):
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    n1 = (await db_session.execute(select(func.count()).select_from(Security))).scalar_one()
    again = await sync_mod.sync_catalogue(db_session, {"equity_l": TEXTS["equity_l"]}, NOW)  # sectors file not re-sent
    assert again["stocks"]["added"] == 0 and (await db_session.execute(select(func.count()).select_from(Security))).scalar_one() == n1
    assert (await db_session.execute(select(Security.sector).where(Security.symbol == "TCS"))).scalar_one() == "Information Technology"


async def test_missing_rows_retire_but_only_from_their_own_source(db_session, monkeypatch):
    monkeypatch.setattr(sync_mod, "MIN_COMPLETE_FRACTION", 0.5)  # the 9-row fixture: losing 1 row is 89%, fine at real scale
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    shorter = "\n".join(l for l in TEXTS["equity_l"].splitlines() if not l.startswith("TCS,"))
    r = await sync_mod.sync_catalogue(db_session, {"equity_l": shorter}, NOW)
    assert r["stocks"]["retired"] == 1
    assert (await db_session.execute(select(Security.is_active).where(Security.symbol == "TCS"))).scalar_one() is False
    back = await sync_mod.sync_catalogue(db_session, {"equity_l": TEXTS["equity_l"]}, NOW)   # TCS is listed again
    assert back["stocks"]["retired"] == 0
    assert (await db_session.execute(select(Security.is_active).where(Security.symbol == "TCS"))).scalar_one() is True
    assert (await db_session.execute(select(Security.is_active).where(Security.symbol == "GOLDBEES"))).scalar_one() is True  # ETF list untouched


async def test_empty_or_garbage_file_is_refused_and_nothing_is_retired(db_session):
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    for key in ("equity_l", "etf_list", "amfi"):
        with pytest.raises(ValueError):
            await sync_mod.sync_catalogue(db_session, {key: "<html>Access Denied</html>"}, NOW)
        await db_session.rollback()
    assert (await db_session.execute(select(Security.is_active).where(Security.symbol == "TCS"))).scalar_one() is True


async def test_ambiguous_symbol_stays_unlinked(db_session):
    await seed_universe(db_session)
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    # a second active EQ security with the same symbol (e.g. a re-used ticker) must not be guessed between
    db_session.add(Security(source_key="isin:INE999Z01019", kind="stock", isin="INE999Z01019", symbol="RELIANCE", name="Other", series="EQ", source="nse_equity_l", is_active=True, seen_at=NOW))
    await db_session.commit()
    r = await sync_mod.link_broker_instruments(db_session)
    assert r["ambiguous"] == 1
    assert (await db_session.execute(select(BrokerInstrument.security_id).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one() is None


async def test_store_actions_is_idempotent_and_updates(db_session):
    ev = ca.normalize_records(json.loads(text("nse_actions.json")))
    assert (await sync_mod.store_actions(db_session, ev, NOW)) == {"added": 5, "updated": 0}
    assert (await sync_mod.store_actions(db_session, ev, NOW)) == {"added": 0, "updated": 5}
    row = (await db_session.execute(select(CorporateAction).where(CorporateAction.kind == "bonus"))).scalar_one()
    assert row.price_factor == D("0.5") and row.needs_review is False


async def test_sync_actions_stops_at_first_failed_window_and_keeps_earlier_ones(db_session):
    calls = []

    async def fetch(a, b):
        calls.append(a)
        if len(calls) == 2:
            raise sources.SourceError("HTTP 403 from www.nseindia.com")
        return json.loads(text("nse_actions.json"))

    async def nopause():
        return None

    r = await sync_mod.sync_actions(db_session, date(2025, 1, 1), date(2026, 10, 1), fetch=fetch, pause=nopause, now=NOW, retry_delays=())
    assert r["windows_done"] == 1 and r["failed"]["error"].startswith("HTTP 403") and len(calls) == 2
    assert (await db_session.execute(select(func.count()).select_from(CorporateAction))).scalar_one() == 5
    # resume point = newest stored ex-date not in the future
    assert await sync_mod.latest_action_date(db_session, date(2026, 10, 1)) == date(2026, 6, 5)
    assert await sync_mod.latest_action_date(db_session, date(2026, 1, 1)) == date(2024, 10, 28)


async def test_refresh_catalogue_survives_one_failed_source(db_session, monkeypatch):
    async def fetch_text(name, client=None):
        if name == "etf_list":
            raise sources.SourceError("HTTP 403 from nsearchives.nseindia.com")
        return TEXTS[name]

    async def fetch_actions(a, b, client=None):
        return []

    async def nopause():
        return None

    monkeypatch.setattr(sources, "fetch_text", fetch_text)
    monkeypatch.setattr(sync_mod.sources, "fetch_actions", fetch_actions)
    monkeypatch.setattr(sync_mod.sources, "polite_sleep", nopause)
    monkeypatch.setattr(sync_mod, "sync_actions", lambda *a, **k: _coro({"windows_done": 0, "events_stored": 0, "failed": None}))
    r = await sync_mod.refresh_catalogue(db_session, NOW)
    assert r["fetch_errors"] == {"etf_list": "HTTP 403 from nsearchives.nseindia.com"} and "etfs" not in r["catalogue"] and r["catalogue"]["stocks"]["added"] == 9


async def _coro(v):
    return v


async def test_host_allowlist_blocks_other_hosts():
    import httpx

    async with httpx.AsyncClient() as c:
        with pytest.raises(sources.SourceError):
            await sources._get(c, "https://evil.example.com/EQUITY_L.csv")


# --- API + job -------------------------------------------------------------------------------------------------

async def api_seed(db_session):
    await seed_universe(db_session)
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    from app.models.watchlist import MarketQuote

    bi = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one()
    db_session.add(MarketQuote(broker_instrument_id=bi.id, ltp=D("1390.5"), prev_close=D("1380"), percent_change=D("0.76"), volume=9_000_000_000, retrieved_at=NOW, mode="FULL"))
    await sync_mod.store_actions(db_session, ca.normalize_records(json.loads(text("nse_actions.json"))), NOW)


async def test_list_filters_search_and_prices(client, db_session):
    await api_seed(db_session)
    r = (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "q": "reliance"})).json()
    assert r["total"] == 1 and r["items"][0]["symbol"] == "RELIANCE" and r["items"][0]["tradable_in_angel"] is True
    assert r["items"][0]["price"]["ltp"] == "1390.5" and r["items"][0]["price"]["volume"] == 9_000_000_000  # > int32
    funds = (await client.get("/api/v4/catalogue/securities", params={"kind": "mutual_fund", "plan": "direct", "option": "growth"})).json()
    assert [i["scheme_code"] for i in funds["items"]] == ["119091"] and funds["items"][0]["nav"] == "5593.1126" and "price" not in funds["items"][0]
    sector = (await client.get("/api/v4/catalogue/securities", params={"sector": "Information Technology"})).json()
    assert {i["symbol"] for i in sector["items"]} == {"INFY", "TCS"}
    assert (await client.get("/api/v4/catalogue/securities", params={"asset_class": "gold"})).json()["items"][0]["symbol"] == "GOLDBEES"


async def test_inactive_hidden_by_default_and_wildcards_in_search_are_literal(client, db_session):
    await api_seed(db_session)
    default = (await client.get("/api/v4/catalogue/securities", params={"kind": "mutual_fund", "limit": 200})).json()
    allrows = (await client.get("/api/v4/catalogue/securities", params={"kind": "mutual_fund", "include_inactive": True, "limit": 200})).json()
    assert allrows["total"] == 14 and default["total"] == 10  # the 4 stale schemes (NAV frozen since 2012-2020) are hidden
    assert (await client.get("/api/v4/catalogue/securities", params={"q": "%"})).json()["total"] == (await client.get("/api/v4/catalogue/securities")).json()["total"]


async def test_pagination_is_stable_and_bounded(client, db_session):
    await api_seed(db_session)
    a = (await client.get("/api/v4/catalogue/securities", params={"limit": 7, "offset": 0})).json()["items"]
    b = (await client.get("/api/v4/catalogue/securities", params={"limit": 7, "offset": 7})).json()["items"]
    assert not ({i["id"] for i in a} & {i["id"] for i in b})
    assert (await client.get("/api/v4/catalogue/securities", params={"limit": 5000})).status_code == 422
    assert (await client.get("/api/v4/catalogue/securities", params={"kind": "bond"})).status_code == 422


async def test_facets_and_detail_with_actions(client, db_session):
    await api_seed(db_session)
    f = (await client.get("/api/v4/catalogue/facets")).json()
    assert f["kinds"]["stock"] == 9 and f["unclassified_stocks"] == 4  # KOTAKBANK/HDFC/INFY/TCS/RELIANCE classified; 4 others not
    assert {"value": "Information Technology", "count": 2} in f["sectors"]
    sid = (await client.get("/api/v4/catalogue/securities", params={"q": "RELIANCE"})).json()["items"][0]["id"]
    d = (await client.get(f"/api/v4/catalogue/securities/{sid}")).json()
    kinds = {a["kind"]: a for a in d["corporate_actions"]}
    assert kinds["bonus"]["price_factor"] == "0.5" and kinds["demerger"]["needs_review"] is True and kinds["dividend"]["amount"] == "6"
    assert (await client.get(f"/api/v4/catalogue/securities/{uuid.uuid4()}")).status_code == 404


async def test_refresh_queues_once_and_status_reports_it(client, db_session):
    first = (await client.post("/api/v4/catalogue/refresh")).json()
    second = (await client.post("/api/v4/catalogue/refresh")).json()
    assert first["queued"] is True and second == {"queued": False, "already_queued": True, "job_id": None}
    st = (await client.get("/api/v4/catalogue/status")).json()
    assert st["last_job"]["status"] == "queued" and st["counts"] == {}


def test_job_outcome_distinguishes_partial_from_nothing():
    from app.portfolio_intelligence.catalogue.jobs import _outcome

    assert _outcome({"fetch_errors": {"amfi": "x"}, "catalogue": {"stocks": {"added": 1, "updated": 0}}})[0] == "done"
    assert _outcome({"fetch_errors": {"a": "x", "b": "y"}, "actions": {"windows_done": 0, "failed": {"error": "e"}}})[0] == "UNAVAILABLE"
    assert _outcome({"fetch_errors": {}, "actions": {"windows_done": 2, "events_stored": 5, "failed": None}})[0] == "done"


async def test_close_pass_queues_one_catalogue_refresh_per_day_and_never_runs_it_inline(db_session, monkeypatch):
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence import scheduler
    from tests.test_living import WED_CLOSE, setup_user

    await setup_user(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: None)
    r = await scheduler.tick(db_session, WED_CLOSE)
    assert r["ran"] and r["catalogue_job"]
    jobs = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "catalogue_refresh"))).scalars().all()
    assert len(jobs) == 1 and jobs[0].status == "queued"
    assert "catalogue_refresh" not in scheduler.run_inline.__defaults__[0]  # bulk fetching is the worker's job only


async def test_bootstrap_queues_only_when_catalogue_is_empty(db_session):
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence import scheduler
    from tests.test_living import setup_user

    await setup_user(db_session)
    await scheduler._bootstrap_catalogue(db_session)
    await scheduler._bootstrap_catalogue(db_session)  # second call: one is already queued
    assert len((await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "catalogue_refresh"))).scalars().all()) == 1
    await sync_mod.sync_catalogue(db_session, {"equity_l": TEXTS["equity_l"]}, NOW)
    for j in (await db_session.execute(select(PortfolioJob))).scalars():
        j.status = "done"
    await db_session.commit()
    await scheduler._bootstrap_catalogue(db_session)
    assert len((await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "catalogue_refresh"))).scalars().all()) == 1


async def test_reparse_corrects_rows_stored_by_an_older_parser(db_session):
    db_session.add(CorporateAction(symbol="ABC", ex_date=date(2026, 5, 1), subject="Annual General Meeting", kind="other", needs_review=True, source="nse", fetched_at=NOW))
    db_session.add(CorporateAction(symbol="ABC", ex_date=date(2026, 6, 1), subject="Bonus 1:1", kind="bonus", ratio_num=D(1), ratio_den=D(1), price_factor=D("0.5"), needs_review=False, source="nse", fetched_at=NOW))
    await db_session.commit()
    assert await sync_mod.reparse_actions(db_session) == 1      # only the AGM row was wrong
    assert await sync_mod.reparse_actions(db_session) == 0      # and it is stable
    row = (await db_session.execute(select(CorporateAction).where(CorporateAction.symbol == "ABC", CorporateAction.kind == "meeting"))).scalar_one()
    assert row.needs_review is False


async def test_a_transient_window_failure_is_retried_with_backoff_before_giving_up(db_session):
    attempts, slept = [], []

    async def flaky(a, b):
        attempts.append(a)
        if len(attempts) in (2, 3):  # window 1 ok; window 2 fails twice then works
            raise sources.SourceError("request failed: ConnectError")
        return json.loads(text("nse_actions.json"))

    async def nopause():
        return None

    async def fake_sleep(seconds):
        slept.append(seconds)

    r = await sync_mod.sync_actions(db_session, date(2025, 1, 1), date(2025, 9, 1), fetch=flaky, pause=nopause, now=NOW, retry_delays=(3.0, 10.0), sleep=fake_sleep)
    assert r["failed"] is None and r["windows_done"] == 3 and slept == [3.0, 10.0]
    stuck = await sync_mod.sync_actions(db_session, date(2025, 1, 1), date(2025, 3, 1), fetch=lambda a, b: _raise(), pause=nopause, now=NOW, retry_delays=(1.0, 2.0), sleep=fake_sleep)
    assert stuck["windows_done"] == 0 and stuck["failed"]["error"] == "HTTP 429 from www.nseindia.com"


async def _raise():
    raise sources.SourceError("HTTP 429 from www.nseindia.com")


async def test_partial_refresh_keeps_its_result_and_is_retried_not_marked_done(db_session, test_engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.single_user import SINGLE_USER_ID
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence import jobs as jobs_mod
    from app.portfolio_intelligence.catalogue import jobs as cat_jobs
    from app.utils.time import utcnow

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(cat_jobs, "AsyncSessionLocal", factory)
    from tests.test_living import setup_user

    await setup_user(db_session)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="catalogue_refresh", request_key="k", status="running", attempts=1, worker_token="tok", created_at=utcnow())
    db_session.add(job)
    await db_session.commit()

    async def partial(db, now=None):
        return {"fetch_errors": {"amfi": "HTTP 503 from portal.amfiindia.com"}, "catalogue": {"stocks": {"added": 2, "updated": 0}},
                "actions": {"windows_done": 3, "events_stored": 40, "failed": None}}

    monkeypatch.setattr(sync_mod, "refresh_catalogue", partial)
    await cat_jobs.process_refresh(job.id, "tok")
    await db_session.refresh(job)
    assert job.status == "queued" and job.error_code == "UNAVAILABLE" and job.not_before is not None  # retried later, not "done"
    assert job.result["fetch_errors"] == {"amfi": "HTTP 503 from portal.amfiindia.com"} and job.result["counts"] == {"stocks": 2}

    job.status, job.worker_token, job.attempts = "running", "tok2", 2

    async def full(db, now=None):
        return {"fetch_errors": {}, "catalogue": {"stocks": {"added": 0, "updated": 2}}, "actions": {"windows_done": 1, "events_stored": 1, "failed": None}}

    monkeypatch.setattr(sync_mod, "refresh_catalogue", full)
    await db_session.commit()
    await cat_jobs.process_refresh(job.id, "stale")   # superseded attempt: must not write
    await db_session.refresh(job)
    assert job.status == "running"
    await cat_jobs.process_refresh(job.id, "tok2")
    await db_session.refresh(job)
    assert job.status == "done" and job.error_code is None


async def test_downloads_retry_transient_errors_but_not_client_errors(monkeypatch):
    import httpx

    calls = {"n": 0}
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(sources.asyncio, "sleep", fake_sleep)

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("All connection attempts failed")
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await sources._get(c, "https://portal.amfiindia.com/spages/NAVAll.txt")
    assert r.text == "ok" and calls["n"] == 3 and slept == [2.0, 6.0]

    calls["n"] = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(404))) as c:
        with pytest.raises(sources.SourceError, match="HTTP 404"):
            await sources._get(c, "https://portal.amfiindia.com/spages/NAVAll.txt")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429))) as c:
        with pytest.raises(sources.SourceError, match="HTTP 429"):
            await sources._get(c, "https://portal.amfiindia.com/spages/NAVAll.txt", retry_delays=(0.0,))


async def test_a_short_file_retires_nothing_and_says_why(db_session):
    await sync_mod.sync_catalogue(db_session, TEXTS, NOW)
    header, first = TEXTS["equity_l"].splitlines()[:2]
    r = await sync_mod.sync_catalogue(db_session, {"equity_l": header + "\n" + first + "\n"}, NOW)   # 1 of 9 rows: not a full list
    assert r["stocks"]["retired"] == 0 and "looks truncated" in r["stocks"]["skipped"]
    assert (await db_session.execute(select(func.count()).select_from(Security).where(Security.kind == "stock", Security.is_active.is_(True)))).scalar_one() == 9
