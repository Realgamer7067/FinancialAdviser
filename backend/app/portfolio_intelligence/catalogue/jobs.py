"""Catalogue refresh as a typed portfolio job. Bulk fetching (five public files plus NSE corporate-action
windows) runs ONLY in the worker: the Angel client's rate limiter is per process, so any bulk work in the API
process could double the broker's request budget. The API only enqueues."""

import logging
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import Security
from app.portfolio_intelligence.job_support import finish_job
from app.utils.time import utcnow

logger = logging.getLogger("catalogue_jobs")
KIND = "catalogue_refresh"


async def enqueue_refresh(db: AsyncSession, key: str, now: datetime | None = None) -> PortfolioJob | None:
    """Queue one refresh unless one is already queued/running. `key` labels the reason (e.g. daily-2026-10-01)."""
    now = now or utcnow()
    live = (await db.execute(select(PortfolioJob.id).where(PortfolioJob.kind == KIND, PortfolioJob.status.in_(("queued", "running"))).limit(1))).first()
    if live is not None:
        return None
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind=KIND, account_id=None, request_key=f"{key}-{uuid.uuid4().hex[:8]}", status="queued", attempts=0, created_at=now)
    db.add(job)
    await db.commit()
    return job


async def catalogue_is_empty(db: AsyncSession) -> bool:
    return (await db.execute(select(func.count()).select_from(Security))).scalar_one() == 0


def _outcome(report: dict) -> tuple[str, dict]:
    """done | UNAVAILABLE, plus a small summary. A run that produced nothing at all is a failure to retry; a
    partial run (some files stale, some windows stored) is done, with the gaps recorded for the UI."""
    cat = report.get("catalogue") or {}
    actions = report.get("actions") or {}
    produced = bool(cat) or actions.get("windows_done", 0) > 0
    summary = {"fetch_errors": report.get("fetch_errors") or {}, "catalogue_error": report.get("catalogue_error"),
               "counts": {k: (v.get("added", 0) + v.get("updated", 0)) for k, v in cat.items() if isinstance(v, dict) and "added" in v},
               "linked_broker": cat.get("linked_broker"), "actions": {k: actions.get(k) for k in ("windows_done", "events_stored", "failed")}}
    return ("done" if produced else "UNAVAILABLE"), summary


async def process_refresh(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.catalogue.sync import refresh_catalogue
    from app.portfolio_intelligence.jobs import _fail

    async with AsyncSessionLocal() as db:
        try:
            report = await refresh_catalogue(db)
        except Exception:  # noqa: BLE001 -- never crash the worker loop
            logger.exception("catalogue refresh crashed")
            await db.rollback()
            report = None
    if report is None:
        await _fail(job_id, token, "INTERNAL", "catalogue refresh failed (see worker log)", None)
        return
    status, summary = _outcome(report)
    complete = status == "done" and not (summary["fetch_errors"] or summary["actions"]["failed"] or summary["catalogue_error"])
    if not await finish_job(AsyncSessionLocal, job_id, token, summary, complete=complete):
        return
    if not complete:
        # Everything fetched is already stored (upserts, resume-from-last-date), so a retry only fills the gaps.
        await _fail(job_id, token, "UNAVAILABLE", "some sources or corporate-action windows could not be fetched; retrying", None)
        return
    logger.info("catalogue refresh done: %s", summary)
    try:   # the fund NAV histories are verified against the AMFI NAVs this refresh just loaded
        from app.portfolio_intelligence.funds.jobs import enqueue_nav

        async with AsyncSessionLocal() as db:
            await enqueue_nav(db, "after-catalogue", now=utcnow())
    except Exception:  # noqa: BLE001
        logger.exception("could not queue the fund NAV sync")
