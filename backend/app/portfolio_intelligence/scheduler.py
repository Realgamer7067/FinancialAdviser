"""Scheduled market-close pass (plan sections 6, 12.10). At most once per
weekday, after the final close (16:00 IST, deliberately later than the 15:30
bell so a closing-auction reference price is not mistaken for the close):

1. for every included Angel account whose session is still valid, queue ONE
   sync job (typed, bounded retries); with no valid session, record an
   `auth_expired` event and flag the account so the next review says
   "reconnect" and keeps showing the last dated state;
2. queue a review (coalesced with any live one).

The unique (kind, date) marker means the API process and a worker never double
run. Nothing here ever runs the legacy recommendation pipeline."""

import asyncio
import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.models.living import SchedulerRun
from app.models.portfolio_jobs import PortfolioJob
from app.portfolio_intelligence.decisions.runner import enqueue_review
from app.portfolio_intelligence.events import record_event
from app.portfolio_intelligence.sources.angel.token_store import IST, load_session
from app.utils.time import utcnow

logger = logging.getLogger("scheduler")
CLOSE_TIME = time(16, 0)  # IST
_tasks: set = set()


async def tick(db: AsyncSession, now: datetime | None = None, client_factory=None) -> dict:
    now = now or utcnow()
    ist = now.astimezone(IST)
    from app.portfolio_intelligence.market import calendar as cal

    if not cal.is_trading_day(ist.date()):
        return {"ran": False, "reason": "weekend" if ist.weekday() >= 5 else f"exchange holiday ({cal.holiday_name(ist.date())})"}
    if ist.time() < CLOSE_TIME:
        return {"ran": False, "reason": "before the final close (16:00 IST)"}
    today = ist.date()
    if (await db.execute(select(SchedulerRun.id).where(SchedulerRun.kind == "daily_close", SchedulerRun.run_date == today))).first():
        return {"ran": False, "reason": "already ran today"}

    accounts = (await db.execute(select(SourceAccount).where(
        SourceAccount.user_id == SINGLE_USER_ID, SourceAccount.source_type == "angel_one", SourceAccount.included.is_(True)))).scalars().all()
    session_ok = load_session(now=now) is not None
    queued, expired = [], []
    for a in accounts:
        if session_ok:
            exists = (await db.execute(select(PortfolioJob.id).where(
                PortfolioJob.kind == "account_sync", PortfolioJob.account_id == a.id,
                PortfolioJob.status.in_(("queued", "running"))).limit(1))).first()
            if exists is None:
                db.add(PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=a.id, request_key=f"sched-{today}", status="queued",
                                    attempts=0, created_at=now))
                queued.append(str(a.id))
        else:
            a.status = "reconnect_required"
            a.last_error = "AUTH_EXPIRED: no valid broker session at the daily close; reconnect to refresh"
            expired.append(str(a.id))
    marker = SchedulerRun(kind="daily_close", run_date=today, ran_at=now,
                          detail={"queued_syncs": queued, "session_valid": session_ok, "expired_accounts": expired})
    db.add(marker)
    try:
        await db.commit()  # the marker's unique key decides the race between processes
    except IntegrityError:
        await db.rollback()
        return {"ran": False, "reason": "another process ran it"}
    await record_event(db, SINGLE_USER_ID, "scheduled_close", dedup_key=f"close:{today}", affected={"queued_syncs": queued, "expired": expired}, occurred_at=now)
    await _observe_thesis_prices(db)
    catalogue_job = await _queue_catalogue(db, f"daily-{today}", now)
    market_jobs = await _queue_market(db, f"daily-{today}", now, session_ok)
    watch = await _refresh_watchlist(db, now, session_ok, client_factory)
    await enqueue_review(db, SINGLE_USER_ID)
    return {"ran": True, "date": today.isoformat(), "queued_syncs": queued, "session_valid": session_ok, "expired": expired, "watchlist": watch,
            "catalogue_job": catalogue_job, "market_jobs": market_jobs}


