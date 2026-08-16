"""Admin/debug API (Section 69).

Not protected by auth in this MVP -- these are local-dev developer tools.
Put this behind an admin-only auth check (or off the public network entirely)
before any real deployment; Section 71 treats user financial data as
sensitive and this page can indirectly reveal system/provider state.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.system import DataSource, RecommendationJob
from app.models_iface.portfolio_finrl import FinRLDRLPortfolioModel

router = APIRouter(prefix="/admin", tags=["admin"])


class DataSourceStatus(BaseModel):
    name: str
    kind: str
    status: str
    last_synced_at: datetime | None
    token_expires_at: datetime | None


class JobStatus(BaseModel):
    id: str
    status: str
    error: str | None
    created_at: datetime


class DebugOut(BaseModel):
    demo_mode: bool
    qwen_configured: bool
    # FinRL is never used to drive live recommendations (mean-variance is)
    # -- this just reports whether scripts/train_finrl_agent.py has been run.
    # Any output from it is lightly-trained/not-validated (Section 74).
    finrl_checkpoint_trained: bool
    data_sources: list[DataSourceStatus]
    recent_jobs: list[JobStatus]


@router.get("/debug", response_model=DebugOut)
async def debug(db: AsyncSession = Depends(get_db)):
    sources = (await db.execute(select(DataSource))).scalars().all()
    jobs = (
        await db.execute(select(RecommendationJob).order_by(RecommendationJob.created_at.desc()).limit(20))
    ).scalars().all()
    return DebugOut(
        demo_mode=settings.demo_mode,
        qwen_configured=settings.qwen_configured,
        finrl_checkpoint_trained=FinRLDRLPortfolioModel.is_trained(),
        data_sources=[
            DataSourceStatus(
                name=s.name, kind=s.kind, status=s.status, last_synced_at=s.last_synced_at, token_expires_at=s.token_expires_at
            )
            for s in sources
        ],
        recent_jobs=[JobStatus(id=str(j.id), status=j.status, error=j.error, created_at=j.created_at) for j in jobs],
    )
