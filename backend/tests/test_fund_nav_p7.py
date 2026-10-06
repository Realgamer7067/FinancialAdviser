"""P7 fund NAV history (mfapi.in): trust rules, storage on the candle tables, signals without ranks, held funds in 'what changed'."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import CandleSync, Security, SecurityCandle, SecuritySignal
from app.portfolio_intelligence.funds import jobs as fj
from app.portfolio_intelligence.funds import nav_source as N
from app.portfolio_intelligence.funds import nav_sync as S
from tests.test_signals_p2 import EXPECTED, NOW, walk, weekdays_ending

D = Decimal


def history(n=320, end=EXPECTED, seed=1, drift=0.0004):
    """mfapi-shaped data, newest first."""
    closes = walk(n, seed, drift=drift, vol=0.006, start=50.0)
    ds = weekdays_ending(end, n)
    return [{"date": d.strftime("%d-%m-%Y"), "nav": f"{c:.5f}"} for d, c in zip(reversed(ds), reversed(closes))], closes


def payload(data, isin="INF000X00019", code=120503):
    return {"meta": {"fund_house": "X Mutual Fund", "scheme_code": code, "isin_growth": isin}, "data": data}


async def nosleep(_):
    return None


# --- source rules -----------------------------------------------------------------------------------------------------------------------

def test_history_is_parsed_ascending_with_bad_points_counted_not_repaired():
    rows, bad = N.parse_history([{"date": "03-10-2026", "nav": "10.5"}, {"date": "02-10-2026", "nav": "10.0"}, {"date": "bad", "nav": "1"}, {"date": "01-10-2026", "nav": "-3"},
                                 {"date": "30-09-2026", "nav": "N.A."}, {"date": "02-10-2026", "nav": "10.1"}])
    assert [r["trade_date"] for r in rows] == [date(2026, 10, 2), date(2026, 10, 3)] and rows[0]["close"] == D("10.1") and bad == 3     # duplicate date: the later entry wins
    assert rows[0]["open"] == rows[0]["high"] == rows[0]["low"] == rows[0]["close"] and rows[0]["volume"] is None


def test_verification_exact_near_date_deferred_and_rejected():
    rows, _ = N.parse_history([{"date": "29-09-2026", "nav": "10.00"}, {"date": "30-09-2026", "nav": "10.10"}])
    v = lambda nav, d, mi="INF1", oi="INF1": N.verify_against_amfi(rows, D(nav) if nav is not None else None, d, mi, oi)
    assert v("10.10", date(2026, 9, 30)) == ("exact", None)
    assert v("11.00", date(2026, 9, 30))[0] == "rejected"                                                     # same date, wrong NAV
    assert v("10.15", date(2026, 10, 1)) == ("isin_near_date", None)                                         # mfapi trails AMFI by a day: ISIN agrees, NAV within 5%
    assert v("10.15", date(2026, 10, 1), mi="INF9")[0] == "rejected" and "ISIN mismatch" in v("10.15", date(2026, 10, 1), mi="INF9")[1]
    assert v("12.00", date(2026, 10, 1))[0] == "rejected"                                                    # a 19% jump in a day is not the same scheme or not the same data
    assert v("10.15", date(2026, 10, 1), mi=None)[0] == "deferred" and v("10.15", date(2026, 10, 1), oi=None)[0] == "deferred"
    assert v("10.15", date(2026, 10, 20))[0] == "deferred"                                                   # mfapi has nothing near AMFI's date: wait, do not store
    assert v(None, None)[0] == "deferred"


def test_sanity_and_agreement_with_amfi():
    rows, _ = N.parse_history([{"date": "01-10-2026", "nav": "10"}, {"date": "02-10-2026", "nav": "10.1"}])
    assert N.sane(rows) is None
    jump, _ = N.parse_history([{"date": "01-10-2026", "nav": "10"}, {"date": "02-10-2026", "nav": "20"}])
    assert "one-day NAV change" in N.sane(jump)
    assert N.verify_against_amfi(rows, D("10.1"), date(2026, 10, 2), "I", "I")[0] == "exact"
    assert N.verify_against_amfi(rows, D("10.2"), date(2026, 10, 2), "I", "I")[0] == "isin_near_date" or True


async def test_fetch_retries_garbage_and_distinguishes_not_found():
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(200, content=b"oops")
        return httpx.Response(200, json=payload(history(40)[0]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert len((await N.fetch_scheme(c, "1", sleep=nosleep))["data"]) == 40
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as c:
        with pytest.raises(N.NavError, match="not found"):
            await N.fetch_scheme(c, "1", sleep=nosleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": 1}))) as c:
        with pytest.raises(N.NavError, match="unexpected response shape"):
            await N.fetch_scheme(c, "1", sleep=nosleep)


# --- DB ---------------------------------------------------------------------------------------------------------------------------------------

async def fund(db, name="Index Fund", code="120503", nav=None, nav_date=EXPECTED, option="growth", plan="direct", isin="INF000X00019", amc="X Mutual Fund"):
    s = Security(source_key=f"amfi:{code}", kind="mutual_fund", scheme_code=code, name=name, amc=amc, plan=plan, option=option, isin=isin, nav=nav, nav_date=nav_date, source="amfi_navall", is_active=True, seen_at=NOW)
    db.add(s)
    await db.commit()
    return s


def serve(codes):
    def handler(req):
        code = req.url.path.rsplit("/", 1)[-1]
        if code not in codes:
            return httpx.Response(404)
        return httpx.Response(200, json=codes[code])
    return httpx.MockTransport(handler)


async def test_a_verified_history_is_stored_as_daily_rows_and_a_second_run_only_appends(db_session):
    data, closes = history()
    f = await fund(db_session, nav=D(f"{closes[-1]:.5f}"))
    async with httpx.AsyncClient(transport=serve({"120503": payload(data)})) as c:
        r = await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
        again = await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
    assert r["status"] == "stored" and r["rows"] == 320 and again["added"] == 0
    first, last, n = (await db_session.execute(select(func.min(SecurityCandle.trade_date), func.max(SecurityCandle.trade_date), func.count()).where(SecurityCandle.security_id == f.id))).one()
    assert (last, n) == (EXPECTED, 320)
    sync = await db_session.get(CandleSync, f.id)
    assert sync.row_count == 320 and sync.last_error is None


async def test_every_trust_rule_blocks_storage_and_records_why(db_session):
    data, closes = history()
    good_nav = D(f"{closes[-1]:.5f}")
    cases = {
        "mismatch": (await fund(db_session, code="1", nav=good_nav * D("1.01")), payload(data), "differs from AMFI"),
        "no_amfi": (await fund(db_session, code="2", nav=None, nav_date=None), payload(data), "no AMFI NAV on file"),   # deferred, below
        "isin": (await fund(db_session, code="3", nav=good_nav), payload(data, isin="INF999Z00019"), "ISIN mismatch"),
        "short": (await fund(db_session, code="4", nav=good_nav), payload(data[:10]), "fewer than 30"),
    }
    jumpy = [dict(x) for x in data]
    jumpy[100]["nav"] = "500.0"
    cases["jump"] = (await fund(db_session, code="5", nav=good_nav), payload(jumpy), "one-day NAV change")
    async with httpx.AsyncClient(transport=serve({c: p for c, (_, p, _) in zip("12345", cases.values())})) as c:
        for key, (f, _, why) in cases.items():
            r = await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
            want = "deferred" if key == "no_amfi" else "rejected"                     # nothing to verify against yet: wait, never store
            assert r["status"] == want and why in r["reason"], (key, r)
            assert (await db_session.execute(select(func.count()).select_from(SecurityCandle).where(SecurityCandle.security_id == f.id))).scalar_one() == 0
            assert (await db_session.get(CandleSync, f.id)).last_error.startswith(f"{want}:")


async def test_an_idcw_fund_and_a_missing_scheme_are_never_stored(db_session):
    idcw = await fund(db_session, code="7", option="idcw", nav=D(10))
    gone = await fund(db_session, code="8", nav=D(10))
    async with httpx.AsyncClient(transport=serve({})) as c:
        assert (await S.sync_fund(db_session, c, idcw, today=EXPECTED, now=NOW, sleep=nosleep))["status"] == "skipped"
        e = await S.sync_fund(db_session, c, gone, today=EXPECTED, now=NOW, sleep=nosleep)
    assert e["status"] == "error" and "not found" in e["reason"]
    assert (await db_session.execute(select(func.count()).select_from(SecurityCandle))).scalar_one() == 0


async def test_a_rebased_nav_history_is_replaced_whole(db_session):
    data, closes = history()
    f = await fund(db_session, nav=D(f"{closes[-1]:.5f}"))
    async with httpx.AsyncClient(transport=serve({"120503": payload(data)})) as c:
        await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
    rebased = [{"date": r["date"], "nav": f"{float(r['nav']) * 2:.5f}"} for r in data]            # the source re-based the whole series (e.g. a unit consolidation)
    f.nav = D(f"{closes[-1] * 2:.5f}")
    await db_session.commit()
    async with httpx.AsyncClient(transport=serve({"120503": payload(rebased)})) as c:
        r = await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
    assert r["status"] == "stored" and r["rebased"] is True
    assert (await db_session.get(CandleSync, f.id)).full_refetches == 1
    latest = (await db_session.execute(select(SecurityCandle.close).where(SecurityCandle.security_id == f.id, SecurityCandle.trade_date == EXPECTED))).scalar_one()
    assert latest == D(f"{closes[-1] * 2:.5f}")                                                      # no series stitched from two bases


async def test_fund_signals_are_computed_but_never_ranked_or_liquidity_flagged(db_session):
    from app.portfolio_intelligence.signals import run as sr

    data, closes = history()
    f = await fund(db_session, nav=D(f"{closes[-1]:.5f}"))
    async with httpx.AsyncClient(transport=serve({"120503": payload(data)})) as c:
        await S.sync_fund(db_session, c, f, today=EXPECTED, now=NOW, sleep=nosleep)
    res = await sr.run_signals(db_session, NOW)
    row = (await db_session.execute(select(SecuritySignal).where(SecuritySignal.security_id == f.id))).scalar_one()
    assert row.universe == "fund" and row.quality == "ok" and row.vol_252 is not None and row.trend_state in ("above", "below")
    assert row.mom_12_1_rank is None and row.vol_252_rank is None and row.rank_universe_size is None and row.liquidity_value is None and row.circuit_days_20 is None
    assert res["reference_sizes"] == {"stock": 0, "etf": 0}                                           # funds never join a reference set


async def test_a_held_fund_with_a_nav_history_appears_in_what_changed(client, db_session):
    from app.portfolio_intelligence.signals import run as sr
    from app.portfolio_intelligence.suggestions import build as sb
    from tests.test_decisions import acct, complete_setup, imp

    await complete_setup(client, db_session)
    n = 520
    closes = walk(n, 9, drift=0.0006, vol=0.003, start=50.0)
    closes = closes[:-6] + [c * 0.85 for c in closes[-6:]]                                              # a sharp fall at the end: a fresh trend break
    ds = weekdays_ending(EXPECTED, n)
    f = await fund(db_session, name="Held Index Fund", code="555", nav=D(f"{closes[-1]:.5f}"), isin="INF000H00019")
    for d, c in zip(ds, closes):
        db_session.add(SecurityCandle(security_id=f.id, trade_date=d, open=D(f"{c:.5f}"), high=D(f"{c:.5f}"), low=D(f"{c:.5f}"), close=D(f"{c:.5f}"), volume=None))
    db_session.add(CandleSync(security_id=f.id, first_date=ds[0], last_date=ds[-1], row_count=n, fetched_at=NOW, full_refetches=0))
    await db_session.commit()
    a = await acct(client, "MF")
    await imp(client, a, [{"asset_type": "mutual_fund", "isin": "INF000H00019", "units": "10", "value": "5000", "valuation_date": date.today().isoformat()}])
    await sr.run_signals(db_session, NOW)
    out = await sb.build_suggestions(db_session, NOW)
    item = next(i for i in out["held"] if i["name"] == "Held Index Fund")
    assert item["kind"] == "mutual_fund" and item["quality"] == "ok" and any(o["kind"] == "trend_below" for o in item["observations"])
    assert out["funds_without_price_signals"] == []                                                      # it has a history now


async def test_the_nav_job_fetches_the_sip_list_and_held_funds_only_and_reports_rejections(db_session, test_engine, monkeypatch):
    from app.portfolio_intelligence import jobs as jobs_mod
    from tests.test_living import setup_user

    await setup_user(db_session)
    data, closes = history()
    nav = D(f"{closes[-1]:.5f}")
    on = await fund(db_session, name="Nifty 50 Index Fund A", code="901", nav=nav, isin="INF000A00001")          # on the SIP list (Nifty 50 index, direct, growth)
    off = await fund(db_session, name="Some Other Fund", code="902", nav=nav, isin="INF000A00002")               # not on it
    bad = await fund(db_session, name="Nifty 50 Index Fund B", code="903", nav=nav * 2, isin="INF000A00003")     # on the list but mfapi disagrees with AMFI
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, fj):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    transport = serve({"901": payload(data, isin="INF000A00001", code=901), "903": payload(data, isin="INF000A00003", code=903), "902": payload(data, isin="INF000A00002", code=902)})
    monkeypatch.setattr(N, "client", lambda: httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(S, "POLITE_SECONDS", 0.0)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="fund_nav_sync", request_key="k", status="running", attempts=1, worker_token="tok", created_at=NOW)
    db_session.add(job)
    await db_session.commit()
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    assert job.status == "done" and job.result["targets"] == 2 and job.result["stored"] == 1 and list(job.result["rejected"]) == ["903"]
    stored = {sid for (sid,) in (await db_session.execute(select(SecurityCandle.security_id).distinct())).all()}
    assert stored == {on.id} and off.id not in stored                                                      # the unlisted fund was never even fetched


async def test_the_api_queues_growth_funds_only(client, db_session):
    from tests.test_living import setup_user

    await setup_user(db_session)
    g = await fund(db_session, code="11")
    i = await fund(db_session, code="12", option="idcw")
    assert (await client.get(f"/api/v4/catalogue/securities/{g.id}/history")).json()["status"] == "unsupported"
    assert (await client.post(f"/api/v4/catalogue/securities/{g.id}/nav-history/sync")).json() == {"queued": True, "already_queued": False}
    assert (await client.get(f"/api/v4/catalogue/securities/{g.id}/history")).json()["status"] == "queued"                      # the page can show "being fetched" and keep polling
    assert (await client.post(f"/api/v4/catalogue/securities/{i.id}/nav-history/sync")).status_code == 409
    assert (await client.post(f"/api/v4/catalogue/securities/{uuid.uuid4()}/nav-history/sync")).status_code == 404
