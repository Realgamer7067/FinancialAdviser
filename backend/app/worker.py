"""Background worker (Section 70). The API never runs the pipeline inline --
it enqueues a RecommendationJob row and this process polls for queued work.
Deliberately a plain asyncio loop, not Celery/Redis, per the "don't
overengineer" instruction (Section 64) -- one worker is enough for the MVP's
scale."""

import asyncio
import logging
import traceback

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.system import RecommendationJob
from app.pipelines.recommendation_pipeline import PipelineError, run_recommendation_pipeline
from app.utils.time import utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
logger = logging.getLogger("worker")


async def _claim_next_job(db: AsyncSession) -> RecommendationJob | None:
    job = (
        await db.execute(
            select(RecommendationJob).where(RecommendationJob.status == "queued").order_by(RecommendationJob.created_at).limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = utcnow()
    await db.commit()
    return job


async def _mark_failed(job_id, error: str) -> None:
    """Runs in its own fresh session -- the session that ran the pipeline may
    be left in a failed/pending-rollback state by whatever raised, and trying
    to commit through it would itself raise (Section 50: a failed job must
    still be recorded, never silently disappear)."""
    async with AsyncSessionLocal() as db:
        job = await db.get(RecommendationJob, job_id)
        job.status = "failed"
        job.error = error
        job.completed_at = utcnow()
        await db.commit()


async def _process_job(job_id) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(RecommendationJob, job_id)
        try:
            council_run = await run_recommendation_pipeline(db, job.user_id, job_id=job.id)
            job.status = "done"
            job.completed_at = utcnow()
            job.result_council_run_id = council_run.id
            await db.commit()
            logger.info("job %s done -> council_run %s", job.id, council_run.id)
            return
        except PipelineError as exc:
            error = str(exc)
            logger.warning("job %s failed: %s", job.id, exc)
        except Exception as exc:  # noqa: BLE001 -- must never crash the worker loop (Section 50)
            error = f"{exc}\n{traceback.format_exc()[-2000:]}"
            logger.exception("job %s crashed", job.id)
        await db.rollback()  # the session may be unusable after the failure above

    await _mark_failed(job_id, error)


async def run_worker_loop() -> None:
    logger.info("worker started (poll interval=%ss, demo_mode=%s)", settings.worker_poll_interval_seconds, settings.demo_mode)
    while True:
        async with AsyncSessionLocal() as db:
            job = await _claim_next_job(db)
        if job is None:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
            continue
        await _process_job(job.id)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
