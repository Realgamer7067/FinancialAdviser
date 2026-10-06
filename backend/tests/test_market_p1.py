"""P1: candle parsing/refresh, per-event adjustment audit, snapshot and backfill jobs, market API. No network."""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle
from app.models.watchlist import BrokerInstrument, MarketQuote, Watchlist, WatchlistItem
from app.portfolio_intelligence.market import adjust as adj
from app.portfolio_intelligence.market import candles as cm
from app.portfolio_intelligence.market import jobs as mj
from app.portfolio_intelligence.market import quotes as qm
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AuthExpired, BadResponse, RateLimited
from tests.angel_fixtures import ok, transport
from tests.test_securities_catalogue import NOW, TEXTS, seed_universe
from tests.test_securities_catalogue import sync_mod

D = Decimal
WED_EVE = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)   # Wed 17:30 IST: market closed, close is final
WED_MID = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)    # Wed 11:30 IST: open
SAT = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def ts(d: date) -> str:
    return f"{d.isoformat()}T00:00:00+05:30"


def raw_rows(start: date, closes: list[float]):
    return [[ts(start + timedelta(days=i)), c, c * 1.01, c * 0.99, c, 1000 + i] for i, c in enumerate(closes)]


# --- candle parsing ---------------------------------------------------------------------------------------------

def test_parse_candles_sorts_dedupes_and_rejects_bad_rows_without_repairing():
    raw = [[ts(date(2026, 9, 2)), 10, 11, 9, 10.5, 100], [ts(date(2026, 9, 1)), 10, 11, 9, 10, 100],
           [ts(date(2026, 9, 1)), 10, 12, 9, 11, 200],                       # same date again: last wins
           [ts(date(2026, 9, 3)), 0, 11, 9, 10, 100],                         # zero price
           [ts(date(2026, 9, 4)), 10, 9, 11, 10, 100],                        # high < low
           [ts(date(2026, 9, 5)), 10, 11, 9, 12, 100],                        # close outside the range
           [ts(date(2026, 9, 6)), 10, 11, 9, 10, -5],                         # negative volume
           ["garbage", 1, 2, 3, 4, 5], [ts(date(2026, 9, 7)), "x", 1, 1, 1, 1], "nope", [ts(date(2026, 9, 8)), 5, 6]]
    rows, bad = cm.parse_candles(raw)
    assert [r["trade_date"] for r in rows] == [date(2026, 9, 1), date(2026, 9, 2)] and rows[0]["volume"] == 200 and bad == 8


def test_expected_last_session_and_last_close():
    assert cm.expected_last_session(WED_EVE) == date(2026, 9, 30) and cm.expected_last_session(WED_MID) == date(2026, 9, 29)
    assert cm.expected_last_session(SAT) == date(2026, 10, 2)
    assert qm.last_close_time(WED_MID).date() == date(2026, 9, 29) and qm.last_close_time(WED_EVE).date() == date(2026, 9, 30)
    assert qm.last_close_time(SAT).date() == date(2026, 10, 2)


# --- per-event adjustment audit ----------------------------------------------------------------------------------

def ev(ex, kind, factor, review=False):
    return {"ex_date": ex, "kind": kind, "price_factor": None if factor is None else D(str(factor)), "needs_review": review}


def closes_around(ex: date, before: float, after: float):
    return [(ex - timedelta(days=2), D(str(before))), (ex - timedelta(days=1), D(str(before))), (ex, D(str(after))), (ex + timedelta(days=1), D(str(after)))]


def test_audit_tells_raw_from_already_adjusted():
    ex = date(2024, 10, 28)
    raw = adj.audit_events(closes_around(ex, 2600, 1300), [ev(ex, "bonus", "0.5")])
    assert raw[0]["status"] == "raw"
    already = adj.audit_events(closes_around(ex, 1327.85, 1334.35), [ev(ex, "bonus", "0.5")])   # the real RELIANCE closes from Angel
    assert already[0]["status"] == "adjusted"
    assert adj.audit_events(closes_around(ex, 1000, 700), [ev(ex, "bonus", "0.5")])[0]["status"] == "unclear"   # -30%: neither a halving nor a normal day
    assert adj.audit_events(closes_around(ex, 1000, 880), [ev(ex, "bonus", "0.5")])[0]["status"] == "adjusted"  # -12% on the day: ordinary for an adjusted series
    assert adj.audit_events(closes_around(ex, 1000, 540), [ev(ex, "bonus", "0.5")])[0]["status"] == "raw"      # a halving plus 8% noise


