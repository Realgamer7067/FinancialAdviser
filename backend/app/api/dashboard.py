"""Dashboard API (Section 55): answers "how's the market", "what fits me",
"what risks should I know" in one call."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.council import CouncilRun
from app.models.recommendation import Recommendation
from app.models.user import RiskProfile, User, UserProfile
from app.providers.factory import get_market_data_provider

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardOut(BaseModel):
    market_status: str
    nifty_price: float | None
    nifty_is_stale: bool
    has_profile: bool
    risk_profile: str | None
    latest_run_status: str | None
    top_recommendation_count: int
    strong_or_candidate_count: int


@router.get("", response_model=DashboardOut)
async def get_dashboard(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    provider = await get_market_data_provider(db)
    try:
        status = await provider.get_market_status("NSE")
        market_status = status.status
    except Exception:
        market_status = "UNKNOWN"

    nifty_price = None
    nifty_is_stale = True
    try:
        indices = await provider.get_market_indices()
        if indices:
            nifty_price = indices[0].price
            nifty_is_stale = indices[0].is_stale
    except Exception:
        pass

    profile = (
        await db.execute(
            select(UserProfile).where(UserProfile.user_id == user.id).order_by(UserProfile.created_at.desc())
        )
    ).scalars().first()

    risk_label = None
    if profile:
        risk = (
            await db.execute(
                select(RiskProfile).where(RiskProfile.user_profile_id == profile.id).order_by(RiskProfile.created_at.desc())
            )
        ).scalars().first()
        risk_label = risk.risk_profile if risk else None

    latest_run = (
        await db.execute(select(CouncilRun).where(CouncilRun.user_id == user.id).order_by(CouncilRun.started_at.desc()))
    ).scalars().first()

    top_count = 0
    strong_or_candidate = 0
    if latest_run:
        recs = (
            await db.execute(select(Recommendation).where(Recommendation.council_run_id == latest_run.id))
        ).scalars().all()
        top_count = len(recs)
        strong_or_candidate = sum(1 for r in recs if r.recommendation in ("STRONG_CANDIDATE", "CANDIDATE"))

    return DashboardOut(
        market_status=market_status,
        nifty_price=nifty_price,
        nifty_is_stale=nifty_is_stale,
        has_profile=profile is not None,
        risk_profile=risk_label,
        latest_run_status=latest_run.status if latest_run else None,
        top_recommendation_count=top_count,
        strong_or_candidate_count=strong_or_candidate,
    )
