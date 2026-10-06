"""Worker jobs for the ledger: the retrospective study (on demand, stored once per study version and data marker) and the nightly scoring
step that runs after the signals and suggestions steps."""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.securities import LedgerStudy
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.portfolio_intelligence.ledger import backtest, panel
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger.score import score_pending
from app.utils.time import utcnow

logger = logging.getLogger("ledger_jobs")
STUDY = "ledger_study"


async def enqueue_study(db: AsyncSession, key: str, now: datetime | None = None):
    return await enqueue_unique(db, STUDY, key, now=now)


async def run_and_store_study(db: AsyncSession, now: datetime | None = None) -> dict:
    """Run the registered study on the stored panel and keep it, once per (study version, data marker). A second call with unchanged data
    returns the stored one: results cannot be re-rolled by re-running."""
    now = now or utcnow()
    close, volume, total_return, meta = await panel.load_panel(db)
    existing = (await db.execute(select(LedgerStudy).where(LedgerStudy.study_version == R.STUDY_VERSION_V2, LedgerStudy.data_marker == meta["data_marker"]))).scalar_one_or_none()
    if existing is not None:
        return {"created": False, "study_id": str(existing.id), "data_marker": meta["data_marker"]}
    result = await asyncio.to_thread(backtest.run_study, close, volume, total_return)
    result["panel"] = meta
    row = LedgerStudy(study_version=R.STUDY_VERSION_V2, registry_hash=R.registry_hash_v2(), data_marker=meta["data_marker"], evidence="backtest", result=result, created_at=now)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        row = (await db.execute(select(LedgerStudy).where(LedgerStudy.study_version == R.STUDY_VERSION_V2, LedgerStudy.data_marker == meta["data_marker"]))).scalar_one()
        return {"created": False, "study_id": str(row.id), "data_marker": meta["data_marker"]}
    return {"created": True, "study_id": str(row.id), "data_marker": meta["data_marker"]}


async def process_study_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail

    summary, err = None, None
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_and_store_study(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ledger study failed")
        err = f"{type(exc).__name__}: {str(exc)[:120]}"
    if err:
        await _fail(job_id, token, "INTERNAL", err, None)
        return
    await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True)


async def scoring_step() -> dict:
    """Nightly, after signals and suggestions. A failure is reported in the job result and never fails the signals job."""
    try:
        async with AsyncSessionLocal() as db:
            return await score_pending(db, utcnow())
    except Exception as exc:  # noqa: BLE001
        logger.exception("ledger scoring failed")
        return {"error": type(exc).__name__}