def test_audit_small_factors_are_indeterminate_and_never_applied():
    ex = date(2025, 3, 3)
    rows = [{"trade_date": d, "open": c, "high": c, "low": c, "close": c} for d, c in closes_around(ex, 100, 91)]
    out = adj.adjust_series(rows, [ev(ex, "bonus", "0.9")])    # bonus 1:9: only 10%
    assert out["audit"][0]["status"] == "indeterminate" and out["applied"] == 0 and out["rows"][0]["close"] == D(100)
    assert out["unreliable"] and "indeterminate" in out["unreliable"][0]["reason"]


def test_audit_clearly_unclear_move_is_flagged():
    ex = date(2025, 3, 3)
    a = adj.audit_events(closes_around(ex, 100, 20), [ev(ex, "split", "0.5")])   # -80%: more than a split explains
    assert a[0]["status"] == "unclear"


def test_adjust_series_applies_only_raw_events_and_compounds_them():
    ex1, ex2 = date(2024, 6, 3), date(2025, 6, 2)
    rows = []
    base = date(2024, 5, 27)
    px = [1000, 1000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500, 500, 500, 250]   # two raw 1:1 events
    days = [base + timedelta(days=i) for i in range(5)] + [ex1 + timedelta(days=i) for i in range(7)] + [ex2 - timedelta(days=1), ex2]
    for d, c in zip(days, px):
        rows.append({"trade_date": d, "open": D(c), "high": D(c), "low": D(c), "close": D(c), "volume": 1})
    out = adj.adjust_series(rows, [ev(ex1, "bonus", "0.5"), ev(ex2, "bonus", "0.5")])
    assert out["applied"] == 2 and {r["close"] for r in out["rows"]} == {D(250)}
    assert out["rows"][0]["volume"] == 1                                 # non-price fields untouched


def test_audit_conflicting_duplicates_collapse_or_flag():
    ex = date(2024, 10, 28)
    cl = closes_around(ex, 2600, 1300)
    same = adj.audit_events(cl, [ev(ex, "bonus", "0.5"), ev(ex, "bonus", "0.5")])    # the same event re-worded: one
    assert [a["status"] for a in same] == ["raw"]
    clash = adj.audit_events(cl, [ev(ex, "bonus", "0.5"), ev(ex, "bonus", "0.6")])
    assert [a["status"] for a in clash] == ["conflict"]
    both = adj.audit_events(cl, [ev(ex, "bonus", "0.5"), ev(ex, "split", "0.2")])    # different kinds on one date are legitimate
    assert sorted(a["kind"] for a in both) == ["bonus", "split"]


def test_audit_events_outside_the_series_and_no_data():
    cl = closes_around(date(2025, 1, 10), 100, 100)
    out = adj.audit_events(cl, [ev(date(2020, 1, 1), "bonus", "0.5"), ev(date(2030, 1, 1), "bonus", "0.5")])
    assert [a["status"] for a in out] == ["outside", "outside"]
    assert adj.audit_events([], [ev(date(2020, 1, 1), "bonus", "0.5")])[0]["status"] == "outside"


def test_rights_and_demerger_mark_history_unreliable_but_are_never_adjusted():
    ex = date(2026, 4, 30)
    rows = [{"trade_date": d, "open": c, "high": c, "low": c, "close": c} for d, c in closes_around(ex, 289.5, 271.55)]
    out = adj.adjust_series(rows, [ev(ex, "demerger", None, review=True)])
    assert out["applied"] == 0 and out["rows"][0]["close"] == D("289.5") and "demerger" in out["unreliable"][0]["reason"]
    assert adj.adjust_series(rows, [ev(date(2020, 1, 1), "rights", None, review=True)])["unreliable"] == []   # outside the series


# --- Angel client: candles ----------------------------------------------------------------------------------------

