"""Job claiming/lease/fencing (docs/V2-RETHINK.md P0: job claiming was a
SELECT then UPDATE with no locking and no lease recovery -- extra workers
could double-process a job, and a crashed worker left a job stuck "running"
forever)."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.worker as worker_module
from app.core.config import settings
from app.models.system import RecommendationJob
from app.models.user import User
from app.utils.time import utcnow


async def _make_user(db_session):
    user = User(email="worker-test@example.com", hashed_password="unused", full_name="Worker Test")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _patch_worker_session_factory(monkeypatch, session_factory):
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", session_factory)


async def test_claim_marks_running_and_sets_fencing_token(db_session):
    user = await _make_user(db_session)
    job = RecommendationJob(user_id=user.id, status="queued")
    db_session.add(job)
    await db_session.commit()

    claimed = await worker_module._claim_next_job(db_session)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_token is not None
    assert claimed.lease_expires_at is not None


async def test_running_job_with_live_lease_is_not_reclaimed(db_session):
    user = await _make_user(db_session)
    job = RecommendationJob(
        user_id=user.id,
        status="running",
        worker_token="original-token",
        lease_expires_at=utcnow() + timedelta(seconds=settings.job_lease_seconds),
    )
    db_session.add(job)
    await db_session.commit()

    claimed = await worker_module._claim_next_job(db_session)

    assert claimed is None  # still leased -- another worker must not double-process it


async def test_running_job_with_expired_lease_is_reclaimed(db_session):
    user = await _make_user(db_session)
    job = RecommendationJob(
        user_id=user.id,
        status="running",
        worker_token="dead-workers-token",
        lease_expires_at=utcnow() - timedelta(seconds=1),  # expired -- worker presumed dead
    )
    db_session.add(job)
    await db_session.commit()
    original_token = job.worker_token

    claimed = await worker_module._claim_next_job(db_session)

    assert claimed is not None
    assert claimed.worker_token != original_token  # a fresh attempt gets a fresh token


async def test_stale_attempts_completion_write_is_dropped(db_session, session_factory):
    user = await _make_user(db_session)
    job = RecommendationJob(user_id=user.id, status="queued")
    db_session.add(job)
    await db_session.commit()
    job_id = job.id

    # Simulate: attempt A claims, then its lease expires and attempt B
    # reclaims before A's (delayed) completion write finally lands.
    stale_token = "attempt-a-stale-token"
    job.worker_token = stale_token
    await db_session.commit()

    async with session_factory() as db2:
        reclaimed = await db2.get(RecommendationJob, job_id)
        reclaimed.worker_token = "attempt-b-fresh-token"
        reclaimed.status = "running"
        await db2.commit()

    # Attempt A's stale completion write must be dropped, not overwrite B's claim.
    await worker_module._mark_done(job_id, stale_token, council_run_id=None)

    async with session_factory() as db3:
        final = await db3.get(RecommendationJob, job_id)
        assert final.status == "running"  # NOT clobbered back to "done" by the stale attempt
        assert final.worker_token == "attempt-b-fresh-token"


async def test_current_attempts_completion_write_succeeds(db_session, session_factory):
    user = await _make_user(db_session)
    job = RecommendationJob(user_id=user.id, status="running", worker_token="current-token")
    db_session.add(job)
    await db_session.commit()
    job_id = job.id

    await worker_module._mark_done(job_id, "current-token", council_run_id=None)

    async with session_factory() as db2:
        final = await db2.get(RecommendationJob, job_id)
        assert final.status == "done"
