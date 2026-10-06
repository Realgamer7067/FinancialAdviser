"""Sync pipeline, typed jobs, fencing and the connection API (SQLite-backed)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import PositionObservation, SourceAccount, SourceImport
from app.models.market import Instrument
from app.models.portfolio_jobs import PortfolioJob
from app.models.user import User
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence import jobs as jobs_mod
from app.portfolio_intelligence.sources.angel import client as client_mod
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AuthExpired, IdentityConflict
from app.portfolio_intelligence.sources.angel.identity import fingerprint
from app.portfolio_intelligence.sources.angel.sync import fetch_account_snapshot, publish_sync_result
from app.utils.time import utcnow
from tests.angel_fixtures import RELIANCE_ISIN, holding, holdings_payload, ok, transport

CODE = "A123456"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "angel_fingerprint_key", "test-key")
    monkeypatch.setattr(client_mod, "MIN_INTERVAL_SECONDS", 0.0)


async def _seed(db, code=CODE):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    db.add(Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=RELIANCE_ISIN))
    acct = SourceAccount(user_id=SINGLE_USER_ID, source_type="angel_one", label="Angel", masked_external_id="A***56",
                         external_fingerprint=fingerprint(code), included=True, status="active", version=1, created_at=utcnow())
    db.add(acct)
    await db.commit()
    return acct


def routes(holdings=None, code=CODE):
    return {
        "getProfile": ok({"clientcode": code, "name": "X"}),
        "getAllHolding": holdings if holdings is not None else holdings_payload(),
        "getPosition": ok([]),
        "getRMS": ok({"net": "100.0", "availablecash": "50.0"}),
    }


def client_for(r):
    return AngelClient(api_key="k", jwt="jwt", transport=transport(r))


async def _run_sync(db, acct, r, token="tok"):
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct.id, request_key=str(uuid.uuid4()),
                       status="running", attempts=1, worker_token=token, created_at=utcnow(), started_at=utcnow())
    db.add(job)
    await db.commit()
    parsed, summary = await fetch_account_snapshot(acct, client_for(r))
    imp = await publish_sync_result(db, job.id, token, acct.id, parsed, summary)
    return job, imp


async def _current(client, acct):
    return (await client.get(f"/api/v4/accounts/{acct.id}/positions")).json()["positions"]


async def test_complete_sync_becomes_current_and_keeps_provider_fields(client, db_session):
    acct = await _seed(db_session)
    job, imp = await _run_sync(db_session, acct, routes())
    assert imp.status == "complete" and imp.reconciliation["material_gap"] is False
    await db_session.refresh(job)
    assert job.status == "done" and job.result_import_id == imp.id
    pos = await _current(client, acct)
    assert len(pos) == 1 and pos[0]["resolution"] == "resolved" and pos[0]["cost_basis"] is None
    assert imp.provider_summary["open_positions"]["supported"] is False  # separate coverage bucket
    assert "rms_note" in imp.provider_summary


async def test_valid_empty_replaces_and_broken_preserves(client, db_session):
    acct = await _seed(db_session)
    await _run_sync(db_session, acct, routes())
    assert len(await _current(client, acct)) == 1
    # broken response (holdings missing) => failure, last good import kept
    with pytest.raises(Exception):
        await fetch_account_snapshot(acct, client_for(routes({"status": True, "data": {"totalholding": {}}})))
    assert len(await _current(client, acct)) == 1
    # valid empty => a real zero-holdings import (position was sold)
    await _run_sync(db_session, acct, routes(holdings_payload(rows=[], total=0)))
    assert await _current(client, acct) == []


async def test_partial_sync_never_replaces_last_complete(client, db_session):
    acct = await _seed(db_session)
    await _run_sync(db_session, acct, routes())
    bad = holdings_payload([holding(), holding(quantity=-1, tradingsymbol="BAD")])
    job, imp = await _run_sync(db_session, acct, routes(bad))
    assert imp.status == "partial"
    await db_session.refresh(job)
    await db_session.refresh(acct)
    assert job.status == "failed" and job.error_code == "PARTIAL_DATA" and "PARTIAL_DATA" in acct.last_error
    assert len(await _current(client, acct)) == 1  # still the earlier complete import
    n = (await db_session.execute(select(func.count()).select_from(SourceImport))).scalar_one()
    assert n == 2  # partial stored for review


async def test_identity_mismatch_rejected(db_session):
    acct = await _seed(db_session)
    with pytest.raises(IdentityConflict):
        await fetch_account_snapshot(acct, client_for(routes(code="Z999999")))


async def test_stale_token_cannot_publish(db_session):
    acct = await _seed(db_session)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct.id, request_key="k",
                       status="running", attempts=2, worker_token="new-attempt", created_at=utcnow())
    db_session.add(job)
    await db_session.commit()
    parsed, summary = await fetch_account_snapshot(acct, client_for(routes()))
    with pytest.raises(StalePublicationError):
        await publish_sync_result(db_session, job.id, "old-attempt", acct.id, parsed, summary)
    assert (await db_session.execute(select(func.count()).select_from(SourceImport))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(PositionObservation))).scalar_one() == 0


async def test_claim_reclaims_expired_lease_with_new_token(db_session):
    acct = await _seed(db_session)
    db_session.add(PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct.id, request_key="k",
                                status="queued", attempts=0, created_at=utcnow()))
    await db_session.commit()
    first = await jobs_mod.claim_next_portfolio_job(db_session)
    assert first is not None and first.status == "running"
    t1 = first.worker_token
    assert await jobs_mod.claim_next_portfolio_job(db_session) is None  # lease still valid
    first.lease_expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    second = await jobs_mod.claim_next_portfolio_job(db_session)
    assert second is not None and second.worker_token != t1 and second.attempts == 2


async def test_auth_expiry_marks_reconnect_and_stale_failure_dropped(db_session, test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    acct = await _seed(db_session)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct.id, request_key="k",
                       status="running", attempts=1, worker_token="tok", created_at=utcnow())
    db_session.add(job)
    await db_session.commit()

    async def expired(account, client=None):
        raise AuthExpired("broker session invalid or expired")
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", expired)

    await jobs_mod.process_portfolio_job(job.id, "stale-token")  # superseded attempt: must not write
    await db_session.refresh(job)
    assert job.status == "running"
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    await db_session.refresh(acct)
    assert job.status == "failed" and job.error_code == "AUTH_EXPIRED"
    assert acct.status == "reconnect_required"


# --- API ---------------------------------------------------------------

async def test_status_and_sync_endpoints(client, db_session, monkeypatch):
    from app.api.v4 import connections
    from app.portfolio_intelligence.sources.angel.token_store import Session

    acct = await _seed(db_session)
    st = (await client.get("/api/v4/connections/angel/status")).json()
    assert st["session"] == "reconnect_required" and st["accounts"][0]["masked_external_id"] == "A***56"
    assert "jwt" not in str(st).lower() and "fingerprint" not in st["accounts"][0]

    r = await client.post(f"/api/v4/accounts/{acct.id}/sync", json={"idempotency_key": "s1"})
    assert r.status_code == 409 and "reconnect_required" in str(r.json())

    now = utcnow()
    monkeypatch.setattr(connections, "load_session", lambda: Session("j", "r", "f", now + timedelta(hours=1), now))
    a = await client.post(f"/api/v4/accounts/{acct.id}/sync", json={"idempotency_key": "s1"})
    assert a.status_code == 202 and a.json()["status"] == "queued"
    same = await client.post(f"/api/v4/accounts/{acct.id}/sync", json={"idempotency_key": "s1"})
    other_key = await client.post(f"/api/v4/accounts/{acct.id}/sync", json={"idempotency_key": "s2"})
    assert same.json()["id"] == a.json()["id"] == other_key.json()["id"]  # coalesced onto the active job
    assert (await client.get(f"/api/v4/jobs/{a.json()['id']}")).json()["status"] == "queued"
    assert (await client.get(f"/api/v4/jobs/{uuid.uuid4()}")).status_code == 404


async def test_manual_account_cannot_sync_and_broker_cannot_manual_import(client, db_session):
    acct = await _seed(db_session)
    m = (await client.post("/api/v4/accounts", json={"label": "Manual"})).json()
    assert (await client.post(f"/api/v4/accounts/{m['id']}/sync", json={"idempotency_key": "x"})).status_code == 422
    r = await client.post("/api/v4/imports/manual/confirm", json={
        "account_id": str(acct.id), "idempotency_key": "k",
        "rows": [{"asset_type": "gold", "description": "c", "value": "1", "valuation_date": "2026-09-01"}]})
    assert r.status_code == 422


async def test_fence_compares_locked_row_not_stale_identity_map(test_engine, db_session):
    """Session A loaded the job (token t1) before its network fetch; another
    attempt then reclaimed it (token t2). A's publish must be refused even
    though A's identity map still says t1."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    acct = await _seed(db_session)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct.id, request_key="k",
                       status="running", attempts=1, worker_token="t1", created_at=utcnow())
    db_session.add(job)
    await db_session.commit()
    parsed, summary = await fetch_account_snapshot(acct, client_for(routes()))

    async with factory() as a, factory() as b:
        loaded = await a.get(PortfolioJob, job.id)  # A's stale view
        assert loaded.worker_token == "t1"
        reclaimed = await b.get(PortfolioJob, job.id)
        reclaimed.worker_token = "t2"
        await b.commit()
        with pytest.raises(StalePublicationError):
            await publish_sync_result(a, job.id, "t1", acct.id, parsed, summary)
    assert (await db_session.execute(select(func.count()).select_from(SourceImport))).scalar_one() == 0


