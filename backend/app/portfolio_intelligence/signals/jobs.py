"""Worker-only signal jobs. `signals_compute` is one bulk job (read history, numpy in a thread, insert-only store);
it is queued when the candle backfill chain has nothing left, and by the close pass as a fallback. A second trigger
for the same data is harmless: stored rows are never rewritten."""

import logging
import uuid
from datetime import datetime

from app.core.db import AsyncSessionLocal
from app.portfolio_intelligence.job_support import enqueue_unique, finish_job
from app.utils.time import utcnow

logger = logging.getLogger("signal_jobs")
COMPUTE = "signals_compute"


async def enqueue_signals(db, key: str, now: datetime | None = None):
    return await enqueue_unique(db, COMPUTE, key, now=now)


async def process_signals_job(job_id: uuid.UUID, token: str) -> None:
    from app.portfolio_intelligence.jobs import _fail
    from app.portfolio_intelligence.signals.run import run_signals

    summary, code = None, None
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_signals(db, utcnow())
        summary["scores"] = await _scores_step()
        summary["suggestions"] = await _suggestions_step()
        from app.portfolio_intelligence.ledger.jobs import scoring_step

        summary["ledger"] = await scoring_step()
    except Exception:  # noqa: BLE001 -- never crash the worker loop
        logger.exception("signals job %s crashed", job_id)
        code = "INTERNAL"
    if code:
        await _fail(job_id, token, code, "signal computation failed (see worker log)", None)
        return
    if await finish_job(AsyncSessionLocal, job_id, token, summary, complete=True):
        logger.info("signals done: %s", {k: v for k, v in summary.items() if k != "independence"})
        from app.portfolio_intelligence.signals.forecast import enqueue_forecasts

        async with AsyncSessionLocal() as db:   # the forecast shortlist uses the liquidity just computed
            await enqueue_forecasts(db, "after-signals", utcnow(), exclude_job_id=job_id)


async def _scores_step() -> dict:
    """Store the day's checklist scores (insert-only). A failure is reported in the job result and never fails the signal computation."""
    from app.portfolio_intelligence.scoring.service import current_ranking, current_scores

    try:
        async with AsyncSessionLocal() as db:
            r = await current_scores(db, now=utcnow())
            rows = r["rows"].values()
            rk = await current_ranking(db, now=utcnow())
            ranked = rk["rows"].values()
            return {"scored": sum(1 for x in rows if x["score"] is not None), "below_floor": sum(1 for x in rows if x["status"] == "below_floor"), "not_scored": sum(1 for x in rows if x["status"] == "not_scored"),
                    "ranked": sum(1 for x in ranked if x["composite"] is not None), "ranking_eligible": sum(1 for x in ranked if x["status"] == "eligible")}
    except Exception as exc:  # noqa: BLE001
        logger.exception("score step failed")
        return {"error": type(exc).__name__}


async def _suggestions_step() -> dict:
    """After the day's signals: raise/clear the state-based inbox items and log new triggers. A failure here is reported in the
    job result and never fails (or retries) the signal computation itself."""
    from app.portfolio_intelligence.suggestions.build import build_suggestions
    from app.portfolio_intelligence.suggestions.persist import persist_suggestions

    try:
        async with AsyncSessionLocal() as db:
            now = utcnow()
            built = await build_suggestions(db, now)
            stats = await persist_suggestions(db, built, now)
            return {**stats, "held": len(built["held"]), "watched": len(built["watched"])}
    except Exception as exc:  # noqa: BLE001
        logger.exception("suggestion step failed")
        return {"error": type(exc).__name__}
