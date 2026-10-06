"""Worker job `fund_nav_sync`: verified NAV histories for the SIP-list funds and the funds you hold. Queued after the nightly catalogue refresh
(which refreshes the AMFI NAVs the histories are verified against) and on demand."""

import logging
import uuid

from sqlalchemy import select

from app.core.db import AsyncSessionLocal
from app.models.securities import Security
from app.portfolio_intelligence.funds import nav_sync as S
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.utils.time import utcnow

logger = logging.getLogger("fund_jobs")
KIND = "fund_nav_sync"


async def enqueue_nav(db, key: str, *, params: dict | None = None, now=None):
    return await enqueue_unique(db, KIND, key, params=params, now=now)


async def process_nav_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail
    from app.portfolio_intelligence.job_support import finish_job as _finish

    summary, err = None, None
    try:
        async with AsyncSessionLocal() as db:
            from app.models.portfolio_jobs import PortfolioJob

            job = await db.get(PortfolioJob, job_id)
            ids = (job.params or {}).get("security_ids") if job else None
            if ids:
                funds = list((await db.execute(select(Security).where(Security.id.in_([uuid.UUID(i) for i in ids]), Security.kind == "mutual_fund"))).scalars())
            else:
                funds = await S.target_funds(db, await S.held_fund_isins(db))
            summary = {"targets": len(funds), **await S.sync_all(db, funds, now=utcnow())}
    except Exception as exc:  # noqa: BLE001
        logger.exception("fund NAV job failed")
        err = f"{type(exc).__name__}: {str(exc)[:100]}"
    if err:
        await _fail(job_id, token, "INTERNAL", err, None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("fund NAV sync done: %s", {k: v for k, v in summary.items() if k not in ("rejected", "errors")} | {"rejected": len(summary["rejected"]), "errors": len(summary["errors"])})
