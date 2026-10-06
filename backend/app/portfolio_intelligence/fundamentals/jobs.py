"""Worker job `fundamentals_refresh`: Yahoo snapshot + annual statements + an NSE cross-check for the Nifty 50, as new dated rows (nothing is overwritten).

Time-boxed chunks (the worker lease is 300 s): each chunk handles names until its budget is spent, then queues the next with what remains. Yahoo rate-limits,
so names are paced and a run of consecutive failures stops the chain instead of hammering it; the partial result is kept and the scheduler tries again later."""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from app.core.db import AsyncSessionLocal
from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument
from app.models.portfolio_jobs import PortfolioJob
from app.portfolio_intelligence.fundamentals import nse as N
from app.portfolio_intelligence.fundamentals import yahoo as Y
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.providers.fundamentals import YFinanceFundamentalProvider
from app.providers.mode import expected_fundamentals_source
from app.services.fundamental_analysis import fill_derived_ratios
from app.utils.time import utcnow

logger = logging.getLogger("fundamentals_jobs")
KIND = "fundamentals_refresh"
REFRESH_DAYS = 7
CHUNK_SECONDS = 150
YAHOO_PACE = 1.2
MAX_CONSECUTIVE_FAILURES = 5
NSE_GIVE_UP_AFTER = 3
COLUMNS = {c.name for c in FundamentalMetrics.__table__.columns}


async def enqueue_fundamentals(db: AsyncSession, key: str, *, params: dict | None = None, now: datetime | None = None, exclude_job_id: uuid.UUID | None = None):
    return await enqueue_unique(db, KIND, key, params=params, now=now, exclude_job_id=exclude_job_id)


async def universe(db: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    """(instrument id, symbol) for every company that already has fundamentals, else the seed universe."""
    rows = (await db.execute(select(Instrument.id, Instrument.symbol).where(Instrument.id.in_(select(FundamentalMetrics.instrument_id).distinct()), Instrument.is_active.is_(True))
                             .order_by(Instrument.symbol))).all()
    if rows:
        return [(i, s) for i, s in rows]
    from app.providers.nifty50_seed import NIFTY50_SEED

    syms = [s.symbol for s in NIFTY50_SEED]
    return [(i, s) for i, s in (await db.execute(select(Instrument.id, Instrument.symbol).where(Instrument.symbol.in_(syms)).order_by(Instrument.symbol))).all()]


async def is_due(db: AsyncSession, now: datetime) -> bool:
    """Due when any company's newest row is older than a week, unless a refresh was already tried in the last six hours (a partial or failed run must not be retried every tick)."""
    if (await db.execute(select(PortfolioJob.id).where(PortfolioJob.kind == KIND, PortfolioJob.created_at > now - timedelta(hours=6)).limit(1))).first():
        return False
    newest = dict((await db.execute(select(FundamentalMetrics.instrument_id, func.max(FundamentalMetrics.retrieved_at)).where(FundamentalMetrics.source == expected_fundamentals_source())
                                    .group_by(FundamentalMetrics.instrument_id))).all())
    ids = [i for i, _ in await universe(db)]
    if not ids:
        return False
    cutoff = now - timedelta(days=REFRESH_DAYS)
    for i in ids:
        t = newest.get(i)
        if t is None:
            return True
        if (t if t.tzinfo else t.replace(tzinfo=timezone.utc)) < cutoff:
            return True
    return False


@retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=4), reraise=True)
def _statements(ticker: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(ticker)
    return Y.annual_from_frames(t.balance_sheet, t.cashflow, t.financials)


async def refresh_symbol(db: AsyncSession, instrument_id: uuid.UUID, symbol: str, provider, nse_client) -> dict:
    """One company: returns a small outcome dict. Raises nothing for 'no data' (reported), only commits a row when Yahoo gave something."""
    snap = await provider.get_fundamentals(symbol)
    if snap is None or (snap.eps is None and snap.market_cap is None):
        return {"ok": False, "reason": "Yahoo returned no usable figures"}
    snap = fill_derived_ratios(snap)
    row = {k: v for k, v in snap.model_dump().items() if k in COLUMNS}
    try:
        row.update(await asyncio.to_thread(_statements, f"{symbol}.NS"))
    except Exception as exc:  # noqa: BLE001 -- annual statements are optional; the snapshot is still worth keeping
        logger.warning("annual statements failed for %s: %s", symbol, type(exc).__name__)
    nse_state = "skipped"
    if nse_client is not None:
        try:
            row.update(await N.check_symbol(nse_client, symbol))
            nse_state = "ok"
        except N.NseError as exc:
            nse_state = f"failed: {exc}"[:80]
    db.add(FundamentalMetrics(instrument_id=instrument_id, **row))
    await db.commit()
    return {"ok": True, "nse": nse_state, "annual": row.get("annual_period_end") is not None}


async def process_fundamentals_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail

    async with AsyncSessionLocal() as db:
        job = await db.get(PortfolioJob, job_id)
        params = dict(job.params or {}) if job else {}
    err, summary = None, None
    try:
        async with AsyncSessionLocal() as db:
            if "remaining" in params:
                todo = [(uuid.UUID(i), s) for i, s in params["remaining"]]
                tally = {k: params.get(k, 0) for k in ("saved", "failed_count", "nse_ok", "annual_ok")}
                failed = dict(params.get("failed") or {})
                nse_off = bool(params.get("nse_off"))
            else:
                todo, tally, failed, nse_off = await universe(db), {"saved": 0, "failed_count": 0, "nse_ok": 0, "annual_ok": 0}, {}, False
            provider = YFinanceFundamentalProvider()
            started, consecutive, nse_fail, aborted = time.monotonic(), 0, 0, False
            c = None
            if not nse_off:
                c = N.client()
                try:
                    await N.warm(c)
                except N.NseError:
                    nse_off = True
            try:
                while todo and time.monotonic() - started < CHUNK_SECONDS:
                    iid, sym = todo[0]
                    out = await refresh_symbol(db, iid, sym, provider, None if nse_off else c)
                    todo.pop(0)
                    if out["ok"]:
                        consecutive = 0
                        tally["saved"] += 1
                        tally["annual_ok"] += int(out["annual"])
                        if out["nse"] == "ok":
                            tally["nse_ok"] += 1
                            nse_fail = 0
                        elif out["nse"].startswith("failed"):
                            nse_fail += 1
                            nse_off = nse_off or nse_fail >= NSE_GIVE_UP_AFTER
                    else:
                        consecutive += 1
                        tally["failed_count"] += 1
                        failed[sym] = out["reason"]
                        if consecutive >= MAX_CONSECUTIVE_FAILURES:
                            aborted = True
                            break
                    await asyncio.sleep(YAHOO_PACE)
            finally:
                if c is not None:
                    await c.aclose()
            summary = {**tally, "failed": failed, "remaining": len(todo), "nse_off": nse_off, "aborted": aborted}
            if todo and not aborted:
                await enqueue_fundamentals(db, "continue", params={"remaining": [[str(i), s] for i, s in todo], "failed": failed, "nse_off": nse_off, **tally}, now=utcnow(), exclude_job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("fundamentals job failed")
        err = ("INTERNAL", f"{type(exc).__name__}: {str(exc)[:100]}")
    if err:
        await _fail(job_id, token, err[0], err[1], None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("fundamentals chunk done: %s", {k: v for k, v in summary.items() if k != "failed"} | {"failed_names": len(summary["failed"])})