async def test_client_candle_request_shape_and_errors():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok([[ts(date(2026, 9, 1)), 1, 2, 1, 2, 5]]))

    c = AngelClient(api_key="k", jwt="j", transport=transport({"getCandleData": handler}))
    rows = await c.get_daily_candles("NSE", "2885", "2024-10-22", "2024-11-01")
    assert rows[0][4] == 2 and seen["body"] == {"exchange": "NSE", "symboltoken": "2885", "interval": "ONE_DAY", "fromdate": "2024-10-22 09:15", "todate": "2024-11-01 15:30"}
    none = AngelClient(api_key="k", jwt="j", transport=transport({"getCandleData": ok(None)}))
    assert await none.get_daily_candles("NSE", "1", "2024-01-01", "2024-01-02") == []
    bad = AngelClient(api_key="k", jwt="j", transport=transport({"getCandleData": ok({"not": "a list"})}))
    with pytest.raises(BadResponse):
        await bad.get_daily_candles("NSE", "1", "2024-01-01", "2024-01-02")


# --- DB: apply_fetch ------------------------------------------------------------------------------------------------

async def one_security(db, symbol="RELIANCE"):
    await seed_universe(db)
    await sync_mod.sync_catalogue(db, TEXTS, NOW)
    return (await db.execute(select(Security).where(Security.symbol == symbol))).scalar_one()


def parsed(start: date, closes):
    return cm.parse_candles(raw_rows(start, closes))[0]


async def test_apply_fetch_appends_and_is_idempotent(db_session):
    s = await one_security(db_session)
    start = date(2026, 9, 1)
    a = await cm.apply_fetch(db_session, s.id, parsed(start, [100, 101, 102]), today=date(2026, 9, 3), now=NOW)
    assert a == {"added": 3, "rebased": False, "rows": 3}
    b = await cm.apply_fetch(db_session, s.id, parsed(start + timedelta(days=2), [102, 103]), today=date(2026, 9, 4), now=NOW)   # overlap day matches
    assert b["added"] == 1 and b["rebased"] is False and b["rows"] == 4
    c = await cm.apply_fetch(db_session, s.id, parsed(start + timedelta(days=2), [102, 103]), today=date(2026, 9, 4), now=NOW)
    assert c["added"] == 0
    sync = await db_session.get(CandleSync, s.id)
    assert (sync.first_date, sync.last_date, sync.row_count, sync.full_refetches) == (start, date(2026, 9, 4), 4, 0)


async def test_a_rebased_overlap_replaces_the_whole_series(db_session):
    s = await one_security(db_session)
    start = date(2026, 9, 1)
    await cm.apply_fetch(db_session, s.id, parsed(start, [200, 202, 204, 206]), today=date(2026, 9, 4), now=NOW)
    # the source re-adjusted history after a split: every close halved, including the overlap
    half_overlap = parsed(start + timedelta(days=2), [102, 103, 104])
    full = parsed(start, [100, 101, 102, 103, 104])

    async def refetch():
        return full

    r = await cm.apply_fetch(db_session, s.id, half_overlap, today=date(2026, 9, 5), now=NOW, refetch_full=refetch)
    assert r["rebased"] is True and r["rows"] == 5
    closes = [c for (c,) in (await db_session.execute(select(SecurityCandle.close).where(SecurityCandle.security_id == s.id).order_by(SecurityCandle.trade_date))).all()]
    assert closes == [D(100), D(101), D(102), D(103), D(104)]          # no series stitched from two adjustment bases
    assert (await db_session.get(CandleSync, s.id)).full_refetches == 1


# --- jobs: targets, backfill, snapshot ------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, candles=None, quotes=None, fail=None):
        self.candles, self.quotes, self.fail, self.calls = candles or {}, quotes or [], fail or {}, []

    async def get_daily_candles(self, exchange, token, a, b):
        self.calls.append((token, a, b))
        if token in self.fail:
            raise self.fail[token]
        return self.candles.get(token, [])

    async def get_quotes(self, exchange_tokens, mode="LTP"):
        self.calls.append(("quotes", len(exchange_tokens["NSE"])))
        toks = set(exchange_tokens["NSE"])
        return {"fetched": [q for q in self.quotes if q["symbolToken"] in toks], "unfetched": []}

    async def aclose(self):
        pass


