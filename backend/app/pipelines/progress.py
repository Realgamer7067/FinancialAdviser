"""Job-progress tracking for the recommendation pipeline (dashboard progress bar).

Deliberately writes through a SEPARATE session from the pipeline's own --
run_recommendation_pipeline holds one long-lived, mostly-uncommitted
transaction (a single `await db.commit()` at the very end), so writing
progress through that session would (a) not be visible to the job-status
poller, which reads via its own connection, until the whole run finishes,
defeating the point, and (b) make partial pipeline state durable on a crash
if we started committing that session early. A dedicated short-lived
session per stage update, committed immediately, has neither problem.

No-op when job_id is None -- protects the pipeline smoke test, which calls
run_recommendation_pipeline with no job_id and must not touch any real DB.
"""

from datetime import timedelta
from typing import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.system import RecommendationJob
from app.utils.time import utcnow

# Stage constants, in pipeline order.
STAGE_LOADING_PROFILE = "loading_profile"
STAGE_SYNCING_INSTRUMENTS = "syncing_instruments"
STAGE_MARKET_REGIME = "market_regime"
STAGE_FETCHING_MARKET_DATA = "fetching_market_data"
STAGE_SCREENING = "screening"
STAGE_NEWS_INGESTION = "news_ingestion"
STAGE_KRONOS_FORECAST = "kronos_forecast"
STAGE_PRELIM_SCORING = "preliminary_scoring"
STAGE_PORTFOLIO_OPTIMIZATION = "portfolio_optimization"
STAGE_COUNCIL_SETUP = "council_setup"
STAGE_PLANNER = "planner"
STAGE_COUNCIL_EVALUATION = "council_evaluation"
STAGE_FINALIZING = "finalizing"

# (start_pct, end_pct) per stage -- hand-tuned rough weights, NOT measured.
# The 50-symbol fetch loop and the council loop dominate real wall-clock time
# under live providers, so they get the widest bands.
STAGE_BANDS: dict[str, tuple[float, float]] = {
    STAGE_LOADING_PROFILE: (0, 2),
    STAGE_SYNCING_INSTRUMENTS: (2, 4),
    STAGE_MARKET_REGIME: (4, 6),
    STAGE_FETCHING_MARKET_DATA: (6, 40),
    STAGE_SCREENING: (40, 42),
    STAGE_NEWS_INGESTION: (42, 46),
    STAGE_KRONOS_FORECAST: (46, 65),
    STAGE_PRELIM_SCORING: (65, 67),
    STAGE_PORTFOLIO_OPTIMIZATION: (67, 70),
    STAGE_COUNCIL_SETUP: (70, 71),
    STAGE_PLANNER: (71, 74),
    STAGE_COUNCIL_EVALUATION: (74, 98),
    STAGE_FINALIZING: (98, 100),
}


class JobProgressTracker:
    """Stateless beyond job_id/session_factory -- each set_stage() call opens
    and closes its own short-lived session, so this needs no context-manager
    lifecycle. Just instantiate and call set_stage() directly."""

    def __init__(
        self,
        job_id: UUID | None,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
        worker_token: str | None = None,
    ):
        self.job_id = job_id
        self._session_factory = session_factory
        # Fencing token (docs/V2-RETHINK.md P0): if the job's lease expired
        # and another worker attempt reclaimed it, this attempt's worker_token
        # no longer matches the row -- stop writing progress for an attempt
        # that's already been superseded, rather than corrupting the newer
        # attempt's view of its own progress.
        self._worker_token = worker_token

    async def set_stage(
        self,
        stage: str,
        *,
        current_symbol: str | None = None,
        index: int | None = None,
        total: int | None = None,
    ) -> None:
        if self.job_id is None:
            return
        start, end = STAGE_BANDS[stage]
        if total is not None and index is not None and total > 0:
            pct = start + (end - start) * (index / total)
        else:
            pct = start
        async with self._session_factory() as session:
            job = await session.get(RecommendationJob, self.job_id)
            if job is None:
                return
            if self._worker_token is not None and job.worker_token != self._worker_token:
                # Reclaimed by another attempt -- this run is stale, stop
                # touching the job (Section 50: never let a superseded
                # attempt clobber a newer one's state).
                return
            job.stage = stage
            job.progress_pct = round(pct, 1)
            job.stage_detail = {"current_symbol": current_symbol, "index": index, "total": total}
            job.lease_expires_at = utcnow() + timedelta(seconds=settings.job_lease_seconds)
            await session.commit()
