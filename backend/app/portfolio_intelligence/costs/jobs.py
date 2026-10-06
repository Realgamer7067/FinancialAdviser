"""Worker job `ter_refresh`: a chain of time-boxed chunks (each fetches AMCs until its budget is spent and queues the next), then one matching pass."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import SchemeTer
from app.portfolio_intelligence.costs import ter_source as T
from app.portfolio_intelligence.costs import ter_sync as S
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.utils.time import utcnow

logger = logging.getLogger("ter_jobs")
KIND = "ter_refresh"
REFRESH_DAYS = 7


async def enqueue_ter(db: AsyncSession, key: str, *, params: dict | None = None, now: datetime | None = None, exclude_job_id: uuid.UUID | None = None):
    return await enqueue_unique(db, KIND, key, params=params, now=now, exclude_job_id=exclude_job_id)


async def is_due(db: AsyncSession, now: datetime) -> bool:
    newest = (await db.execute(select(func.max(SchemeTer.fetched_at)))).scalar_one()
    if newest is None:
        return True
    from datetime import timezone

    return (now - (newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc))).days >= REFRESH_DAYS


async def process_ter_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail

    async with AsyncSessionLocal() as db:
        job = await db.get(PortfolioJob, job_id)
        params = dict(job.params or {}) if job else {}
    summary, err = None, None
    try:
        async with AsyncSessionLocal() as db:
            now = utcnow()
            if "amcs" in params:
                amcs, failed, done_total = params["amcs"], dict(params.get("failed") or {}), int(params.get("done_total") or 0)
            else:
                async with T.client() as c:
                    amcs, failed, done_total = await T.list_amcs(c), {}, 0
            chunk = await S.fetch_chunk(db, amcs, today=now.astimezone(IST).date())
            failed.update({str(k): v for k, v in chunk["failed"].items()})
            done_total += len(chunk["done"])
            if chunk["remaining"]:
                await enqueue_ter(db, "continue", params={"amcs": chunk["remaining"], "failed": failed, "done_total": done_total}, now=now, exclude_job_id=job_id)
                summary = {"chunk_done": len(chunk["done"]), "remaining": len(chunk["remaining"]), "done_total": done_total, "failed": failed}
            else:
                summary = {"chunk_done": len(chunk["done"]), "remaining": 0, "done_total": done_total, "failed": failed, "matching": await S.match_all(db, now)}
    except T.TerError as exc:
        err = ("UNAVAILABLE", str(exc)[:120])
    except Exception as exc:  # noqa: BLE001
        logger.exception("ter job failed")
        err = ("INTERNAL", f"{type(exc).__name__}: {str(exc)[:100]}")
    if err:
        await _fail(job_id, token, err[0], err[1], None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("ter chunk done: %s", {k: v for k, v in summary.items() if k != "failed"} | {"failed_amcs": len(summary["failed"])})
