"""P7 expense ratios in the database: chunked fetching, failures isolated, matching coverage, replacement, job chain, API."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import SchemeTer, Security, SecurityTer
from app.portfolio_intelligence.costs import jobs as tj
from app.portfolio_intelligence.costs import ter_source as T
from app.portfolio_intelligence.costs import ter_sync as S
from tests.test_ter_p7 import nosleep, pages, row

D = Decimal
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def server(data_by_amc, fail=(), calls=None):
    """AMFI stand-in: {mf_id: [rows]} served in pages of 3; AMCs in `fail` always answer garbage."""
    def handler(req):
        mf = int(req.url.params["MF_ID"])
        if calls is not None:
            calls.append((mf, req.url.params["Month"], int(req.url.params["page"])))
        if mf in fail:
            return httpx.Response(200, content=b"<html>x</html>")
        rows = data_by_amc.get(mf, [])
        if not rows:
            return httpx.Response(200, json={"data": [], "meta": {"page": 1, "pageSize": 3, "total": 0, "pageCount": 1}})
        pg = pages(rows)
        return httpx.Response(200, json=pg[int(req.url.params["page"]) - 1])
    return httpx.MockTransport(handler)


AMCS = [{"mf_id": 28, "name": "UTI Mutual Fund"}, {"mf_id": 22, "name": "SBI Mutual Fund"}, {"mf_id": 3, "name": "Axis Mutual Fund"}]
DATA = {28: [row("U1", "UTI - Nifty 50 Index Fund", mf=28, r="0.60", d="0.20"), row("U1", "UTI - Nifty 50 Index Fund", dt="2026-09-22", mf=28, r="9", d="9"), row("U2", "UTI - Bond Fund", mf=28)],
        22: [row("S1", "SBI - Nifty 50 Index Fund", mf=22, r="0.50", d="0.18")], 3: [row("A1", "Axis Nifty 50 Index Fund", mf=3, r="0.40", d="0.12")]}


async def test_fetch_chunk_stores_the_latest_row_per_scheme_and_isolates_a_failing_amc(db_session):
    calls = []
    async with httpx.AsyncClient(transport=server(DATA, fail={22}, calls=calls)) as c:
        res = await S.fetch_chunk(db_session, AMCS, today=date(2026, 10, 1), client=c, sleep=nosleep)
    assert res["done"] == [28, 3] and list(res["failed"]) == [22] and "malformed JSON" in res["failed"][22] and res["remaining"] == []
    got = {r.nsdl_code: r for r in (await db_session.execute(select(SchemeTer))).scalars()}
    assert set(got) == {"U1", "U2", "A1"} and got["U1"].direct_ter == D("0.2") and got["U1"].ter_date == date(2026, 9, 30) and got["U1"].amc_name == "UTI Mutual Fund"   # the newer row won
    assert {m for _, m, _ in calls} == {"10-2026"} and {p for mf, _, p in calls if mf == 28} == {1}        # the current month was served, so no fallback; UTI fits one page here


async def test_an_amc_with_nothing_for_the_new_month_falls_back_to_the_previous_one(db_session):
    seen = []

    def handler(req):
        seen.append(req.url.params["Month"])
        if req.url.params["Month"] == "10-2026":
            return httpx.Response(200, json={"data": [], "meta": {"page": 1, "pageSize": 3, "total": 0, "pageCount": 1}})
        return httpx.Response(200, json=pages([row("U1", "UTI - Nifty 50 Index Fund", mf=28)])[0])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        res = await S.fetch_chunk(db_session, AMCS[:1], today=date(2026, 10, 1), client=c, sleep=nosleep)
    assert seen == ["10-2026", "09-2026"] and res["done"] == [28]


async def test_the_time_budget_stops_a_chunk_and_returns_the_rest(db_session):
    ticks = iter([0.0, 1.0, 999.0, 999.0, 999.0])
    async with httpx.AsyncClient(transport=server(DATA)) as c:
        res = await S.fetch_chunk(db_session, AMCS, today=date(2026, 10, 1), client=c, sleep=nosleep, budget=5.0, clock=lambda: next(ticks))
    assert res["done"] == [28] and [a["mf_id"] for a in res["remaining"]] == [22, 3]


async def seed_funds(db):
    rows = [("UTI Nifty 50 Index Fund", "UTI Mutual Fund", "direct", "mutual_fund", "INF000U00011"), ("UTI Nifty 50 Index Fund", "UTI Mutual Fund", "regular", "mutual_fund", "INF000U00029"),
            ("Axis Nifty 50 Index Fund", "Axis Mutual Fund", "direct", "mutual_fund", "INF000A00011"), ("SBI Nifty 50 Index Fund", "SBI Mutual Fund", "direct", "mutual_fund", "INF000S00011"),
            ("Mystery Fund", "UTI Mutual Fund", "direct", "mutual_fund", "INF000M00011"),
            ("UTI Sensex ETF", "UTI Mutual Fund", None, "mutual_fund", "INF000E00011")]
    out = {}
    for i, (name, amc, plan, kind, isin) in enumerate(rows):
        s = Security(source_key=f"amfi:{500 + i}", kind=kind, scheme_code=str(500 + i), name=name, amc=amc, plan=plan, option="growth" if plan else None, isin=isin, source="amfi_navall", is_active=True, seen_at=NOW)
        db.add(s)
        out[f"{name}|{plan}"] = s
    etf = Security(source_key="isin:INF000E00011", kind="etf", isin="INF000E00011", symbol="UTISENSEX", name="UTI-SENSEX", series="EQ", source="nse_etf_list", is_active=True, seen_at=NOW)
    db.add(etf)
    await db.commit()
    return out, etf


async def test_matching_covers_defensible_matches_only_and_replaces_previous_matches(db_session):
    funds, etf = await seed_funds(db_session)
    data = dict(DATA)
    data[28] = data[28] + [row("U9", "UTI - Sensex ETF", mf=28, r="0.31", d="0.0")]
    async with httpx.AsyncClient(transport=server(data)) as c:
        await S.fetch_chunk(db_session, AMCS, today=date(2026, 10, 1), client=c, sleep=nosleep)
    res = await S.match_all(db_session, NOW)
    assert res["mutual_funds_matched"] == 4 and res["mutual_funds_total"] == 6 and res["etfs_matched"] == 1 and res["etfs_total"] == 1
    t = {x.security_id: x for x in (await db_session.execute(select(SecurityTer))).scalars()}
    assert t[funds["UTI Nifty 50 Index Fund|direct"].id].ter == D("0.2") and t[funds["UTI Nifty 50 Index Fund|regular"].id].ter == D("0.6")
    assert funds["Mystery Fund|direct"].id not in t                                                       # no TER scheme with that name: unknown, not guessed
    assert t[etf.id].ter == D("0.31") and t[etf.id].plan_used == "etf"                                    # the ETF took the Regular column, reached through its AMFI ISIN
    await db_session.execute(SchemeTer.__table__.delete().where(SchemeTer.nsdl_code == "S1"))
    await db_session.commit()
    again = await S.match_all(db_session, NOW)
    assert again["mutual_funds_matched"] == 3                                                             # a scheme that disappeared leaves no stale match behind
    assert (await db_session.execute(select(func.count()).select_from(SecurityTer))).scalar_one() == 4


async def test_the_job_chains_chunks_and_matches_only_after_the_last(db_session, test_engine, monkeypatch):
    from app.portfolio_intelligence import jobs as jobs_mod
    from tests.test_living import setup_user

    await setup_user(db_session)
    await seed_funds(db_session)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, tj):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(tj, "utcnow", lambda: NOW)
    transport = server(DATA)

    async def amcs(c, sleep=None):
        return AMCS

    monkeypatch.setattr(T, "list_amcs", amcs)
    monkeypatch.setattr(T, "client", lambda: httpx.AsyncClient(transport=transport))
    real_chunk = S.fetch_chunk

    async def limited(db, amcs, **kw):
        res = await real_chunk(db, amcs[:1], **kw)
        res["remaining"] = amcs[1:]                                         # only the first AMC is processed in this chunk
        return res

    monkeypatch.setattr(S, "fetch_chunk", limited)

    async def run(job):
        db_session.add(job)
        await db_session.commit()
        await jobs_mod.process_portfolio_job(job.id, "tok")
        await db_session.refresh(job)
        return job

    j1 = await run(PortfolioJob(user_id=SINGLE_USER_ID, kind="ter_refresh", request_key="a", status="running", attempts=1, worker_token="tok", created_at=NOW))
    assert j1.status == "done" and j1.result["remaining"] == 2 and "matching" not in j1.result
    nxt = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "ter_refresh", PortfolioJob.status == "queued"))).scalar_one()
    assert [a["mf_id"] for a in nxt.params["amcs"]] == [22, 3]
    nxt.status, nxt.worker_token = "running", "tok"
    await db_session.commit()
    await jobs_mod.process_portfolio_job(nxt.id, "tok")
    await db_session.refresh(nxt)
    assert nxt.status == "done" and nxt.result["remaining"] == 1
    last = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "ter_refresh", PortfolioJob.status == "queued"))).scalar_one()
    last.status, last.worker_token = "running", "tok"
    await db_session.commit()
    await jobs_mod.process_portfolio_job(last.id, "tok")
    await db_session.refresh(last)
    assert last.result["remaining"] == 0 and last.result["matching"]["mutual_funds_matched"] == 4 and last.result["done_total"] == 3


async def test_due_logic_and_the_weekly_scheduler_hook(db_session):
    from app.portfolio_intelligence import scheduler
    from tests.test_living import setup_user

    await setup_user(db_session)
    assert await tj.is_due(db_session, NOW) is True                                                       # never fetched
    await scheduler._maybe_ter(db_session)
    await scheduler._maybe_ter(db_session)
    assert (await db_session.execute(select(func.count()).select_from(PortfolioJob).where(PortfolioJob.kind == "ter_refresh"))).scalar_one() == 1     # once, not per tick
    db_session.add(SchemeTer(nsdl_code="X", mf_id=1, amc_name="a", scheme_name="s", ter_date=date(2026, 9, 30), fetched_at=datetime.now(timezone.utc)))
    await db_session.commit()
    assert await tj.is_due(db_session, datetime.now(timezone.utc)) is False


async def test_the_api_shows_the_expense_ratio_only_where_matched_and_can_sort_by_it(client, db_session):
    funds, etf = await seed_funds(db_session)
    for key, ter in (("UTI Nifty 50 Index Fund|direct", D("0.20")), ("Axis Nifty 50 Index Fund|direct", D("0.12"))):
        f = funds[key]
        db_session.add(SecurityTer(security_id=f.id, nsdl_code="N", scheme_name=f.name, ter=ter, plan_used="direct", matched_via="name_in_fund_house", ter_date=date(2026, 9, 30), matched_at=NOW))
    await db_session.commit()
    r = (await client.get("/api/v4/catalogue/securities", params={"kind": "mutual_fund", "plan": "direct", "sort": "ter", "order": "asc", "include_inactive": True})).json()["items"]
    assert [i["name"] for i in r[:2]] == ["Axis Nifty 50 Index Fund", "UTI Nifty 50 Index Fund"] and r[0]["ter"]["percent"] == "0.12" and r[0]["ter"]["source"] == "AMFI total expense ratio"
    assert all("ter" not in i for i in r[2:])                                                              # unmatched: the field is absent, not zero, and sorts last
    d = (await client.get(f"/api/v4/catalogue/securities/{funds['UTI Nifty 50 Index Fund|direct'].id}")).json()
    assert d["ter"]["percent"] == "0.2" and d["ter"]["plan"] == "direct"
    stk = (await client.get("/api/v4/catalogue/securities", params={"kind": "etf"})).json()["items"]
    assert all("ter" not in i for i in stk)
    st = (await client.get("/api/v4/catalogue/ter/status")).json()
    assert st["matched"] == {"mutual_fund": 2} and st["active_total"] == {"mutual_fund": 6, "etf": 1} and "UNKNOWN" in st["note"]
    from tests.test_living import setup_user

    await setup_user(db_session)
    assert (await client.post("/api/v4/catalogue/ter/refresh")).json() == {"queued": True, "already_queued": False}
