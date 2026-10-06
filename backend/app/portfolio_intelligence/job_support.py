"""Small shared helpers for worker-only typed jobs (catalogue refresh, market snapshot, candle backfill)."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.utils.time import utcnow

logger = logging.getLogger("job_support")


async def enqueue_unique(db: AsyncSession, kind: str, key: str, *, params: dict | None = None, now: datetime | None = None,
                         exclude_job_id: uuid.UUID | None = None) -> PortfolioJob | None:
    """Queue one job of `kind` unless a queued/running job of that kind with the SAME params exists (None == None, so
    two bulk jobs block each other, while a per-security on-demand job never blocks the bulk chain or another
    security). `exclude_job_id` is the caller's own running job, so a job can queue its own follow-up."""
    live = (await db.execute(select(PortfolioJob).where(PortfolioJob.kind == kind, PortfolioJob.status.in_(("queued", "running"))))).scalars().all()
    if any(j.id != exclude_job_id and (j.params or None) == (params or None) for j in live):
        return None
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind=kind, account_id=None, request_key=f"{key}-{uuid.uuid4().hex[:8]}", status="queued",
                       attempts=0, created_at=now or utcnow(), params=params)
    db.add(job)
    await db.commit()
    return job


async def finish_job(session_factory, job_id: uuid.UUID, token: str, summary: dict, *, complete: bool) -> bool:
    """Fenced terminal write: records `summary` as the job's result and, when `complete`, marks it done. Returns False
    (and writes nothing) if this attempt was superseded. A not-complete job keeps its result and the caller then
    routes it through the normal failure/retry path."""
    async with session_factory() as db:
        job = (await db.execute(select(PortfolioJob).where(PortfolioJob.id == job_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if job is None or job.worker_token != token or job.status != "running":
            logger.warning("job %s: dropping stale completion", job_id)
            return False
        job.result = summary
        if complete:
            job.status, job.completed_at, job.error, job.error_code = "done", utcnow(), None, None
        await db.commit()
    return True
