"""Phase 08: events, inbox lifecycle, scheduler, retries, auth-expiry recovery."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.models.living import InboxIssue, PortfolioEvent, SchedulerRun
from app.models.portfolio_jobs import PortfolioJob
from app.models.system import RecommendationJob
from app.models.user import User
from app.portfolio_intelligence import jobs as jobs_mod
from app.portfolio_intelligence import scheduler
from app.portfolio_intelligence.decisions import inbox as inbox_mod
from app.portfolio_intelligence.events import record_event
from app.portfolio_intelligence.sources.angel import client as client_mod
from app.portfolio_intelligence.sources.angel.errors import AuthExpired, RateLimited
from app.portfolio_intelligence.sources.angel.identity import fingerprint
from app.utils.time import utcnow
from tests.angel_fixtures import RELIANCE_ISIN, holdings_payload, ok, transport
from tests.test_decisions import acct, complete_setup, current, dep, eq, imp, run_reviews, seed  # noqa: F401

D = Decimal
WED_CLOSE = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)   # 17:30 IST Wednesday
WED_MORNING = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
SATURDAY = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def naive(dt):
    """SQLite hands back naive datetimes; compare wall-clock values only."""
    return dt.replace(tzinfo=None)


def outcome(issues, version=1):
    return SimpleNamespace(id=uuid.uuid4(), state_version=version, result={"issues": issues})


def it(fp="issuer_concentration:RELIANCE", sev="review", measure="0.40", title="RELIANCE is large"):
    return {"fingerprint": fp, "kind": fp.split(":")[0], "severity": sev, "title": title, "detail": f"weight {measure}", "measure": measure}


async def rows(db):
    return (await db.execute(select(InboxIssue))).scalars().all()


async def setup_user(db):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db.commit()


# --- inbox lifecycle ------------------------------------------------------------------------------

async def test_same_issue_across_reviews_is_one_row(db_session):
    await setup_user(db_session)
    t0 = utcnow()
    for i in range(4):  # repeated reviews / quote churn never multiply items
        await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(measure=f"0.4{i}")]), t0 + timedelta(minutes=i))
        await db_session.commit()
    r = await rows(db_session)
    assert len(r) == 1 and r[0].status == "open" and naive(r[0].first_seen_at) == naive(t0) and naive(r[0].last_seen_at) > naive(t0) and Decimal(r[0].measure) == D("0.43")


async def test_resolved_when_gone_and_reopened_when_it_returns(db_session):
    await setup_user(db_session)
    now = utcnow()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it()]), now)
    stats = await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([]), now)
    assert stats["resolved"] == 1
    assert (await rows(db_session))[0].status == "resolved"
    stats = await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it()]), now)
    r = (await rows(db_session))[0]
    assert stats["reopened"] == 1 and r.status == "open" and r.reopen_count == 1


async def test_dismissal_is_remembered_and_only_material_change_reopens(db_session):
    await setup_user(db_session)
    now = utcnow()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(measure="0.40")]), now)
    row = (await rows(db_session))[0]
    with pytest.raises(inbox_mod.InboxError):
        inbox_mod.dismiss(row, "  ", now)  # a reason is required
    inbox_mod.dismiss(row, "I am keeping this on purpose", now)
    await db_session.commit()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(measure="0.42")]), now)  # +2pp: not material
    assert (await rows(db_session))[0].status == "dismissed"
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([]), now)  # condition goes away: dismissal is NOT auto-resolved
    assert (await rows(db_session))[0].status == "dismissed"
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(measure="0.44")]), now)  # comes back, still not material
    assert (await rows(db_session))[0].status == "dismissed" and (await rows(db_session))[0].dismissed_reason == "I am keeping this on purpose"
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(measure="0.47")]), now)  # +7pp vs when dismissed
    r = (await rows(db_session))[0]
    assert r.status == "open" and r.reopen_count == 1


async def test_severity_escalation_reopens_a_dismissed_issue(db_session):
    await setup_user(db_session)
    now = utcnow()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(fp="reserve_shortfall", sev="information", measure=None)]), now)
    inbox_mod.dismiss((await rows(db_session))[0], "known", now)
    await db_session.commit()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(fp="reserve_shortfall", sev="urgent", measure=None)]), now)
    assert (await rows(db_session))[0].status == "open"


async def test_snooze_returns_after_its_date(db_session):
    await setup_user(db_session)
    now = utcnow()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it()]), now)
    row = (await rows(db_session))[0]
    with pytest.raises(inbox_mod.InboxError):
        inbox_mod.snooze(row, now.date(), now.date())
    inbox_mod.snooze(row, now.date() + timedelta(days=3), now.date())
    await db_session.commit()
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it()]), now)
    assert (await rows(db_session))[0].status == "snoozed"
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it()]), now + timedelta(days=4))
    assert (await rows(db_session))[0].status == "open"


async def test_inbox_api_versions_and_counts(client, db_session):
    await setup_user(db_session)
    await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, outcome([it(), it(fp="goal_needs_revision:g1", sev="urgent", measure=None, title="Goal")]), utcnow())
    await db_session.commit()
    inbox = (await client.get("/api/v4/inbox")).json()
    assert [i["category"] for i in inbox["items"]] == ["urgent", "review"] and inbox["counts"]["open"] == 2  # most severe first
    item = inbox["items"][1]
    assert (await client.post(f"/api/v4/inbox/{item['id']}/dismiss", json={"expected_version": 99, "reason": "x"})).status_code == 409
    assert (await client.post(f"/api/v4/inbox/{item['id']}/dismiss", json={"expected_version": item["version"], "reason": ""})).status_code == 422
    d = (await client.post(f"/api/v4/inbox/{item['id']}/dismiss", json={"expected_version": item["version"], "reason": "intentional"})).json()
    assert d["status"] == "dismissed"
    assert (await client.get("/api/v4/inbox")).json()["counts"] == {"open": 1, "snoozed": 0, "dismissed": 1, "resolved": 0}
    assert len((await client.get("/api/v4/inbox?status=dismissed")).json()["items"]) == 1
    past = (date.today() - timedelta(days=1)).isoformat()
    assert (await client.post(f"/api/v4/inbox/{d['id']}/snooze", json={"expected_version": d["version"], "until": past})).status_code == 422
    re = await client.post(f"/api/v4/inbox/{d['id']}/reopen", json={"expected_version": d["version"]})
    assert re.status_code == 200 and re.json()["status"] == "open"
    assert (await client.post(f"/api/v4/inbox/{uuid.uuid4()}/dismiss", json={"expected_version": 1, "reason": "x"})).status_code == 404


# --- events ------------------------------------------------------------------------------------------

async def test_duplicate_events_coalesce(db_session):
    await setup_user(db_session)
    assert await record_event(db_session, SINGLE_USER_ID, "valuation_published", dedup_key="valuation:abc") is True
    assert await record_event(db_session, SINGLE_USER_ID, "valuation_published", dedup_key="valuation:abc") is False
    assert (await db_session.execute(select(func.count()).select_from(PortfolioEvent))).scalar_one() == 1


async def test_price_only_change_makes_no_inbox_noise_and_no_new_review(client, db_session, run_reviews):
    a, b = await complete_setup(client, db_session)
    await run_reviews()
    inbox_before = (await client.get("/api/v4/inbox?status=all")).json()["counts"]
    await imp(client, a, [eq("INE002A01018", "16000"), eq("INE467B01029", "14000")])  # same holdings, prices moved
    jobs = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "review", PortfolioJob.status == "queued"))).scalars().all()
    assert jobs == []  # a valuation-only change does not queue a review by itself
    assert (await client.get("/api/v4/inbox?status=all")).json()["counts"] == inbox_before
    kinds = {e["kind"] for e in (await client.get("/api/v4/events")).json()}
    assert "valuation_published" in kinds and "state_built" in kinds


async def test_nothing_material_changed_is_reported(client, db_session, run_reviews):
    a, b = await complete_setup(client, db_session)
    await run_reviews()
    await client.post("/api/v4/reviews", json={"force": True})
    await run_reviews()
    c = await current(client)
    assert c["since_previous"]["nothing_material_changed"] is True and c["since_previous"]["new_issues"] == []


# --- scheduler ---------------------------------------------------------------------------------------

async def angel_account(db, code="A123456"):
    settings.angel_fingerprint_key = "k"
    a = SourceAccount(user_id=SINGLE_USER_ID, source_type="angel_one", label="Angel", masked_external_id="A***56",
                      external_fingerprint=fingerprint(code), included=True, status="active", version=1, created_at=utcnow())
    db.add(a)
    await db.commit()
    return a


async def test_scheduler_skips_weekend_and_before_close_and_runs_once_a_day(db_session, monkeypatch):
    await setup_user(db_session)
    assert (await scheduler.tick(db_session, SATURDAY))["reason"] == "weekend"
    assert "before the final close" in (await scheduler.tick(db_session, WED_MORNING))["reason"]
    first = await scheduler.tick(db_session, WED_CLOSE)
    assert first["ran"] is True
    assert (await scheduler.tick(db_session, WED_CLOSE + timedelta(minutes=10)))["reason"] == "already ran today"
    assert (await db_session.execute(select(func.count()).select_from(SchedulerRun))).scalar_one() == 1
    nxt = await scheduler.tick(db_session, WED_CLOSE + timedelta(days=1))
    assert nxt["ran"] is True  # a new day runs again


async def test_scheduler_queues_syncs_only_with_a_valid_session_and_never_the_legacy_pipeline(db_session, monkeypatch):
    await setup_user(db_session)
    a = await angel_account(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())
    r = await scheduler.tick(db_session, WED_CLOSE)
    assert r["ran"] and r["queued_syncs"] == [str(a.id)] and r["session_valid"] is True
    kinds = {j.kind for j in (await db_session.execute(select(PortfolioJob))).scalars()}
    assert kinds == {"account_sync", "review", "catalogue_refresh", "market_snapshot", "candle_backfill"}  # the close pass also queues the worker-only catalogue/market jobs
    assert (await db_session.execute(select(func.count()).select_from(RecommendationJob))).scalar_one() == 0  # no 1,100-line Nifty run


async def test_expired_session_at_close_flags_reconnect_and_keeps_last_state(db_session, monkeypatch):
    await setup_user(db_session)
    a = await angel_account(db_session)
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: None)
    r = await scheduler.tick(db_session, WED_CLOSE)
    assert r["session_valid"] is False and r["expired"] == [str(a.id)] and r["queued_syncs"] == []
    await db_session.refresh(a)
    assert a.status == "reconnect_required" and "reconnect" in a.last_error
    syncs = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "account_sync"))).scalars().all()
    assert syncs == []  # no pointless call with a dead session


# --- bounded retries and recovery ----------------------------------------------------------------------

@pytest.fixture
def jobs_env(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.AsyncSessionLocal", factory)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "angel_fingerprint_key", "k")
    monkeypatch.setattr(client_mod, "MIN_INTERVAL_SECONDS", 0.0)
    return factory


async def queue_sync(db, acct_id, key="k1"):
    j = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=acct_id, request_key=key, status="queued", attempts=0, created_at=utcnow())
    db.add(j)
    await db.commit()
    return j


async def run_one(db, kinds=("account_sync",)):
    job = await jobs_mod.claim_next_portfolio_job(db, kinds=kinds)
    if job is None:
        return None
    await jobs_mod.process_portfolio_job(job.id, job.worker_token)
    await db.refresh(job)
    return job


def good_fetch(rows=None):
    from app.portfolio_intelligence.sources.angel.client import AngelClient
    routes = {"getProfile": ok({"clientcode": "A123456"}), "getAllHolding": holdings_payload(rows), "getPosition": ok([]), "getRMS": ok({"net": "1"})}
    return AngelClient(api_key="k", jwt="j", transport=transport(routes))


async def test_rate_limit_retries_with_backoff_then_gives_up_and_keeps_last_good(client, db_session, jobs_env, monkeypatch):
    await setup_user(db_session)
    a = await angel_account(db_session)
    real_fetch = jobs_mod.fetch_account_snapshot
    # 1) a good sync
    async def good(account, c=None):
        return await real_fetch(account, good_fetch())
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", good)
    await queue_sync(db_session, a.id, "good")
    j = await run_one(db_session)
    assert j.status == "done"
    assert len((await client.get(f"/api/v4/accounts/{a.id}/positions")).json()["positions"]) == 1

    # 2) the broker rate-limits: bounded retries with exponential backoff
    async def limited(account, c=None):
        raise RateLimited("broker rate limit")
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", limited)
    job = await queue_sync(db_session, a.id, "limited")
    j1 = await run_one(db_session)
    assert j1.status == "queued" and j1.attempts == 1 and j1.error_code == "RATE_LIMITED" and naive(j1.not_before) > naive(utcnow())
    assert await jobs_mod.claim_next_portfolio_job(db_session, kinds=("account_sync",)) is None  # not claimable during backoff
    j1.not_before = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    j2 = await run_one(db_session)
    assert j2.status == "queued" and j2.attempts == 2
    j2.not_before = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    j3 = await run_one(db_session)
    assert j3.status == "failed" and j3.attempts == 3  # bounded: three tries, then a terminal failure
    await db_session.refresh(a)
    assert a.last_error.startswith("RATE_LIMITED")
    # last good state survives every failure
    assert len((await client.get(f"/api/v4/accounts/{a.id}/positions")).json()["positions"]) == 1
    assert (await client.get("/api/v4/state/current")).json()["state"] is not None


async def test_auth_expiry_is_not_retried_and_recovery_clears_the_issue(client, db_session, jobs_env, monkeypatch, run_reviews):
    await setup_user(db_session)
    a = await angel_account(db_session)
    real_fetch = jobs_mod.fetch_account_snapshot

    async def good(account, c=None):
        return await real_fetch(account, good_fetch())
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", good)
    await queue_sync(db_session, a.id, "g1")
    assert (await run_one(db_session)).status == "done"

    async def expired(account, c=None):
        raise AuthExpired("broker session invalid or expired")
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", expired)
    await queue_sync(db_session, a.id, "g2")
    j = await run_one(db_session)
    assert j.status == "failed" and j.error_code == "AUTH_EXPIRED" and j.attempts == 1  # never retried
    await db_session.refresh(a)
    assert a.status == "reconnect_required"
    kinds = {e["kind"] for e in (await client.get("/api/v4/events")).json()}
    assert "auth_expired" in kinds
    await run_one(db_session, kinds=("review",))  # the review queued by the failure
    c = await current(client)
    assert c["outcome"]["status"] == "NEEDS_INPUT" and "reconnect" in c["outcome"]["headline"].lower()
    items = (await client.get("/api/v4/inbox")).json()["items"]
    assert any(i["kind"] == "reconnect_required" for i in items)
    assert len((await client.get(f"/api/v4/accounts/{a.id}/positions")).json()["positions"]) == 1  # dated state still there

    # the owner reconnects: the next successful sync clears the account state and the inbox item
    monkeypatch.setattr(jobs_mod, "fetch_account_snapshot", good)
    await queue_sync(db_session, a.id, "g3")
    assert (await run_one(db_session)).status == "done"
    await run_one(db_session, kinds=("review",))
    await db_session.refresh(a)
    assert a.status == "active"
    c2 = await current(client)
    assert not any(i["kind"] == "reconnect_required" for i in c2["outcome"]["result"]["issues"])
    resolved = (await client.get("/api/v4/inbox?status=resolved")).json()["items"]
    assert any(i["kind"] == "reconnect_required" for i in resolved)


async def test_outcomes_without_fingerprints_from_before_this_phase_still_work(client, db_session):
    """A real database already holds Phase 07 outcomes whose issues have no fingerprint."""
    from app.models.decisions import CurrentDecision, DecisionOutcome
    from app.models.twin import PortfolioState, ValuationSnapshot

    await seed(db_session)
    a = await acct(client, "A")
    await imp(client, a, [dep("1000")])
    cur = (await client.get("/api/v4/state/current")).json()
    now = utcnow()
    old = DecisionOutcome(user_id=SINGLE_USER_ID, state_id=uuid.UUID(cur["state"]["id"]), state_version=cur["state"]["version"],
                          valuation_id=uuid.UUID(cur["valuation"]["id"]), policy_version="decision-p0-unreviewed|review-v2", status="NEEDS_INPUT",
                          headline="old", result={"issues": [{"kind": "profile_incomplete", "severity": "review", "title": "t", "detail": "d"}],
                                                  "valid": {"review_by": (now + timedelta(days=7)).isoformat()}}, created_at=now)
    db_session.add(old)
    await db_session.flush()
    db_session.add(CurrentDecision(user_id=SINGLE_USER_ID, outcome_id=old.id, updated_at=now))
    await db_session.commit()
    r = await client.get("/api/v4/actions/current")
    assert r.status_code == 200 and r.json()["outcome"]["headline"] == "old"
    stats = await inbox_mod.sync_inbox(db_session, SINGLE_USER_ID, old, now)
    assert stats["created"] == 1