async def _queue_catalogue(db: AsyncSession, key: str, now: datetime) -> str | None:
    """Queue the daily catalogue + corporate-actions refresh for the WORKER (never run here: bulk fetching
    stays out of the API process). Returns the job id, or None if one was already queued/running."""
    from app.portfolio_intelligence.catalogue.jobs import enqueue_refresh

    try:
        job = await enqueue_refresh(db, key, now)
    except Exception:  # noqa: BLE001 -- must never break the close pass
        await db.rollback()
        logger.exception("could not queue catalogue refresh")
        return None
    return str(job.id) if job else None


async def _queue_market(db: AsyncSession, key: str, now: datetime, session_ok: bool) -> dict:
    """Queue the final-close quote snapshot and the incremental candle fetch for the WORKER. Both need a valid broker
    session; without one nothing is queued (the reconnect issue is already raised by the account flow)."""
    from app.portfolio_intelligence.market import jobs as mj

    if not session_ok:
        return {"skipped": "no valid broker session"}
    out = {}
    for name, fn in (("snapshot", mj.enqueue_snapshot), ("backfill", mj.enqueue_backfill)):
        try:
            job = await fn(db, key, now=now)
            out[name] = str(job.id) if job else None
        except Exception:  # noqa: BLE001 -- must never break the close pass
            await db.rollback()
            logger.exception("could not queue market %s", name)
            out[name] = None
    return out


async def _bootstrap_market(db: AsyncSession) -> None:
    """With a valid session and linked securities but no prices/candles yet, queue the first snapshot and backfill now."""
    from sqlalchemy import func

    from app.models.securities import CandleSync
    from app.models.watchlist import BrokerInstrument, MarketQuote

    if load_session() is None:
        return
    linked = (await db.execute(select(func.count()).select_from(BrokerInstrument).where(BrokerInstrument.security_id.is_not(None)))).scalar_one()
    if not linked:
        return
    quotes = (await db.execute(select(func.count()).select_from(MarketQuote))).scalar_one()
    synced = (await db.execute(select(func.count()).select_from(CandleSync))).scalar_one()
    now = utcnow()
    if quotes < 100:
        await _queue_market_one(db, "snapshot", "bootstrap", now)
    if synced == 0:
        await _queue_market_one(db, "backfill", "bootstrap", now)


async def _queue_market_one(db: AsyncSession, which: str, key: str, now: datetime) -> None:
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence.market import jobs as mj

    kind = mj.SNAPSHOT if which == "snapshot" else mj.BACKFILL
    recent_fail = (await db.execute(select(PortfolioJob.id).where(PortfolioJob.kind == kind, PortfolioJob.status == "failed",
                                                                  PortfolioJob.created_at > now - timedelta(hours=1)).limit(1))).first()
    if recent_fail:  # do not hammer the broker with a bootstrap retry every scheduler tick after a failure
        return
    try:
        await (mj.enqueue_snapshot if which == "snapshot" else mj.enqueue_backfill)(db, key, now=now)
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("could not queue market %s", which)


async def _maybe_ter(db: AsyncSession) -> None:
    """Weekly expense-ratio refresh for the worker (public AMFI data, no session needed); not again for an hour after a failed attempt."""
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence.costs import jobs as tj

    now = utcnow()
    if not await tj.is_due(db, now):
        return
    if (await db.execute(select(PortfolioJob.id).where(PortfolioJob.kind == tj.KIND, PortfolioJob.status == "failed", PortfolioJob.created_at > now - timedelta(hours=1)).limit(1))).first():
        return
    try:
        await tj.enqueue_ter(db, "weekly", now=now)
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("could not queue the expense-ratio refresh")


async def _maybe_fundamentals(db: AsyncSession) -> None:
    """Weekly company-fundamentals refresh (Yahoo snapshot and annual statements, NSE cross-check); no broker session needed."""
    from app.portfolio_intelligence.fundamentals import jobs as fj

    now = utcnow()
    try:
        if await fj.is_due(db, now):
            await fj.enqueue_fundamentals(db, "weekly", now=now)
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("could not queue the fundamentals refresh")


