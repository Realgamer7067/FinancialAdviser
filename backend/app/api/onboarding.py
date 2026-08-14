"""Onboarding API (Section 2). Structured forms only -- computes the risk
profile deterministically (app/risk/scoring.py); the raw questionnaire answers
are stored separately from the derived profile, never overwritten by Qwen."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import RiskProfile, User, UserProfile
from app.risk.scoring import compute_risk_profile
from app.schemas.onboarding import OnboardingRequest, RiskProfileResponse

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.post("", response_model=RiskProfileResponse, status_code=201)
async def submit_onboarding(
    payload: OnboardingRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        scored = compute_risk_profile(payload.raw_risk_answers, payload.investment_horizon_years)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prior_count = (
        await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    ).scalars().all()

    profile = UserProfile(
        user_id=user.id,
        version=len(prior_count) + 1,
        age=payload.age,
        employment_status=payload.employment_status,
        monthly_income_range=payload.monthly_income_range,
        monthly_investable_amount=payload.monthly_investable_amount,
        total_initial_investment=payload.total_initial_investment,
        existing_investments=payload.existing_investments,
        existing_debt=payload.existing_debt,
        emergency_fund_status=payload.emergency_fund_status,
        dependents=payload.dependents,
        investment_objective=payload.investment_objective,
        investment_horizon_years=payload.investment_horizon_years,
        liquidity_requirement=payload.liquidity_requirement,
        investment_frequency=payload.investment_frequency,
        raw_risk_answers=dict(payload.raw_risk_answers),
    )
    db.add(profile)
    await db.flush()

    risk_profile = RiskProfile(
        user_profile_id=profile.id,
        risk_score=scored["risk_score"],
        risk_profile=scored["risk_profile"],
        investment_horizon_years=payload.investment_horizon_years,
        capital=payload.total_initial_investment,
        monthly_contribution=payload.monthly_investable_amount,
        objective=payload.investment_objective,
        liquidity_requirement=payload.liquidity_requirement,
    )
    db.add(risk_profile)
    await db.commit()

    return RiskProfileResponse(
        risk_score=risk_profile.risk_score,
        risk_profile=risk_profile.risk_profile,
        investment_horizon_years=risk_profile.investment_horizon_years,
        capital=risk_profile.capital,
        monthly_contribution=risk_profile.monthly_contribution,
        objective=risk_profile.objective,
        liquidity_requirement=risk_profile.liquidity_requirement,
    )


@router.get("/me", response_model=RiskProfileResponse)
async def get_my_risk_profile(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    profile = (
        await db.execute(
            select(UserProfile).where(UserProfile.user_id == user.id).order_by(UserProfile.created_at.desc())
        )
    ).scalars().first()
    if profile is None:
        raise HTTPException(status_code=404, detail="No onboarding profile yet")

    risk_profile = (
        await db.execute(
            select(RiskProfile).where(RiskProfile.user_profile_id == profile.id).order_by(RiskProfile.created_at.desc())
        )
    ).scalars().first()
    if risk_profile is None:
        raise HTTPException(status_code=404, detail="No risk profile computed yet")

    return RiskProfileResponse(
        risk_score=risk_profile.risk_score,
        risk_profile=risk_profile.risk_profile,
        investment_horizon_years=risk_profile.investment_horizon_years,
        capital=risk_profile.capital,
        monthly_contribution=risk_profile.monthly_contribution,
        objective=risk_profile.objective,
        liquidity_requirement=risk_profile.liquidity_requirement,
    )
