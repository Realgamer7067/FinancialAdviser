"""Publication ownership guard (docs/v3-execution/CONTRACTS.md C2).

The gap this closes: before this module existed, only the job ROW's own
terminal write (`worker._mark_done`/`_mark_terminal`) was fenced by
`worker_token`. The pipeline's actual publication -- `council_run.status =
"done"` plus every `Recommendation`/`PortfolioRecommendation` row -- happened
inside `run_recommendation_pipeline` and committed unconditionally. A worker
whose lease expired mid-run and was reclaimed by a newer attempt could still
finish its own pipeline run and publish real rows; only the job row's status
update would then fail to land, while the council run and recommendations it
produced were already live and visible through every "latest" endpoint.

`verify_ownership` performs a single atomic conditional UPDATE (`UPDATE ...
SET lease_expires_at = :renewed WHERE id = :job_id AND worker_token =
:token`) and checks the affected row count -- a single UPDATE statement has
no client-side read-then-write gap regardless of backend, so this closes the
"read-compare-unconditional-write" class of race even before a real
PostgreSQL interleaving proof exists (recorded as blocked in CONTRACTS.md
C6). It does NOT commit -- callers must run it inside the same transaction as
the publication writes it guards, so a failed check and a successful publish
can never both land.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system import RecommendationJob
from app.utils.time import utcnow


class StalePublicationError(Exception):
    """Raised when a job's worker_token no longer matches at the moment of
    publication -- this attempt has been superseded by a newer one and MUST
    NOT publish. Not a pipeline failure; the caller should treat this as
    "dropped, someone else owns this job now," not as a job failure to record."""


async def verify_ownership(db: AsyncSession, job_id: UUID | None, worker_token: str | None) -> None:
    """Call immediately before any publication write (council_run.status =
    'done', Recommendation rows, PortfolioRecommendation rows), inside the
    SAME transaction that will commit them. Raises StalePublicationError
    instead of returning False so a caller can't accidentally ignore the
    result -- the guard aborts the publish itself, it isn't a value to
    optionally check.

    No-op (always succeeds) when job_id/worker_token are None -- the
    unfenced manual-trigger and smoke-test paths that don't go through the
    worker's atomic claim at all (job_id=None) have no ownership concept to
    violate."""
    if job_id is None or worker_token is None:
        return
    result = await db.execute(
        update(RecommendationJob)
        .where(RecommendationJob.id == job_id, RecommendationJob.worker_token == worker_token)
        .values(lease_expires_at=utcnow() + timedelta(seconds=settings.job_lease_seconds))
    )
    if result.rowcount == 0:
        raise StalePublicationError(
            f"job {job_id}: worker_token no longer matches at publication time -- "
            "reclaimed by another attempt, refusing to publish"
        )