async def _bootstrap_catalogue(db: AsyncSession) -> None:
    """First run on an empty catalogue: queue a refresh now instead of waiting for the next close."""
    from app.portfolio_intelligence.catalogue.jobs import catalogue_is_empty

    if await catalogue_is_empty(db):
        await _queue_catalogue(db, "bootstrap", utcnow())


async def _observe_thesis_prices(db: AsyncSession) -> None:
    """Record price events for active theses (observation only: never changes a thesis or its status)."""
    from app.api.v4.theses import observe_price
    from app.models.theses import Thesis

    latest: dict = {}
    for t in (await db.execute(select(Thesis).where(Thesis.user_id == SINGLE_USER_ID).order_by(Thesis.chain_id, Thesis.version.desc()))).scalars():
        latest.setdefault(t.chain_id, t)
    for t in latest.values():
        if t.status == "active":
            try:
                await observe_price(db, t)
            except Exception:  # noqa: BLE001 -- observation must never break the close pass
                await db.rollback()
                logger.exception("thesis price observation failed for %s", t.symbol)


async def _refresh_watchlist(db: AsyncSession, now: datetime, session_ok: bool, client_factory=None) -> dict:
    """After the close, refresh watched prices once (so alerts reach the inbox even if the page is closed).
    Skipped without a valid broker session; any failure is reported, never raised into the close pass."""
    from app.models.watchlist import WatchlistItem, Watchlist
    from app.portfolio_intelligence.market import alerts as alerts_mod
    from app.portfolio_intelligence.market import quotes as quotes_mod
    from app.portfolio_intelligence.sources.angel.client import AngelClient
    from app.portfolio_intelligence.sources.angel.errors import AngelError

    ids = [r for (r,) in (await db.execute(select(WatchlistItem.broker_instrument_id).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                                            .where(Watchlist.user_id == SINGLE_USER_ID).distinct())).all()]
    if not ids:
        return {"skipped": "empty watchlist"}
    if not session_ok:
        return {"skipped": "no valid broker session"}
    client = await client_factory() if client_factory else AngelClient(jwt=load_session(now=now).jwt)
    try:
        stats = await quotes_mod.refresh_quotes(db, ids, client, now=now)
        stats["alerts"] = await alerts_mod.evaluate_alerts(db, SINGLE_USER_ID, now)
        return stats
    except AngelError as exc:
        await db.rollback()
        return {"error": exc.code}
    finally:
        await client.aclose()


async def run_inline(kinds=("review", "account_sync"), max_jobs: int = 10) -> int:
    from app.core.db import AsyncSessionLocal
    from app.portfolio_intelligence.jobs import claim_next_portfolio_job, process_portfolio_job

    n = 0
    for _ in range(max_jobs):
        async with AsyncSessionLocal() as db:
            job = await claim_next_portfolio_job(db, kinds=kinds)
        if job is None:
            break
        await process_portfolio_job(job.id, job.worker_token)
        n += 1
    return n


async def scheduler_loop() -> None:
    from app.core.db import AsyncSessionLocal

    logger.info("scheduler started (every %ss)", settings.scheduler_interval_seconds)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await tick(db)
                await _bootstrap_catalogue(db)
                await _bootstrap_market(db)
                await _maybe_ter(db)
                await _maybe_fundamentals(db)
                from app.portfolio_intelligence.market import holidays as _hol

                await _hol.load_calendar(db)   # pick up holidays the worker stored (this process loads them only at startup otherwise)
            if result.get("ran"):
                logger.info("scheduled close ran: %s", result)
            await run_inline()  # also drains due retries and any queued review/sync
        except Exception:  # noqa: BLE001 -- the loop must survive any single failure
            logger.exception("scheduler tick failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


def start_scheduler() -> None:
    if not settings.scheduler_enabled:
        return
    task = asyncio.get_running_loop().create_task(scheduler_loop())
    _tasks.add(task)