async def test_candle_targets_tiers_and_once_per_day_rule(db_session):
    await one_security(db_session)
    wl = Watchlist(user_id=SINGLE_USER_ID, name="L", created_at=NOW)
    db_session.add(wl)
    await db_session.flush()
    gold = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "GOLDBEES"))).scalar_one()
    db_session.add(WatchlistItem(watchlist_id=wl.id, broker_instrument_id=gold.id, added_at=NOW))
    await db_session.commit()
    syms = {i: s for i, s in (await db_session.execute(select(Security.id, Security.symbol))).all()}
    targets = await mj.candle_targets(db_session, WED_EVE)
    assert [syms[t[0]] for t in targets] == ["GOLDBEES", "RELIANCE"] and [t[2] for t in targets] == [0, 2]  # watched first; RELIANCE has a sector; NOSUCH is not in the catalogue
    s = (await db_session.execute(select(Security).where(Security.symbol == "RELIANCE"))).scalar_one()
    # fetched today with data up to the last session: nothing to do; behind the session but fetched today: wait until tomorrow
    db_session.add(CandleSync(security_id=s.id, first_date=date(2026, 1, 1), last_date=date(2026, 9, 30), row_count=10, fetched_at=WED_EVE, full_refetches=0))
    await db_session.commit()
    assert [syms[t[0]] for t in await mj.candle_targets(db_session, WED_EVE)] == ["GOLDBEES"]
    sync = await db_session.get(CandleSync, s.id)
    sync.last_date = date(2026, 9, 28)
    await db_session.commit()
    assert [syms[t[0]] for t in await mj.candle_targets(db_session, WED_EVE)] == ["GOLDBEES"]                      # fetched today already (holiday?)
    assert "RELIANCE" in [syms[t[0]] for t in await mj.candle_targets(db_session, WED_EVE + timedelta(days=1))]    # tomorrow it is due again
    only = await mj.candle_targets(db_session, WED_EVE, security_ids=[str(s.id)])
    assert [syms[t[0]] for t in only] == ["RELIANCE"]                                                               # on demand ignores tier/day rules


async def test_backfill_first_fetch_then_incremental_and_per_security_errors(db_session):
    await one_security(db_session)
    rel = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one()
    gold = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "GOLDBEES"))).scalar_one()
    rel_id, rel_tok, gold_id, gold_tok = rel.security_id, rel.token, gold.security_id, gold.token   # plain values: a rollback expires ORM objects
    targets = [(rel_id, rel_tok, 2), (gold_id, gold_tok, 1)]
    client = FakeClient(candles={rel_tok: raw_rows(date(2026, 9, 1), [100, 101, 102])}, fail={gold_tok: BadResponse("bad")})
    r = await mj.backfill_candles(db_session, client, targets, WED_EVE)
    assert r["securities"] == 1 and r["errors"] == 1 and r["rows_added"] == 3
    assert client.calls[0][1] == (date(2026, 9, 30) - timedelta(days=cm.HISTORY_DAYS)).isoformat()   # first fetch: five years back
    assert (await db_session.get(CandleSync, gold_id)).last_error == "BAD_RESPONSE"
    # second run is incremental: it asks from (last stored - 7 days)
    client2 = FakeClient(candles={rel_tok: raw_rows(date(2026, 9, 3), [102, 103])})
    r2 = await mj.backfill_candles(db_session, client2, [(rel_id, rel_tok, 2)], WED_EVE)
    assert r2["rows_added"] == 1 and client2.calls[0][1] == (date(2026, 9, 3) - timedelta(days=7)).isoformat()


async def test_auth_and_rate_limit_abort_the_job_but_keep_earlier_securities(db_session):
    await one_security(db_session)
    rel = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one()
    gold = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "GOLDBEES"))).scalar_one()
    rel_id, rel_tok, gold_id, gold_tok = rel.security_id, rel.token, gold.security_id, gold.token
    client = FakeClient(candles={rel_tok: raw_rows(date(2026, 9, 1), [100, 101])}, fail={gold_tok: RateLimited("slow down")})
    with pytest.raises(RateLimited):
        await mj.backfill_candles(db_session, client, [(rel_id, rel_tok, 2), (gold_id, gold_tok, 1)], WED_EVE)
    assert (await db_session.execute(select(func.count()).select_from(SecurityCandle).where(SecurityCandle.security_id == rel_id))).scalar_one() == 2
    client2 = FakeClient(fail={rel_tok: AuthExpired("expired")})
    with pytest.raises(AuthExpired):
        await mj.backfill_candles(db_session, client2, [(rel_id, rel_tok, 2)], WED_EVE)


def quote_entry(token, ltp, pct, vol=1000):
    return {"symbolToken": token, "tradingSymbol": "X", "ltp": ltp, "close": ltp / (1 + pct / 100), "percentChange": pct, "tradeVolume": vol,
            "52WeekHigh": ltp * 1.2, "52WeekLow": ltp * 0.7, "open": ltp, "high": ltp, "low": ltp}


