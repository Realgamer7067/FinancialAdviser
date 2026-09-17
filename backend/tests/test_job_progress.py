"""Unit coverage for JobProgressTracker's percentage math and no-op path,
isolated from the full pipeline (see test_pipeline_smoke.py for the
end-to-end wiring check)."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.system import RecommendationJob
from app.pipelines.progress import STAGE_BANDS, STAGE_COUNCIL_EVALUATION, STAGE_LOADING_PROFILE, JobProgressTracker


async def test_job_id_none_is_a_no_op(db_session):
    tracker = JobProgressTracker(None, session_factory=lambda: db_session)
    await tracker.set_stage(STAGE_LOADING_PROFILE)  # must not raise, must not touch the DB


async def test_set_stage_writes_band_start_without_index(db_session, test_engine):
    job = RecommendationJob(user_id=SINGLE_USER_ID, status="running", created_at=datetime.now(timezone.utc))
    db_session.add(job)
    await db_session.commit()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    tracker = JobProgressTracker(job.id, session_factory=session_factory)
    await tracker.set_stage(STAGE_LOADING_PROFILE)

    refreshed = (await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job.id))).scalar_one()
    start, _ = STAGE_BANDS[STAGE_LOADING_PROFILE]
    assert refreshed.stage == STAGE_LOADING_PROFILE
    assert refreshed.progress_pct == start
    assert refreshed.stage_detail == {"current_symbol": None, "index": None, "total": None}


async def test_set_stage_interpolates_within_band(db_session, test_engine):
    job = RecommendationJob(user_id=SINGLE_USER_ID, status="running", created_at=datetime.now(timezone.utc))
    db_session.add(job)
    await db_session.commit()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    tracker = JobProgressTracker(job.id, session_factory=session_factory)
    await tracker.set_stage(STAGE_COUNCIL_EVALUATION, current_symbol="TCS", index=1, total=4)

    refreshed = (await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job.id))).scalar_one()
    start, end = STAGE_BANDS[STAGE_COUNCIL_EVALUATION]
    expected = round(start + (end - start) * (1 / 4), 1)
    assert refreshed.progress_pct == expected
    assert refreshed.stage_detail == {"current_symbol": "TCS", "index": 1, "total": 4}


async def test_set_stage_missing_job_is_a_no_op(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    tracker = JobProgressTracker(uuid4(), session_factory=session_factory)
    await tracker.set_stage(STAGE_LOADING_PROFILE)  # job doesn't exist -- must not raise
