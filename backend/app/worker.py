"""Background worker (Section 70). The API never runs the pipeline inline --
it enqueues a RecommendationJob row and this process polls for queued work.
Deliberately a plain asyncio loop, not Celery/Redis, per the "don't
overengineer" instruction (Section 64) -- one worker is enough for the MVP's
scale.

Claiming is atomic (`SELECT ... FOR UPDATE SKIP LOCKED`, docs/V2-RETHINK.md
P0) so two worker processes never grab the same job, and a job whose lease
expired (its worker died or hung) can be reclaimed by a fresh attempt rather
than staying stuck "running" forever. Every write back to the job (progress,
completion, failure) carries a `worker_token` and is only applied if that
token still matches the row -- a stale, recovered worker that eventually
wakes up must not clobber a newer attempt's result."""

import asyncio
import logging
import traceback
import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal, engine
from app.core.migration_barrier import assert_migration_head
from app.models.system import RecommendationJob
from app.pipelines.publication import StalePublicationError
from app.pipelines.recommendation_pipeline import PipelineError, run_recommendation_pipeline
from app.utils.time import utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
logger = logging.getLogger("worker")


async def _claim_next_job(db: AsyncSession) -> RecommendationJob | None:
    now = utcnow()
    lease_until = now + timedelta(seconds=settings.job_lease_seconds)

    result = await db.execute(
        select(RecommendationJob)
        .where(
            or_(
                RecommendationJob.status == "queued",
                # A "running" job whose lease has expired is abandoned --
                # its worker crashed or hung mid-run without ever completing
                # the heartbeat, so it's safe to reclaim (Section 50).
                (RecommendationJob.status == "running") & (RecommendationJob.lease_expires_at < now),
            )
        )
        .order_by(RecommendationJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.started_at = now
    job.worker_token = str(uuid.uuid4())
    job.lease_expires_at = lease_until
    await db.commit()
    return job


async def _mark_terminal(job_id, worker_token: str, *, status: str, error: str | None = None) -> None:
    """Runs in its own fresh session -- the session that ran the pipeline may
    be left in a failed/pending-rollback state by whatever raised, and trying
    to commit through it would itself raise (Section 50: a failed job must
    still be recorded, never silently disappear).

    Fenced on worker_token: if another attempt has since reclaimed this job
    (this attempt's lease expired and someone else took over), this write is
    stale and must be dropped rather than overwriting the newer attempt."""
    async with AsyncSessionLocal() as db:
        job = await db.get(RecommendationJob, job_id)
        if job is None or job.worker_token != worker_token:
            logger.warning("job %s: dropping stale %s write (reclaimed by another attempt)", job_id, status)
            return
        job.status = status
        job.error = error
        job.completed_at = utcnow()
        await db.commit()


async def _mark_done(job_id, worker_token: str, council_run_id) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(RecommendationJob, job_id)
        if job is None or job.worker_token != worker_token:
            logger.warning("job %s: dropping stale completion write (reclaimed by another attempt)", job_id)
            return
        job.status = "done"
        job.completed_at = utcnow()
        job.result_council_run_id = council_run_id
        await db.commit()


async def _process_job(job_id, worker_token: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(RecommendationJob, job_id)
        try:
            council_run = await run_recommendation_pipeline(
                db, job.user_id, job_id=job.id, worker_token=worker_token
            )
            await _mark_done(job_id, worker_token, council_run.id)
            logger.info("job %s done -> council_run %s", job_id, council_run.id)
            return
        except StalePublicationError:
            # This attempt was reclaimed by another worker before it could
            # publish (docs/v3-execution/CONTRACTS.md C2) -- everything this
            # attempt produced was rolled back, nothing became visible. This
            # is NOT a job failure; the attempt that actually owns the job
            # now is responsible for its outcome. Log and drop, do not
            # record "failed" over a newer attempt's in-progress/completed work.
            await db.rollback()
            logger.warning("job %s: attempt %s superseded before publication, dropping", job_id, worker_token)
            return
        except PipelineError as exc:
            error = str(exc)
            logger.warning("job %s failed: %s", job_id, exc)
        except Exception as exc:  # noqa: BLE001 -- must never crash the worker loop (Section 50)
            error = f"{exc}\n{traceback.format_exc()[-2000:]}"
            logger.exception("job %s crashed", job_id)
        await db.rollback()  # the session may be unusable after the failure above

    await _mark_terminal(job_id, worker_token, status="failed", error=error)


async def run_worker_loop() -> None:
    # Migration startup barrier (V3 Phase 11, instruction 2) -- same check as
    # the API's startup event (app/main.py), so a worker started against a
    # stale/ahead schema fails loudly here instead of claiming a job and
    # crashing confusingly mid-pipeline on a missing/renamed column.
    async with engine.connect() as conn:
        await assert_migration_head(conn)
    logger.info("worker started (poll interval=%ss, demo_mode=%s)", settings.worker_poll_interval_seconds, settings.demo_mode)
    while True:
        async with AsyncSessionLocal() as db:
            job = await _claim_next_job(db)
        if job is None:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
            continue
        await _process_job(job.id, job.worker_token)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