async def test_snapshot_commits_each_chunk_and_reports_progress(db_session):
    await one_security(db_session)
    brokers = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.security_id.is_not(None)).order_by(BrokerInstrument.symbol))).scalars().all()
    assert len(brokers) == 2
    client = FakeClient(quotes=[quote_entry(b.token, 100 + i, 1.5 * (i + 1)) for i, b in enumerate(brokers)])
    r = await mj.snapshot_quotes(db_session, client, WED_EVE, chunk=1)
    assert r["chunks"] == 2 and r["chunks_done"] == 2 and r["refreshed"] == 2 and [c for c in client.calls] == [("quotes", 1), ("quotes", 1)]
    assert (await db_session.execute(select(func.count()).select_from(MarketQuote))).scalar_one() == 2


# --- the typed job end to end ---------------------------------------------------------------------------------------

async def run_job(db_session, test_engine, monkeypatch, kind, client, params=None):
    from app.portfolio_intelligence import jobs as jobs_mod

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, mj):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(mj, "load_session", lambda now=None: type("S", (), {"jwt": "j"})())
    monkeypatch.setattr(mj, "AngelClient", lambda jwt=None: client)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind=kind, request_key="k", status="running", attempts=1, worker_token="tok", created_at=NOW, params=params)
    db_session.add(job)
    await db_session.commit()
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    return job


async def test_backfill_job_chains_a_follow_up_when_work_remains(db_session, test_engine, monkeypatch):
    from tests.test_living import setup_user

    await setup_user(db_session)
    await one_security(db_session)
    monkeypatch.setattr(mj, "BACKFILL_CHUNK", 1)   # one security per job: the other must come back as a follow-up
    rel = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one()
    gold = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "GOLDBEES"))).scalar_one()
    client = FakeClient(candles={rel.token: raw_rows(date(2026, 9, 1), [100, 101]), gold.token: raw_rows(date(2026, 9, 1), [50, 51])})
    job = await run_job(db_session, test_engine, monkeypatch, "candle_backfill", client)
    assert job.status == "done" and job.result["securities"] == 1 and job.result["remaining"] == 1
    follow = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "candle_backfill", PortfolioJob.status == "queued"))).scalars().all()
    assert len(follow) == 1 and follow[0].id != job.id


async def test_market_job_without_a_session_fails_as_auth_expired_without_retry(db_session, test_engine, monkeypatch):
    from tests.test_living import setup_user

    await setup_user(db_session)
    await one_security(db_session)
    from app.portfolio_intelligence import jobs as jobs_mod

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(mj, "AsyncSessionLocal", factory)
    monkeypatch.setattr(mj, "load_session", lambda now=None: None)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="market_snapshot", request_key="k", status="running", attempts=1, worker_token="tok", created_at=NOW)
    db_session.add(job)
    await db_session.commit()
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    assert job.status == "failed" and job.error_code == "AUTH_EXPIRED"


async def test_snapshot_job_rate_limit_is_retried_with_backoff(db_session, test_engine, monkeypatch):
    from tests.test_living import setup_user

    await setup_user(db_session)
    await one_security(db_session)

    class Limited(FakeClient):
        async def get_quotes(self, *a, **k):
            raise RateLimited("slow down")

    job = await run_job(db_session, test_engine, monkeypatch, "market_snapshot", Limited())
    assert job.status == "queued" and job.error_code == "RATE_LIMITED" and job.not_before is not None


# --- API ---------------------------------------------------------------------------------------------------------------

async def api_seed(db_session):
    s = await one_security(db_session)
    brokers = {b.symbol: b for b in (await db_session.execute(select(BrokerInstrument))).scalars()}
    for sym, ltp, pct, vol, t in (("RELIANCE", 1390, D("2.5"), 5_000_000, NOW), ("GOLDBEES", 80, D("-1.2"), 9_000_000_000, NOW)):
        db_session.add(MarketQuote(broker_instrument_id=brokers[sym].id, ltp=D(ltp), prev_close=D(ltp), percent_change=pct, volume=vol, retrieved_at=t, mode="FULL"))
    await db_session.commit()
    return s


