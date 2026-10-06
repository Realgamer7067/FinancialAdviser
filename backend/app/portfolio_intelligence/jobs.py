"""Typed portfolio job dispatch: claim (SKIP LOCKED + lease), process, fenced
terminal writes. Mirrors app/worker.py's RecommendationJob pattern but for
PortfolioJob, so the legacy Nifty pipeline never runs for portfolio work."""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.accounts import SourceAccount
from app.models.portfolio_jobs import PortfolioJob
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence.sources.angel.errors import AngelError, AuthExpired
from app.portfolio_intelligence.sources.angel.sync import fetch_account_snapshot, publish_sync_result
from app.utils.time import utcnow

logger = logging.getLogger("portfolio_jobs")
MAX_ATTEMPTS = 3
# Transient provider failures are retried with exponential backoff, at most MAX_ATTEMPTS in total.
# Auth expiry and partial data are NOT retried: they need the owner (reconnect) or a changed source.
RETRYABLE = {"RATE_LIMITED", "UNAVAILABLE"}
BACKOFF_BASE_SECONDS = 60


async def claim_next_portfolio_job(db: AsyncSession, kinds: tuple[str, ...] | None = None) -> PortfolioJob | None:
    now = utcnow()
    stmt = select(PortfolioJob)
    if kinds:
        stmt = stmt.where(PortfolioJob.kind.in_(kinds))
    job = (
        await db.execute(
            stmt
            .where(or_(
                (PortfolioJob.status == "queued") & (or_(PortfolioJob.not_before.is_(None), PortfolioJob.not_before <= now)),
                (PortfolioJob.status == "running") & (PortfolioJob.lease_expires_at < now),
            ))
            .order_by(PortfolioJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    if job.attempts >= MAX_ATTEMPTS:  # abandoned repeatedly: stop reclaiming it
        job.status = "failed"
        job.error_code = "INTERNAL"
        job.error = "job abandoned too many times"
        job.completed_at = now
        await db.commit()
        return None
    job.status = "running"
    job.attempts += 1
    job.started_at = now
    job.worker_token = str(uuid.uuid4())
    job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    await db.commit()
    return job


async def _fail(job_id: uuid.UUID, token: str, code: str, message: str, account_id: uuid.UUID | None) -> None:
    """Fresh session; fenced on the token so a superseded attempt cannot
    overwrite a newer attempt's outcome. The account keeps its last good import."""
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(PortfolioJob).where(PortfolioJob.id == job_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if job is None or job.worker_token != token or job.status != "running":
            logger.warning("portfolio job %s: dropping stale failure write", job_id)
            return
        now = utcnow()
        retry = code in RETRYABLE and job.kind in ("account_sync", "catalogue_refresh", "market_snapshot", "candle_backfill", "signals_compute", "kronos_forecast", "ledger_study", "ter_refresh", "fund_nav_sync", "fundamentals_refresh") and job.attempts < MAX_ATTEMPTS
        job.error_code = code
        job.error = message[:500]
        if retry:
            job.status = "queued"
            job.worker_token = None
            job.lease_expires_at = None
            job.not_before = now + timedelta(seconds=BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1)))
        else:
            job.status = "failed"
            job.completed_at = now
        if account_id is not None:
            account = await db.get(SourceAccount, account_id)
            if account is not None:
                # The last good import is untouched: a failed sync never erases holdings.
                account.last_error = f"{code}: {message[:200]}" + (" (retry scheduled)" if retry else "")
                if code == "AUTH_EXPIRED":
                    account.status = "reconnect_required"
        user_id = job.user_id
        await db.commit()
    if not retry and code in ("AUTH_EXPIRED", "RATE_LIMITED", "UNAVAILABLE", "PARTIAL_DATA", "IDENTITY_CONFLICT") and account_id is not None:
        from app.portfolio_intelligence.events import record_event

        async with AsyncSessionLocal() as db2:
            await record_event(db2, user_id, "auth_expired" if code == "AUTH_EXPIRED" else "sync_failed", dedup_key=f"{code}:{account_id}:{job_id}",
                               source_id=str(account_id), affected={"account_id": str(account_id), "code": code})
        if code == "AUTH_EXPIRED":  # surface the reconnect issue now, from the last good snapshot
            from app.portfolio_intelligence.decisions.runner import enqueue_review, kick_inline_reviews

            async with AsyncSessionLocal() as db3:
                await enqueue_review(db3, user_id)
            kick_inline_reviews()


async def process_portfolio_job(job_id: uuid.UUID, token: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(PortfolioJob, job_id)
        if job is not None and job.kind == "review":
            await _process_review(db, job, token)
            return
        if job is not None and job.kind == "fund_nav_sync":
            from app.portfolio_intelligence.funds.jobs import process_nav_job

            await process_nav_job(job_id, token)
            return
        if job is not None and job.kind == "fundamentals_refresh":
            from app.portfolio_intelligence.fundamentals.jobs import process_fundamentals_job

            await process_fundamentals_job(job_id, token)
            return
        if job is not None and job.kind == "ter_refresh":
            from app.portfolio_intelligence.costs.jobs import process_ter_job

            await process_ter_job(job_id, token)
            return
        if job is not None and job.kind == "ledger_study":
            from app.portfolio_intelligence.ledger.jobs import process_study_job

            await process_study_job(job_id, token)
            return
        if job is not None and job.kind == "kronos_forecast":
            from app.portfolio_intelligence.signals.forecast import process_forecast_job

            await process_forecast_job(job_id, token)
            return
        if job is not None and job.kind == "signals_compute":
            from app.portfolio_intelligence.signals.jobs import process_signals_job

            await process_signals_job(job_id, token)
            return
        if job is not None and job.kind in ("market_snapshot", "candle_backfill"):
            from app.portfolio_intelligence.market.jobs import process_market_job

            await process_market_job(job_id, token)
            return
        if job is not None and job.kind == "catalogue_refresh":
            from app.portfolio_intelligence.catalogue.jobs import process_refresh

            await process_refresh(job_id, token)
            return
        if job is None or job.kind != "account_sync" or job.account_id is None:
            await _fail(job_id, token, "INTERNAL", "unsupported job", None)
            return
        account_id = job.account_id
        account = await db.get(SourceAccount, account_id)
        try:
            if account is None or account.source_type != "angel_one":
                raise AngelError("not an Angel account")
            parsed, summary = await fetch_account_snapshot(account)
            await publish_sync_result(db, job_id, token, account_id, parsed, summary)
            logger.info("portfolio job %s finished (%s, %d rows)", job_id, parsed.status, len(parsed.rows))
            return
        except StalePublicationError:
            await db.rollback()
            logger.warning("portfolio job %s: attempt superseded before publication, dropping", job_id)
            return
        except AngelError as exc:
            code, message = exc.code, str(exc)
        except Exception:  # noqa: BLE001 -- never crash the loop; never log payloads
            logger.exception("portfolio job %s crashed", job_id)
            code, message = "INTERNAL", "unexpected error (see worker log)"
        await db.rollback()
    await _fail(job_id, token, code, message, account_id)


async def _process_review(db: AsyncSession, job: PortfolioJob, token: str) -> None:
    from app.portfolio_intelligence.decisions.runner import compute_review, publish_review

    job_id, user_id = job.id, job.user_id
    try:
        computed = await compute_review(db, user_id)
        if computed is None:
            # Nothing to review yet (no snapshot): a valid, empty completion, not an error.
            await db.rollback()
            async with AsyncSessionLocal() as s2:
                j = (await s2.execute(select(PortfolioJob).where(PortfolioJob.id == job_id).with_for_update())).scalar_one_or_none()
                if j is not None and j.worker_token == token and j.status == "running":
                    j.status = "done"
                    j.completed_at = utcnow()
                    await s2.commit()
            return
        await publish_review(db, job_id, token, computed)
        logger.info("review job %s published (%s)", job_id, computed["status"])
        return
    except StalePublicationError:
        await db.rollback()
        logger.warning("review job %s: attempt superseded before publication, dropping", job_id)
        return
    except Exception:  # noqa: BLE001 -- never crash the loop; never log payloads
        logger.exception("review job %s crashed", job_id)
        await db.rollback()
    await _fail(job_id, token, "INTERNAL", "review failed (see worker log)", None)