async def test_funds_endpoint_reports_what_angel_showed_at_the_last_sync_and_says_what_it_cannot_know(client, db_session, monkeypatch):
    from app.api.v4 import connections
    from app.models.accounts import SourceImport
    from app.portfolio_intelligence.sources.angel.token_store import Session

    # no account at all
    none = (await client.get("/api/v4/connections/angel/funds")).json()
    assert none["available"] is None and none["stale"] is True and "No Angel account" in none["note"]

    acct = await _seed(db_session)
    unread = (await client.get("/api/v4/connections/angel/funds")).json()
    assert unread["available"] is None and "press Sync now" in unread["note"]

    now = utcnow()
    db_session.add(SourceImport(account_id=acct.id, idempotency_key="f1", content_hash="h", schema_version="s", status="complete", row_count=0, created_at=now,
                                provider_summary={"retrieved_at": now.isoformat(), "rms_raw": {"net": "250.0000", "availablecash": "250.0000", "utilisedpayout": "0"}}))
    await db_session.commit()
    monkeypatch.setattr(connections, "load_session", lambda: Session("j", "r", "f", now + timedelta(hours=1), now))
    f = (await client.get("/api/v4/connections/angel/funds")).json()
    assert f["available"] == "250" and f["fields"]["net"] == "250.0000" and f["stale"] is False and f["account_label"]
    assert "cannot see your orders" in f["note"] and "Pending orders" in f["note"]

    # a failed or malformed report is "unknown", never zero
    db_session.add(SourceImport(account_id=acct.id, idempotency_key="f2", content_hash="h2", schema_version="s", status="complete", row_count=0, created_at=now + timedelta(minutes=1),
                                provider_summary={"retrieved_at": now.isoformat(), "rms_raw": {"fetched": False, "code": "UNAVAILABLE"}}))
    await db_session.commit()
    bad = (await client.get("/api/v4/connections/angel/funds")).json()
    assert bad["available"] is None
