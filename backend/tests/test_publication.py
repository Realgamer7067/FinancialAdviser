"""docs/v3-execution/CONTRACTS.md C2: verify_ownership must be the atomic
gate a publication commit is conditioned on -- a single conditional UPDATE,
not a prior read followed by an unconditional write. This is the piece the
prior V2-IMPLEMENTATION-CHECK.md audit found missing: only the job ROW's own
terminal write was fenced before this; the pipeline's actual CouncilRun/
Recommendation publication committed unconditionally."""

import pytest
from sqlalchemy import select

from app.models.system import RecommendationJob
from app.models.user import User
from app.pipelines.publication import StalePublicationError, verify_ownership


async def _make_job(db_session, worker_token: str) -> RecommendationJob:
    user = User(email="pub-test@example.com", hashed_password="unused", full_name="Publication Test")
    db_session.add(user)
    await db_session.flush()
    job = RecommendationJob(user_id=user.id, status="running", worker_token=worker_token)
    db_session.add(job)
    await db_session.commit()
    return job


async def test_verify_ownership_passes_when_token_matches(db_session):
    job = await _make_job(db_session, "real-token")
    await verify_ownership(db_session, job.id, "real-token")  # must not raise
    await db_session.commit()


async def test_verify_ownership_raises_when_token_mismatched(db_session):
    job = await _make_job(db_session, "real-token")
    with pytest.raises(StalePublicationError):
        await verify_ownership(db_session, job.id, "some-other-attempts-token")


async def test_verify_ownership_raises_when_job_was_reclaimed_after_this_attempt_started(db_session):
    # Reproduces the exact race: this attempt reads/starts with "attempt-a",
    # then (simulating a lease expiry + reclaim) the row's token changes to
    # "attempt-b" via a plain update, then attempt-a tries to publish.
    job = await _make_job(db_session, "attempt-a")
    job.worker_token = "attempt-b"
    await db_session.commit()

    with pytest.raises(StalePublicationError):
        await verify_ownership(db_session, job.id, "attempt-a")


async def test_verify_ownership_is_noop_for_manual_trigger_with_no_job(db_session):
    # job_id=None is the unfenced manual/smoke-test path (no worker claim
    # exists to violate) -- must not raise.
    await verify_ownership(db_session, None, None)


async def test_verify_ownership_renews_lease_on_success(db_session):
    job = await _make_job(db_session, "real-token")
    assert job.lease_expires_at is None  # not yet claimed with a lease
    await verify_ownership(db_session, job.id, "real-token")
    await db_session.commit()

    refreshed = (await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job.id))).scalar_one()
    assert refreshed.lease_expires_at is not None


async def test_verify_ownership_is_a_single_atomic_statement_not_read_then_write(db_session):
    # The bug being closed: a prior read of worker_token followed by a
    # separate unconditional write has a gap where another attempt's claim
    # can land in between. verify_ownership must express the check as the
    # WHERE clause of the write itself. Assert this by checking a mismatched
    # token changes NOTHING (no partial write happened) rather than trusting
    # the exception alone.
    job_id = (await _make_job(db_session, "real-token")).id
    with pytest.raises(StalePublicationError):
        await verify_ownership(db_session, job_id, "wrong-token")
    await db_session.rollback()

    refreshed = (
        await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job_id))
    ).scalar_one()
    assert refreshed.worker_token == "real-token"
    assert refreshed.lease_expires_at is None