async def test_sorting_by_quote_fields_puts_unpriced_last(client, db_session):
    await api_seed(db_session)
    up = (await client.get("/api/v4/catalogue/securities", params={"sort": "change", "order": "desc", "limit": 200})).json()["items"]
    assert [i["symbol"] for i in up[:2]] == ["RELIANCE", "GOLDBEES"] and up[2].get("price") is None
    down = (await client.get("/api/v4/catalogue/securities", params={"sort": "change", "order": "asc", "limit": 200})).json()["items"]
    assert [i["symbol"] for i in down[:2]] == ["GOLDBEES", "RELIANCE"]
    vol = (await client.get("/api/v4/catalogue/securities", params={"sort": "volume", "order": "desc"})).json()["items"]
    assert vol[0]["symbol"] == "GOLDBEES"
    assert (await client.get("/api/v4/catalogue/securities", params={"sort": "bogus"})).status_code == 422


async def test_movers(client, db_session):
    await api_seed(db_session)
    m = (await client.get("/api/v4/catalogue/movers", params={"kind": "stock"})).json()
    assert [i["symbol"] for i in m["gainers"]] == ["RELIANCE"] and m["as_of"]
    e = (await client.get("/api/v4/catalogue/movers", params={"kind": "etf", "min_volume": 10_000_000_000})).json()
    assert e["gainers"] == []                                         # the volume floor removes thin names


