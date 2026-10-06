"""Worker-only market jobs: the full-market quote snapshot and the daily-candle backfill.

Both run ONLY in the worker (the Angel client's limiter is per process, so bulk calls in the API process could
double the broker's request budget), in bounded chunks that finish well inside the job lease (300 s, no
heartbeat). A candle job that leaves work behind queues its own follow-up, so a backfill of any size is a
chain of short jobs that survives restarts."""

import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.portfolio_jobs import PortfolioJob  # noqa: F401 -- re-exported for the API
from app.models.securities import CandleSync, Security
from app.models.watchlist import BrokerInstrument, WatchlistItem
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.portfolio_intelligence.market import candles as candles_mod
from app.portfolio_intelligence.market import quotes as quotes_mod
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import AngelError, AuthExpired, RateLimited
from app.portfolio_intelligence.sources.angel.token_store import IST, load_session
from app.utils.time import utcnow

logger = logging.getLogger("market_jobs")
SNAPSHOT, BACKFILL = "market_snapshot", "candle_backfill"
SNAPSHOT_CHUNK = 500          # tokens per DB commit (10 broker requests of 50): progress survives a mid-run failure
BACKFILL_CHUNK = 100          # securities per job: ~100 s at the 1 request/s floor, inside the 300 s lease
DEFAULT_MAX_TIER = 2          # 0 watched, 1 ETFs, 2 stocks with a sector; tier 3 (the rest) only on demand


