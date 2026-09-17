"""Job API (Section 70). The frontend never waits synchronously on the
council/pipeline -- it enqueues a job and polls status."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.system import RecommendationJob
from app.utils.time import utcnow

router = APIRouter(prefix="/api/recommendations/jobs", tags=["jobs"])


class JobStatusResponse(BaseModel):
    id: UUID
    status: str
    stage: str | None
    progress_pct: float | None
    stage_detail: dict | None
    error: str | None
    result_council_run_id: UUID | None


def _to_response(job: RecommendationJob) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        status=job.status,
        stage=job.stage,
        progress_pct=job.progress_pct,
        stage_detail=job.stage_detail,
        error=job.error,
        result_council_run_id=job.result_council_run_id,
    )


@router.post("", status_code=202, response_model=JobStatusResponse)
async def create_job(db: AsyncSession = Depends(get_db)):
    job = RecommendationJob(user_id=SINGLE_USER_ID, status="queued", created_at=utcnow())
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(RecommendationJob, job_id)
    if job is None or job.user_id != SINGLE_USER_ID:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)
