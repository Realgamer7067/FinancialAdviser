"""SIP growth projection + goal-based SIP back-calculation. Pure stateless
math over already-persisted profile/portfolio data -- same idiom as
POST /api/portfolio/allocate. Never presents an assumed return rate as fact
without flagging it (see `assumed_return` on both responses), mirroring
app/education/safer_alternatives.py's "qualitative, never a fake precise
number" convention."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation
from app.models.user import RiskProfile, UserProfile
from app.services.financial_planning import required_monthly_sip, sip_future_value

router = APIRouter(prefix="/api/planning", tags=["planning"])

# Labeled fallback only -- used when no portfolio result exists yet to derive
# a real expected_return from. Never presented as a guarantee.
FALLBACK_ANNUAL_RATE_PCT = 11.0


class SipProjectionPoint(BaseModel):
    year: int
    invested_cumulative: float
    projected_value: float


class SipProjectionOut(BaseModel):
    monthly_amount: float
    years: int
    annual_rate_pct: float
    assumed_return: bool
    points: list[SipProjectionPoint]


class GoalSipRequest(BaseModel):
    target_amount: float = Field(gt=0)
    years: int = Field(gt=0)
    annual_rate_pct: float | None = None


class GoalSipOut(BaseModel):
    target_amount: float
    years: int
    annual_rate_pct: float
    assumed_return: bool
    required_monthly_sip: float


async def _latest_risk_profile(db: AsyncSession) -> RiskProfile | None:
    profile = (
        await db.execute(
            select(UserProfile).where(UserProfile.user_id == SINGLE_USER_ID).order_by(UserProfile.created_at.desc())
        )
    ).scalars().first()
    if profile is None:
        return None
    return (
        await db.execute(
            select(RiskProfile).where(RiskProfile.user_profile_id == profile.id).order_by(RiskProfile.created_at.desc())
        )
    ).scalars().first()


async def _latest_expected_return_pct(db: AsyncSession) -> float | None:
    row = (
        await db.execute(
            select(PortfolioResult)
            .join(PortfolioRecommendation, PortfolioRecommendation.portfolio_result_id == PortfolioResult.id)
            .where(PortfolioRecommendation.user_id == SINGLE_USER_ID)
            .order_by(PortfolioRecommendation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.expected_return is None:
        return None
    return row.expected_return * 100


async def _resolve_rate(db: AsyncSession, annual_rate_pct: float | None) -> tuple[float, bool]:
    """Returns (rate, assumed_return). assumed_return is only True when
    falling back to the generic labeled constant, not when using the user's
    own portfolio's expected_return or an explicit override."""
    if annual_rate_pct is not None:
        return annual_rate_pct, False
    from_portfolio = await _latest_expected_return_pct(db)
    if from_portfolio is not None:
        return from_portfolio, False
    return FALLBACK_ANNUAL_RATE_PCT, True


@router.get("/sip-projection", response_model=SipProjectionOut)
async def sip_projection(
    monthly_amount: float | None = None,
    years: int | None = None,
    annual_rate_pct: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    if monthly_amount is None or years is None:
        risk_profile = await _latest_risk_profile(db)
        if risk_profile is None:
            raise HTTPException(
                status_code=404,
                detail="No onboarding profile yet -- complete onboarding, or pass monthly_amount and years explicitly",
            )
        monthly_amount = monthly_amount if monthly_amount is not None else risk_profile.monthly_contribution
        years = years if years is not None else risk_profile.investment_horizon_years

    if monthly_amount <= 0 or years <= 0:
        raise HTTPException(status_code=422, detail="monthly_amount and years must be positive")

    rate, assumed = await _resolve_rate(db, annual_rate_pct)
    points = sip_future_value(monthly_amount, rate, years)
    return SipProjectionOut(
        monthly_amount=monthly_amount, years=years, annual_rate_pct=rate, assumed_return=assumed, points=points
    )


@router.post("/goal-sip", response_model=GoalSipOut)
async def goal_sip(payload: GoalSipRequest, db: AsyncSession = Depends(get_db)):
    rate, assumed = await _resolve_rate(db, payload.annual_rate_pct)
    required = required_monthly_sip(payload.target_amount, rate, payload.years)
    return GoalSipOut(
        target_amount=payload.target_amount,
        years=payload.years,
        annual_rate_pct=rate,
        assumed_return=assumed,
        required_monthly_sip=required,
    )
