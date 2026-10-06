"""Goals, allocation claims, commitments and projections (Portfolio
Intelligence Engine Phase 04b). Goals/commitments are revision chains; claims
are on account-specific holdings and are re-checked, never silently dropped.
Legacy /api/goals, /api/commitments are untouched."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.goals_v4 import CommitmentRevision, GoalAllocation, GoalRevision
from app.portfolio_intelligence.goals.projection import project_goal
from app.portfolio_intelligence.goals.service import (
    _new_revision, claimed_total, current_holding_values, lock_holding, monthly_equivalent,
)
from app.portfolio_intelligence.goals.store import latest_allocations, latest_commitments, latest_goals
from app.portfolio_intelligence.state.build import safe_refresh
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-goals"])


def _s(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")


# --- goals -----------------------------------------------------------------------


class GoalBody(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    target_amount: Decimal
    target_basis: Literal["today_money", "future_money"]
    target_date: date
    priority: int = Field(ge=1, le=100)
    flexibility: Literal["fixed", "flexible"] = "flexible"
    inflation_assumption: Decimal | None = None  # fraction, 0.06 = 6%

    @field_validator("target_amount")
    @classmethod
    def _amt(cls, v):
        if not v.is_finite() or v <= 0:
            raise ValueError("target_amount must be positive")
        return v

    @field_validator("inflation_assumption")
    @classmethod
    def _inf(cls, v):
        if v is not None and (not v.is_finite() or v < 0 or v > 1):
            raise ValueError("inflation_assumption is a fraction between 0 and 1")
        return v


class GoalUpdate(GoalBody):
    expected_version: int
    status: Literal["active", "closed"] = "active"


def goal_out(g: GoalRevision, allocs: list[GoalAllocation]) -> dict:
    mine = [a for a in allocs if a.goal_chain_id == g.chain_id]
    return {
        "chain_id": str(g.chain_id), "version": g.version, "description": g.description,
        "target_amount": _s(g.target_amount), "target_basis": g.target_basis, "target_date": g.target_date.isoformat(),
        "priority": g.priority, "flexibility": g.flexibility, "inflation_assumption": _s(g.inflation_assumption),
        "status": g.status,
        "allocated_total": _s(sum((a.amount for a in mine if a.status == "active"), Decimal(0))),
        "needs_review_total": _s(sum((a.amount for a in mine if a.status == "needs_review"), Decimal(0))),
        "allocations": [alloc_out(a) for a in mine],
    }


def alloc_out(a: GoalAllocation) -> dict:
    return {"chain_id": str(a.chain_id), "version": a.version, "goal_chain_id": str(a.goal_chain_id),
            "account_id": str(a.source_account_id), "holding": a.holding_label, "amount": _s(a.amount),
            "status": a.status, "reason": a.reason}


@router.get("/goals")
async def list_goals(db: AsyncSession = Depends(get_db)):
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    return [goal_out(g, allocs) for g in sorted(await latest_goals(db, SINGLE_USER_ID), key=lambda g: (g.priority, str(g.chain_id)))]


@router.post("/goals", status_code=201)
async def create_goal(payload: GoalBody, db: AsyncSession = Depends(get_db)):
    g = GoalRevision(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, status="active", created_at=utcnow(),
                     **payload.model_dump())
    db.add(g)
    await db.commit()
    out = goal_out(g, [])
    await safe_refresh(db, SINGLE_USER_ID)
    return out


@router.put("/goals/{chain_id}")
async def edit_goal(chain_id: uuid.UUID, payload: GoalUpdate, db: AsyncSession = Depends(get_db)):
    latest = (await db.execute(select(GoalRevision).where(GoalRevision.chain_id == chain_id, GoalRevision.user_id == SINGLE_USER_ID)
                               .order_by(GoalRevision.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(404, "goal not found")
    if payload.expected_version != latest.version:
        raise HTTPException(409, f"stale version: goal is at version {latest.version}")
    g = GoalRevision(user_id=SINGLE_USER_ID, chain_id=chain_id, version=latest.version + 1, created_at=utcnow(),
                     **payload.model_dump(exclude={"expected_version"}))
    db.add(g)
    if payload.status == "closed":  # closing is explicit: claims are released as auditable revisions
        for a in await latest_allocations(db, SINGLE_USER_ID):
            if a.goal_chain_id == chain_id:
                db.add(_new_revision(a, status="released", reason="goal_closed"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "goal changed concurrently; reload and retry")
    out = goal_out(g, await latest_allocations(db, SINGLE_USER_ID))
    await safe_refresh(db, SINGLE_USER_ID)  # claims stay with the goal chain; they are re-checked, not copied
    return out


# --- allocation claims -------------------------------------------------------------


class AllocationCreate(BaseModel):
    position_id: uuid.UUID  # a position in the CURRENT snapshot (see /state/current)
    amount: Decimal
    expected_goal_version: int  # the goal revision the user was looking at

    @field_validator("amount")
    @classmethod
    def _a(cls, v):
        if not v.is_finite() or v <= 0:
            raise ValueError("amount must be positive")
        return v


async def _goal_or_404(db: AsyncSession, chain_id: uuid.UUID) -> GoalRevision:
    g = next((x for x in await latest_goals(db, SINGLE_USER_ID) if x.chain_id == chain_id), None)
    if g is None:
        raise HTTPException(404, "active goal not found")
    return g


@router.post("/goals/{chain_id}/allocations", status_code=201)
async def claim_holding(chain_id: uuid.UUID, payload: AllocationCreate, db: AsyncSession = Depends(get_db)):
    goal = await _goal_or_404(db, chain_id)
    if payload.expected_goal_version != goal.version:
        raise HTTPException(409, f"stale version: goal is at version {goal.version}; reload before claiming")
    values = await current_holding_values(db, SINGLE_USER_ID)
    info = next((h for h in values.values() if str(payload.position_id) in h.position_ids), None)
    if info is None:
        raise HTTPException(422, "that position is not in the current snapshot")
    if info.value is None:
        raise HTTPException(422, "that holding has no known value, so a claim on it cannot be verified")
    await lock_holding(db, info.key)
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    if any(a.goal_chain_id == chain_id and a.holding_key == info.key for a in allocs):
        raise HTTPException(409, "this goal already claims that holding; resize or release the existing claim")
    already = claimed_total(allocs, info.key)
    if already + payload.amount > info.value:
        raise HTTPException(422, {"message": "claim exceeds what is still unclaimed on this holding",
                                  "holding_value": _s(info.value), "already_claimed": _s(already),
                                  "unclaimed": _s(info.value - already)})
    a = GoalAllocation(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, goal_chain_id=chain_id,
                       source_account_id=info.account_id, holding_key=info.key,
                       holding_label=f"{info.label} ({info.account_label})", amount=payload.amount,
                       status="active", reason=None, created_at=utcnow())
    db.add(a)
    await db.commit()
    out = alloc_out(a)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


class AllocationAction(BaseModel):
    expected_version: int
    action: Literal["confirm", "release", "resize"]
    amount: Decimal | None = None


@router.put("/goal-allocations/{chain_id}")
async def act_on_allocation(chain_id: uuid.UUID, payload: AllocationAction, db: AsyncSession = Depends(get_db)):
    allocs = await latest_allocations(db, SINGLE_USER_ID, include_released=True)
    cur = next((a for a in allocs if a.chain_id == chain_id), None)
    if cur is None:
        raise HTTPException(404, "allocation not found")
    if payload.expected_version != cur.version:
        raise HTTPException(409, f"stale version: allocation is at version {cur.version}")
    if cur.status == "released":
        raise HTTPException(422, "this claim is already released")
    if payload.action == "release":
        new = _new_revision(cur, status="released", reason="released_by_user")
    else:
        amount = cur.amount
        if payload.action == "resize":
            if cur.status != "active":
                raise HTTPException(422, "confirm or release a claim that needs review before resizing it")
            if payload.amount is None or not payload.amount.is_finite() or payload.amount <= 0:
                raise HTTPException(422, "resize needs a positive amount")
            amount = payload.amount
        elif cur.status != "needs_review":
            raise HTTPException(422, "only a claim that needs review can be confirmed")
        info = (await current_holding_values(db, SINGLE_USER_ID)).get(cur.holding_key)
        if info is None or info.value is None:
            raise HTTPException(422, "the holding is not in the current snapshot with a known value; it cannot be confirmed")
        await lock_holding(db, cur.holding_key)
        others = claimed_total(await latest_allocations(db, SINGLE_USER_ID), cur.holding_key, exclude_chain=cur.chain_id)
        if others + amount > info.value:
            raise HTTPException(422, {"message": "claim would exceed the holding's value",
                                      "holding_value": _s(info.value), "claimed_by_others": _s(others)})
        new = _new_revision(cur, status="active", reason=None, amount=amount)
    db.add(new)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "allocation changed concurrently; reload and retry")
    out = alloc_out(new)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


@router.get("/allocations/summary")
async def allocation_summary(db: AsyncSession = Depends(get_db)):
    """Per holding: value, claimed (active + needs_review reserve), unclaimed. This
    is what any future purchase may use; claimed rupees are not deployable."""
    values = await current_holding_values(db, SINGLE_USER_ID)
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    out = []
    for h in values.values():
        claimed = claimed_total(allocs, h.key)
        out.append({"account": h.account_label, "holding": h.label, "asset_type": h.asset_type,
                    "position_ids": h.position_ids, "value": _s(h.value), "claimed": _s(claimed),
                    "unclaimed": None if h.value is None else _s(max(h.value - claimed, Decimal(0)))})
    return sorted(out, key=lambda r: (r["account"], r["holding"]))


# --- commitments --------------------------------------------------------------------


class CommitmentBody(BaseModel):
    goal_chain_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=120)
    amount: Decimal
    frequency: Literal["monthly", "quarterly", "annual"]
    start_date: date
    end_date: date | None = None
    source: Literal["existing_user_reported", "proposed"]
    budget_interpretation: Literal["includes_existing_commitments", "additional_to_existing_commitments"]

    @field_validator("amount")
    @classmethod
    def _a(cls, v):
        if not v.is_finite() or v <= 0:
            raise ValueError("amount must be positive")
        return v

    @model_validator(mode="after")
    def _d(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class CommitmentUpdate(CommitmentBody):
    expected_version: int
    status: Literal["active", "paused", "ended"] = "active"


def commitment_out(c: CommitmentRevision) -> dict:
    return {"chain_id": str(c.chain_id), "version": c.version,
            "goal_chain_id": None if c.goal_chain_id is None else str(c.goal_chain_id), "description": c.description,
            "amount": _s(c.amount), "frequency": c.frequency, "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat() if c.end_date else None, "status": c.status, "source": c.source,
            "budget_interpretation": c.budget_interpretation,
            "monthly_equivalent": _s(monthly_equivalent(c.amount, c.frequency).quantize(Decimal("0.01")))}


@router.get("/commitments")
async def list_commitments(db: AsyncSession = Depends(get_db)):
    return [commitment_out(c) for c in await latest_commitments(db, SINGLE_USER_ID)]


async def _check_goal(db: AsyncSession, goal_chain_id: uuid.UUID | None):
    if goal_chain_id is not None:
        await _goal_or_404(db, goal_chain_id)


@router.post("/commitments", status_code=201)
async def create_commitment(payload: CommitmentBody, db: AsyncSession = Depends(get_db)):
    await _check_goal(db, payload.goal_chain_id)
    for c in await latest_commitments(db, SINGLE_USER_ID):
        if (c.status == "active" and c.goal_chain_id == payload.goal_chain_id and c.description.strip().lower() == payload.description.strip().lower()
                and c.amount == payload.amount and c.frequency == payload.frequency):
            raise HTTPException(409, "an identical active contribution stream already exists; edit it instead of adding a duplicate")
    c = CommitmentRevision(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, status="active", created_at=utcnow(),
                           **payload.model_dump())
    db.add(c)
    await db.commit()
    out = commitment_out(c)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


@router.put("/commitments/{chain_id}")
async def edit_commitment(chain_id: uuid.UUID, payload: CommitmentUpdate, db: AsyncSession = Depends(get_db)):
    latest = (await db.execute(select(CommitmentRevision).where(CommitmentRevision.chain_id == chain_id, CommitmentRevision.user_id == SINGLE_USER_ID)
                               .order_by(CommitmentRevision.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        raise HTTPException(404, "commitment not found")
    if payload.expected_version != latest.version:
        raise HTTPException(409, f"stale version: commitment is at version {latest.version}")
    if latest.status == "ended":
        raise HTTPException(422, "an ended commitment cannot be edited; create a new one")
    await _check_goal(db, payload.goal_chain_id)
    c = CommitmentRevision(user_id=SINGLE_USER_ID, chain_id=chain_id, version=latest.version + 1, created_at=utcnow(),
                           **payload.model_dump(exclude={"expected_version"}))
    db.add(c)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "commitment changed concurrently; reload and retry")
    out = commitment_out(c)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


# --- projections ----------------------------------------------------------------------


@router.get("/goals/projections")
async def goal_projections(db: AsyncSession = Depends(get_db)):
    today = date.today()
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    commitments = await latest_commitments(db, SINGLE_USER_ID)
    out = []
    for g in sorted(await latest_goals(db, SINGLE_USER_ID), key=lambda g: (g.priority, str(g.chain_id))):
        mine = [a for a in allocs if a.goal_chain_id == g.chain_id]
        review = [a for a in mine if a.status == "needs_review"]
        starting = sum((a.amount for a in mine if a.status == "active"), Decimal(0))
        linked = [c for c in commitments if c.goal_chain_id == g.chain_id]
        counted = [c for c in linked if c.status == "active" and c.source == "existing_user_reported"
                   and c.start_date <= today and (c.end_date is None or c.end_date >= today)]
        monthly = sum((monthly_equivalent(c.amount, c.frequency) for c in counted), Decimal(0))
        row = {"goal_chain_id": str(g.chain_id), "description": g.description, "target_amount": _s(g.target_amount),
               "target_basis": g.target_basis, "target_date": g.target_date.isoformat(),
               "starting_value": _s(starting), "monthly_contribution_counted": _s(monthly.quantize(Decimal("0.01"))),
               "excluded_contributions": [commitment_out(c) for c in linked if c not in counted],
               "limitations": ["step-ups ignored", "fees and taxes excluded", "proposed or not-yet-started contributions excluded",
                               "end-of-month contributions, effective annual rates"]}
        if review:
            row.update(status="blocked_needs_review",
                       message=f"{len(review)} claim(s) on this goal need review; the projection is suppressed until you confirm or release them",
                       needs_review=[alloc_out(a) for a in review])
        else:
            row.update(project_goal(target_amount=g.target_amount, target_basis=g.target_basis, target_date=g.target_date,
                                    inflation=g.inflation_assumption, starting_value=starting, monthly_contribution=monthly, today=today))
        out.append(row)
    return out