async def test_visible_refresh_never_calls_the_broker_when_nothing_is_stale(client, db_session, monkeypatch):
    from app.api.v4 import catalogue as api

    await api_seed(db_session)
    ids = [i["id"] for i in (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "q": "reliance"})).json()["items"]]
    calls = []
    monkeypatch.setattr(api, "AngelClient", lambda jwt=None: pytest.fail("no broker call expected"))
    monkeypatch.setattr(api.quotes_mod, "market_status", lambda now=None: {"open": False, "label": "closed"})
    monkeypatch.setattr(api.quotes_mod, "last_close_time", lambda now=None: datetime(2020, 1, 1, tzinfo=timezone.utc))  # saved quotes are newer than the last close
    r = (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": ids})).json()
    assert r["refreshed"] is False and "last session" in r["reason"] and r["items"][0]["symbol"] == "RELIANCE" and not calls


async def test_visible_refresh_economy_and_degradation(client, db_session, monkeypatch):
    from app.api.v4 import catalogue as api

    await api_seed(db_session)
    rel = (await client.get("/api/v4/catalogue/securities", params={"q": "reliance", "kind": "stock"})).json()["items"][0]["id"]
    monkeypatch.setattr(api.quotes_mod, "market_status", lambda now=None: {"open": True, "label": "open"})
    # no session -> saved prices with a reason, still 200
    monkeypatch.setattr(api, "load_session", lambda now=None: None)
    r = (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": [rel]})).json()
    assert r["refreshed"] is False and "not connected" in r["reason"] and r["items"][0]["price"]["ltp"] == "1390"
    # with a session: one broker call, then the 3 s floor answers from saved prices
    monkeypatch.setattr(api, "load_session", lambda now=None: type("S", (), {"jwt": "j"})())
    brokers = (await db_session.execute(select(BrokerInstrument).where(BrokerInstrument.symbol == "RELIANCE"))).scalar_one()
    fake = FakeClient(quotes=[quote_entry(brokers.token, 1400, 3.0)])
    monkeypatch.setattr(api, "AngelClient", lambda jwt=None: fake)
    monkeypatch.setattr(api, "_last_quote_call", 0.0)
    r1 = (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": [rel]})).json()
    assert r1["refreshed"] is True and r1["items"][0]["price"]["ltp"] == "1400"
    r2 = (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": [rel]})).json()
    assert r2["refreshed"] is False and "moments ago" in r2["reason"] and len(fake.calls) == 1
    # expired session: degrade, never 5xx
    monkeypatch.setattr(api, "_last_quote_call", 0.0)

    class Expired(FakeClient):
        async def get_quotes(self, *a, **k):
            raise AuthExpired("expired")
    monkeypatch.setattr(api, "AngelClient", lambda jwt=None: Expired())
    r3 = await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": [rel]})
    assert r3.status_code == 200 and "expired" in r3.json()["reason"]


async def test_visible_refresh_validates_input(client):
    assert (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": []})).status_code == 422
    assert (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": [str(uuid.uuid4())] * 51})).status_code == 422
    assert (await client.post("/api/v4/catalogue/quotes/refresh", json={"security_ids": ["nope"]})).status_code == 422


async def test_history_endpoint_states_and_verified_adjustment(client, db_session):
    s = await api_seed(db_session)
    empty = (await client.get(f"/api/v4/catalogue/securities/{s.id}/history")).json()
    assert empty["status"] == "none" and empty["candles"] == []
    q = (await client.post(f"/api/v4/catalogue/securities/{s.id}/history/sync")).json()
    assert q == {"queued": True, "already_queued": False}
    assert (await client.post(f"/api/v4/catalogue/securities/{s.id}/history/sync")).json()["already_queued"] is True
    assert (await client.get(f"/api/v4/catalogue/securities/{s.id}/history")).json()["status"] == "queued"
    # the real RELIANCE bonus case: Angel's closes are flat across 2024-10-28, so the audit says "adjusted" and nothing is applied
    ex = date(2024, 10, 28)
    for d, c in [(date(2024, 10, 24), "1339.8"), (date(2024, 10, 25), "1327.85"), (ex, "1334.35"), (date(2024, 10, 29), "1340")]:
        db_session.add(SecurityCandle(security_id=s.id, trade_date=d, open=D(c), high=D(c), low=D(c), close=D(c), volume=1))
    db_session.add(CandleSync(security_id=s.id, first_date=date(2024, 10, 24), last_date=date(2024, 10, 29), row_count=4, fetched_at=NOW, full_refetches=0))
    db_session.add(CorporateAction(symbol="RELIANCE", ex_date=ex, subject="Bonus 1:1", kind="bonus", price_factor=D("0.5"), needs_review=False, source="nse", fetched_at=NOW))
    db_session.add(CorporateAction(symbol="RELIANCE", ex_date=date(2024, 10, 26), subject="Demerger", kind="demerger", needs_review=True, source="nse", fetched_at=NOW))
    await db_session.commit()
    h = (await client.get(f"/api/v4/catalogue/securities/{s.id}/history", params={"days": 400})).json()
    assert h["status"] == "ready" and h["adjustment"]["applied"] == 0
    assert h["adjustment"]["audit"] == [{"ex_date": "2024-10-28", "kind": "bonus", "factor": "0.5", "ratio": "1.0049", "status": "adjusted"}]
    assert h["adjustment"]["unreliable"][0]["reason"].startswith("demerger") and [c["c"] for c in h["candles"]] == ["1339.8", "1327.85", "1334.35", "1340"]


async def test_history_is_unsupported_for_funds_and_404_for_unknown(client, db_session):
    await api_seed(db_session)
    fund = (await client.get("/api/v4/catalogue/securities", params={"kind": "mutual_fund"})).json()["items"][0]["id"]
    assert (await client.get(f"/api/v4/catalogue/securities/{fund}/history")).json()["status"] == "unsupported"
    assert (await client.post(f"/api/v4/catalogue/securities/{fund}/history/sync")).status_code == 409
    assert (await client.get(f"/api/v4/catalogue/securities/{uuid.uuid4()}/history")).status_code == 404


async def test_market_jobs_status(client, db_session):
    await api_seed(db_session)
    s = (await client.get("/api/v4/catalogue/market-jobs")).json()
    assert s["market_snapshot"] is None and s["candle_securities"] == 0 and s["quotes"] == 2


# --- scheduler ---------------------------------------------------------------------------------------------------------

async def test_close_pass_queues_market_jobs_only_with_a_session(db_session, monkeypatch):
    from app.portfolio_intelligence import scheduler
    from tests.test_living import WED_CLOSE, setup_user

    await setup_user(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: None)
    r = await scheduler.tick(db_session, WED_CLOSE)
    assert r["market_jobs"] == {"skipped": "no valid broker session"}
    assert (await db_session.execute(select(func.count()).select_from(PortfolioJob).where(PortfolioJob.kind.in_(("market_snapshot", "candle_backfill"))))).scalar_one() == 0


async def test_close_pass_with_a_session_queues_snapshot_and_backfill(db_session, monkeypatch):
    from app.portfolio_intelligence import scheduler
    from tests.test_living import WED_CLOSE, setup_user

    await setup_user(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())
    r = await scheduler.tick(db_session, WED_CLOSE)
    assert r["market_jobs"]["snapshot"] and r["market_jobs"]["backfill"]
    assert "market_snapshot" not in scheduler.run_inline.__defaults__[0] and "candle_backfill" not in scheduler.run_inline.__defaults__[0]


async def test_bootstrap_waits_for_linked_securities_and_a_session_and_backs_off_after_failure(db_session, monkeypatch):
    from app.portfolio_intelligence import scheduler
    from tests.test_living import setup_user

    await setup_user(db_session)

    async def count(kind):
        return (await db_session.execute(select(func.count()).select_from(PortfolioJob).where(PortfolioJob.kind == kind))).scalar_one()

    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())
    await scheduler._bootstrap_market(db_session)
    assert await count("market_snapshot") == 0                       # nothing linked yet
    await one_security(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: None)
    await scheduler._bootstrap_market(db_session)
    assert await count("market_snapshot") == 0                       # no session
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())
    await scheduler._bootstrap_market(db_session)
    await scheduler._bootstrap_market(db_session)
    assert await count("market_snapshot") == 1 and await count("candle_backfill") == 1   # once, not per tick
    for j in (await db_session.execute(select(PortfolioJob))).scalars():
        j.status = "failed"
        j.created_at = datetime.now(timezone.utc)
    await db_session.commit()
    await scheduler._bootstrap_market(db_session)
    assert await count("market_snapshot") == 1                       # a recent failure suppresses the retry


async def test_search_ranks_exact_symbol_then_prefix_before_alphabetical(client, db_session):
    s = await api_seed(db_session)
    db_session.add(Security(source_key="isin:INE000A01011", kind="stock", isin="INE000A01011", symbol="AAARELIANCE", name="Aaa Reliance Chemotex Industries", series="EQ", source="nse_equity_l", is_active=True, seen_at=NOW))
    db_session.add(Security(source_key="isin:INE000B01012", kind="stock", isin="INE000B01012", symbol="RELIANCEPWR", name="Reliance Power Limited", series="EQ", source="nse_equity_l", is_active=True, seen_at=NOW))
    await db_session.commit()
    items = (await client.get("/api/v4/catalogue/securities", params={"q": "reliance", "kind": "stock"})).json()["items"]
    assert [i["symbol"] for i in items] == ["RELIANCE", "RELIANCEPWR", "AAARELIANCE"]      # exact, symbol prefix, then the rest
    # an explicit non-name sort is respected
    by_change = (await client.get("/api/v4/catalogue/securities", params={"q": "reliance", "kind": "stock", "sort": "change", "order": "desc"})).json()["items"]
    assert by_change[0]["symbol"] == "RELIANCE"


async def test_an_on_demand_job_never_blocks_the_bulk_chain_or_another_security(db_session):
    from tests.test_living import setup_user

    await setup_user(db_session)
    one = await mj.enqueue_backfill(db_session, "ondemand", security_ids=["a"], now=NOW)
    assert one is not None
    bulk = await mj.enqueue_backfill(db_session, "bulk", now=NOW)                  # different params: not blocked (this was the stall)
    other = await mj.enqueue_backfill(db_session, "ondemand", security_ids=["b"], now=NOW)
    assert bulk is not None and other is not None
    assert await mj.enqueue_backfill(db_session, "ondemand", security_ids=["a"], now=NOW) is None   # same params: blocked
    assert await mj.enqueue_backfill(db_session, "bulk2", now=NOW) is None                         # a second bulk job: blocked
    bulk.status = "running"
    await db_session.commit()
    assert await mj.enqueue_backfill(db_session, "continue", now=NOW) is None                      # blocked by the running bulk job...
    assert await mj.enqueue_backfill(db_session, "continue", now=NOW, exclude_job_id=bulk.id) is not None  # ...unless it is the caller itself


async def test_manual_market_refresh_needs_a_session(client, db_session, monkeypatch):
    from app.api.v4 import catalogue as api
    from tests.test_living import setup_user

    await setup_user(db_session)
    monkeypatch.setattr(api, "load_session", lambda now=None: None)
    assert (await client.post("/api/v4/catalogue/market-jobs/refresh")).status_code == 409
    monkeypatch.setattr(api, "load_session", lambda now=None: object())
    r = (await client.post("/api/v4/catalogue/market-jobs/refresh")).json()
    assert r == {"snapshot": {"queued": True}, "backfill": {"queued": True}}
    assert (await client.post("/api/v4/catalogue/market-jobs/refresh")).json() == {"snapshot": {"queued": False}, "backfill": {"queued": False}}
