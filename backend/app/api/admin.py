"""Admin/debug API (Section 69) + Upstox OAuth callback (Section 5).

Not protected by auth in this MVP -- these are local-dev developer tools.
Put this behind an admin-only auth check (or off the public network entirely)
before any real deployment; Section 71 treats user financial data as
sensitive and this page can indirectly reveal system/provider state.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.system import DataSource, RecommendationJob
from app.providers.upstox import UpstoxProvider
from app.services.upstox_auth import store_upstox_token

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/upstox/login")
async def upstox_login():
    if not settings.upstox_configured:
        raise HTTPException(status_code=400, detail="UPSTOX_API_KEY/UPSTOX_API_SECRET not set in .env")
    return RedirectResponse(UpstoxProvider.authorization_url())


@router.get("/upstox/callback")
async def upstox_callback(code: str, db: AsyncSession = Depends(get_db)):
    token_payload = await UpstoxProvider.exchange_code_for_token(code)
    access_token = token_payload["access_token"]
    expires_at = UpstoxProvider.next_expiry_ist().astimezone(timezone.utc)
    await store_upstox_token(db, access_token, expires_at)
    await db.commit()
    return {"status": "ok", "expires_at": expires_at.isoformat()}


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
    upstox_configured: bool
    qwen_configured: bool
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
        upstox_configured=settings.upstox_configured,
        qwen_configured=settings.qwen_configured,
        data_sources=[
            DataSourceStatus(
                name=s.name, kind=s.kind, status=s.status, last_synced_at=s.last_synced_at, token_expires_at=s.token_expires_at
            )
            for s in sources
        ],
        recent_jobs=[JobStatus(id=str(j.id), status=j.status, error=j.error, created_at=j.created_at) for j in jobs],
    )
