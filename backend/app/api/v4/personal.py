"""Personal financial facts API (Portfolio Intelligence Engine Phase 04a):
versioned profile, dated liabilities and confirmed preferences. Every write
creates a NEW immutable revision (expected-version conflicts are 409) and then
refreshes the Portfolio Twin, because a profile edit creates a new state even
when holdings are unchanged. Nothing here is inferred from holdings."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.personal import FinancialProfileRevision, LiabilityRevision, PreferenceRevision
from app.portfolio_intelligence.personal.facts import (
    FinancialFacts, compute_capacity, compute_tolerance, missing_fields,
)
from app.portfolio_intelligence.state.build import (
    active_liabilities, active_preferences, latest_profile, safe_refresh,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-personal"])


def profile_view(rev: FinancialProfileRevision | None, liabilities: list[LiabilityRevision]) -> dict:
    facts = rev.facts if rev else FinancialFacts().model_dump(mode="json")
    liab = [{"monthly_payment": l.monthly_payment, "rate_type": l.rate_type, "next_reset_date": l.next_reset_date}
            for l in liabilities]
    return {
        "version": rev.version if rev else 0,
        "created_at": rev.created_at.isoformat() if rev else None,
        "facts": facts,
        "missing_fields": missing_fields(facts),
        "tolerance": compute_tolerance(facts.get("tolerance_answers")),
        "capacity": compute_capacity(facts, liab),
    }


class ProfileIn(BaseModel):
    expected_version: int
    facts: FinancialFacts


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)):
    return profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))


@router.put("/profile")
async def put_profile(payload: ProfileIn, db: AsyncSession = Depends(get_db)):
    current = await latest_profile(db, SINGLE_USER_ID)
    cur_version = current.version if current else 0
    if payload.expected_version != cur_version:
        raise HTTPException(409, f"stale version: profile is at version {cur_version}")
    rev = FinancialProfileRevision(user_id=SINGLE_USER_ID, version=cur_version + 1,
                                   facts=payload.facts.model_dump(mode="json"), created_at=utcnow())
    db.add(rev)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "profile changed concurrently; reload and retry")
    out = profile_view(rev, await active_liabilities(db, SINGLE_USER_ID))
    await safe_refresh(db, SINGLE_USER_ID)
    return out


# --- liabilities ---------------------------------------------------------------

LiabilityKind = Literal["home_loan", "personal_loan", "credit_card", "education_loan", "vehicle_loan", "other"]


class LiabilityBody(BaseModel):
    kind: LiabilityKind
    outstanding_amount: Decimal
    as_of: date
    monthly_payment: Decimal | None = None
    rate_type: Literal["fixed", "floating", "unknown"] = "unknown"
    annual_rate: Decimal | None = None  # fraction: 0.09 = 9%
    next_reset_date: date | None = None
    maturity_date: date | None = None

    @field_validator("outstanding_amount")
    @classmethod
    def _out(cls, v):
        if not v.is_finite() or v <= 0:
            raise ValueError("outstanding_amount must be a positive amount (liabilities are not negative holdings)")
        return v

    @field_validator("monthly_payment")
    @classmethod
    def _pay(cls, v):
        if v is not None and (not v.is_finite() or v < 0):
            raise ValueError("monthly_payment must be non-negative")
        return v

    @field_validator("annual_rate")
    @classmethod
    def _rate(cls, v):
        if v is not None and (not v.is_finite() or v < 0 or v > 1):
            raise ValueError("annual_rate is a fraction between 0 and 1 (0.09 = 9%)")
        return v

    @model_validator(mode="after")
    def _dates(self):
        if self.maturity_date and self.maturity_date < self.as_of:
            raise ValueError("maturity_date is before as_of")
        return self


class LiabilityUpdate(LiabilityBody):
    expected_version: int
    status: Literal["active", "closed"] = "active"


def liability_out(l: LiabilityRevision) -> dict:
    return {
        "chain_id": str(l.chain_id), "revision_id": str(l.id), "version": l.version, "kind": l.kind,
        "outstanding_amount": str(l.outstanding_amount), "as_of": l.as_of.isoformat(),
        "monthly_payment": None if l.monthly_payment is None else str(l.monthly_payment),
        "rate_type": l.rate_type, "annual_rate": None if l.annual_rate is None else str(l.annual_rate),
        "next_reset_date": l.next_reset_date.isoformat() if l.next_reset_date else None,
        "maturity_date": l.maturity_date.isoformat() if l.maturity_date else None,
        "status": l.status,
        # A floating rate without a known reset date cannot be shocked: flagged, never assumed 0.
        "rate_sensitivity_known": not (l.rate_type == "floating" and l.next_reset_date is None) and l.rate_type != "unknown",
    }


@router.get("/liabilities")
async def list_liabilities(db: AsyncSession = Depends(get_db)):
    return [liability_out(l) for l in await active_liabilities(db, SINGLE_USER_ID)]


@router.post("/liabilities", status_code=201)
async def create_liability(payload: LiabilityBody, db: AsyncSession = Depends(get_db)):
    rev = LiabilityRevision(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, status="active",
                            created_at=utcnow(), **payload.model_dump())
    db.add(rev)
    await db.commit()
    out = liability_out(rev)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


@router.put("/liabilities/{chain_id}")
async def update_liability(chain_id: uuid.UUID, payload: LiabilityUpdate, db: AsyncSession = Depends(get_db)):
    latest = (await db.execute(select(LiabilityRevision).where(
        LiabilityRevision.chain_id == chain_id, LiabilityRevision.user_id == SINGLE_USER_ID)
        .order_by(LiabilityRevision.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(404, "liability not found")
    if payload.expected_version != latest.version:
        raise HTTPException(409, f"stale version: liability is at version {latest.version}")
    data = payload.model_dump(exclude={"expected_version"})
    rev = LiabilityRevision(user_id=SINGLE_USER_ID, chain_id=chain_id, version=latest.version + 1,
                            created_at=utcnow(), **data)
    db.add(rev)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "liability changed concurrently; reload and retry")
    out = liability_out(rev)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


# --- preferences ---------------------------------------------------------------


class PreferenceBody(BaseModel):
    kind: Literal["exclude_sector", "exclude_asset_type", "exclude_isin"]
    value: str = Field(min_length=1, max_length=80)
    expires_on: date | None = None
    confirmed: bool = False


class PreferenceUpdate(BaseModel):
    expected_version: int
    status: Literal["revoked"]


def preference_out(p: PreferenceRevision) -> dict:
    return {"chain_id": str(p.chain_id), "revision_id": str(p.id), "version": p.version, "kind": p.kind,
            "value": p.value, "expires_on": p.expires_on.isoformat() if p.expires_on else None,
            "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}


@router.get("/preferences")
async def list_preferences(db: AsyncSession = Depends(get_db)):
    return [preference_out(p) for p in await active_preferences(db, SINGLE_USER_ID)]


@router.post("/preferences", status_code=201)
async def create_preference(payload: PreferenceBody, db: AsyncSession = Depends(get_db)):
    if not payload.confirmed:
        raise HTTPException(422, "restrictions need explicit confirmation (confirmed=true); they are never inferred")
    rev = PreferenceRevision(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, kind=payload.kind,
                             value=payload.value.strip(), expires_on=payload.expires_on, status="active",
                             confirmed_at=utcnow())
    db.add(rev)
    await db.commit()
    out = preference_out(rev)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


@router.put("/preferences/{chain_id}")
async def revoke_preference(chain_id: uuid.UUID, payload: PreferenceUpdate, db: AsyncSession = Depends(get_db)):
    latest = (await db.execute(select(PreferenceRevision).where(
        PreferenceRevision.chain_id == chain_id, PreferenceRevision.user_id == SINGLE_USER_ID)
        .order_by(PreferenceRevision.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(404, "preference not found")
    if payload.expected_version != latest.version:
        raise HTTPException(409, f"stale version: preference is at version {latest.version}")
    rev = PreferenceRevision(user_id=SINGLE_USER_ID, chain_id=chain_id, version=latest.version + 1, kind=latest.kind,
                             value=latest.value, expires_on=latest.expires_on, status="revoked", confirmed_at=utcnow())
    db.add(rev)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "preference changed concurrently; reload and retry")
    out = preference_out(rev)
    await safe_refresh(db, SINGLE_USER_ID)
    return out