async def snapshot_quotes(db: AsyncSession, client, now: datetime | None = None, chunk: int = SNAPSHOT_CHUNK) -> dict:
    """Latest FULL quote for every Angel-tradable catalogue stock/ETF. Each chunk is committed, so an auth/rate
    failure at chunk k keeps chunks 1..k-1."""
    now = now or utcnow()
    ids = [i for (i,) in (await db.execute(select(BrokerInstrument.id).where(BrokerInstrument.security_id.is_not(None), BrokerInstrument.series == "EQ")
                                           .order_by(BrokerInstrument.symbol))).all()]
    total = {"requested": 0, "refreshed": 0, "unfetched": 0, "unparsed": 0, "chunks_done": 0, "chunks": (len(ids) + chunk - 1) // chunk}
    for i in range(0, len(ids), chunk):
        r = await quotes_mod.refresh_quotes(db, ids[i : i + chunk], client, mode="FULL", now=now)
        total["requested"] += r["requested"]
        total["refreshed"] += r["refreshed"]
        total["unfetched"] += len(r["unfetched"])
        total["unparsed"] += len(r["unparsed"])
        total["chunks_done"] += 1
    return total


async def candle_targets(db: AsyncSession, now: datetime, *, max_tier: int = DEFAULT_MAX_TIER, security_ids: list[str] | None = None,
                         limit: int | None = None) -> list[tuple]:
    """[(security_id, token, tier)] needing a candle fetch, best-first. Needs work = never fetched, or its newest stored
    day is behind the last final session AND it was not already fetched today (so a holiday is tried once per day)."""
    expected = candles_mod.expected_last_session(now)
    today_ist = now.astimezone(IST).date()
    watched = {i for (i,) in (await db.execute(select(BrokerInstrument.security_id).join(WatchlistItem, WatchlistItem.broker_instrument_id == BrokerInstrument.id)
                                                 .where(BrokerInstrument.security_id.is_not(None)))).all()}
    stmt = (select(Security.id, Security.kind, Security.sector, BrokerInstrument.token, CandleSync.last_date, CandleSync.fetched_at, CandleSync.row_count)
            .join(BrokerInstrument, BrokerInstrument.security_id == Security.id).outerjoin(CandleSync, CandleSync.security_id == Security.id)
            .where(Security.is_active.is_(True), Security.kind.in_(("stock", "etf")), BrokerInstrument.series == "EQ"))
    if security_ids is not None:
        stmt = stmt.where(Security.id.in_([uuid.UUID(s) for s in security_ids]))
    out = []
    for sid, kind, sector, token, last_date, fetched_at, rows in (await db.execute(stmt)).all():
        tier = 0 if sid in watched else 1 if kind == "etf" else 2 if sector else 3
        if security_ids is None:
            if tier > max_tier:
                continue
            fetched_today = fetched_at is not None and fetched_at.astimezone(IST).date() == today_ist
            if last_date is not None and not (last_date < expected and not fetched_today):
                continue
            if last_date is None and fetched_today and not rows:
                continue  # failed/empty today already; try again tomorrow
        out.append((sid, token, tier))
    out.sort(key=lambda t: (t[2], str(t[0])))
    return out[:limit] if limit else out


async def backfill_candles(db: AsyncSession, client, targets: list[tuple], now: datetime | None = None) -> dict:
    now = now or utcnow()
    today = now.astimezone(IST).date()
    res = {"securities": 0, "rows_added": 0, "rebased": 0, "empty": 0, "errors": 0}
    for sid, token, _tier in targets:
        first, last, n = await candles_mod.stored_range(db, sid)
        start = today - timedelta(days=candles_mod.HISTORY_DAYS)
        from_date = (last - timedelta(days=candles_mod.OVERLAP_DAYS)) if n and last else start
        try:
            raw = await client.get_daily_candles("NSE", token, from_date.isoformat(), today.isoformat())
            parsed, _bad = candles_mod.parse_candles(raw)

            async def full(_token=token):
                p, _ = candles_mod.parse_candles(await client.get_daily_candles("NSE", _token, start.isoformat(), today.isoformat()))
                return p

            if not parsed and not n:
                res["empty"] += 1
                await candles_mod.mark_sync_error(db, sid, "no candles returned", now)
            else:
                r = await candles_mod.apply_fetch(db, sid, parsed, today=today, now=now, refetch_full=full)
                res["rows_added"] += r["added"]
                res["rebased"] += int(r["rebased"])
            await db.commit()
            res["securities"] += 1
        except (AuthExpired, RateLimited):
            await db.rollback()
            raise  # job-level: auth needs the owner, rate limits need a pause; progress so far is committed
        except AngelError as exc:
            await db.rollback()
            await candles_mod.mark_sync_error(db, sid, f"{exc.code}", now)
            await db.commit()
            res["errors"] += 1
    return res


async def enqueue_snapshot(db: AsyncSession, key: str, now: datetime | None = None):
    return await enqueue_unique(db, SNAPSHOT, key, now=now)


async def enqueue_backfill(db: AsyncSession, key: str, *, security_ids: list[str] | None = None, now: datetime | None = None,
                           exclude_job_id: uuid.UUID | None = None):
    params = {"security_ids": sorted(security_ids)} if security_ids else None
    return await enqueue_unique(db, BACKFILL, key, params=params, now=now, exclude_job_id=exclude_job_id)


async def process_market_job(job_id: uuid.UUID, token: str) -> None:
    from app.models.portfolio_jobs import PortfolioJob
    from app.portfolio_intelligence.jobs import _fail

    async with AsyncSessionLocal() as db:
        job = await db.get(PortfolioJob, job_id)
        kind, params = (job.kind, job.params or {}) if job else (None, {})
    code = message = None
    summary: dict = {}
    client = None
    try:
        sess = load_session()
        if sess is None:
            raise AuthExpired("no valid broker session")
        client = AngelClient(jwt=sess.jwt)
        async with AsyncSessionLocal() as db:
            if kind == SNAPSHOT:
                summary = await snapshot_quotes(db, client)
            else:
                now = utcnow()
                ids = params.get("security_ids")
                targets = await candle_targets(db, now, security_ids=ids, limit=BACKFILL_CHUNK)
                summary = await backfill_candles(db, client, targets, now)
                if not ids:
                    left = len(await candle_targets(db, now))
                    summary["remaining"] = left
                    if left:
                        await enqueue_backfill(db, "continue", now=now, exclude_job_id=job_id)
                    else:  # the chain has caught up: compute the day's signals (a repeat is a no-op, stored rows are never rewritten)
                        from app.portfolio_intelligence.signals.jobs import enqueue_signals

                        await enqueue_signals(db, "after-backfill", now=now)
    except AngelError as exc:
        code, message = exc.code, str(exc)
    except Exception:  # noqa: BLE001 -- never crash the worker loop; never log payloads
        logger.exception("market job %s crashed", job_id)
        code, message = "INTERNAL", "unexpected error (see worker log)"
    finally:
        if client is not None:
            await client.aclose()
    if code is not None:
        await _fail(job_id, token, code, message, None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("%s done: %s", kind, summary)
