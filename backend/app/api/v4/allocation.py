"""Allocation plans (Portfolio Intelligence Engine P3): a proposal for how to put NEW money to work, from fixed rules.

Buy-only, never a sale; every leg is gated by the same engine as the action lab; each plan is saved immutably (the same
inputs make one record). Nothing here places an order: the owner executes by hand in Angel One."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.securities import AllocationPlan
from app.portfolio_intelligence.allocation import policy as P
from app.portfolio_intelligence.allocation.service import generate_plan

router = APIRouter(prefix="/api/v4/allocation", tags=["v4-allocation"])


class PlanIn(BaseModel):
    new_money: Decimal = Decimal(0)
    what_if_band: Literal["conservative", "moderate", "aggressive"] | None = None

    @field_validator("new_money")
    @classmethod
    def _m(cls, v):
        if not v.is_finite() or v < 0 or v > Decimal("100000000"):
            raise ValueError("must be between 0 and 10 crore")
        return v


def _payload(row: AllocationPlan, created: bool | None = None) -> dict:
    out = {"plan_id": str(row.id), "created_at": row.created_at.isoformat(), "policy_version": row.policy_version, "engine_version": row.engine_version,
           "params": row.params, "prices_pinned": row.prices, **row.result}
    if created is not None:
        out["created"] = created
    return out


@router.get("/stock-scores")
async def stock_scores(db: AsyncSession = Depends(get_db)):
    """The scored Nifty 50 table on its own, so it can be read without building a plan. Scores are stored point-in-time (insert-only)."""
    from app.portfolio_intelligence.allocation.select import select_candidates
    from app.portfolio_intelligence.allocation.service import stock_screen
    from app.portfolio_intelligence.scoring.service import current_scores
    from app.portfolio_intelligence.sources.angel.token_store import IST
    from app.utils.time import utcnow

    now = utcnow()
    scores = await current_scores(db, now=now)
    candidates = await select_candidates(db, now.astimezone(IST).date(), scores)
    return stock_screen(scores, candidates, [], in_plan=False)


@router.get("/stock-ranking")
async def stock_ranking(db: AsyncSession = Depends(get_db)):
    """The value / quality / momentum ranking of the Nifty 50 on its own (no plan), with the same explanations a plan shows. Stored point-in-time (insert-only)."""
    from app.api.v4.risk import twin_positions
    from app.portfolio_intelligence.allocation.overlap import exposure as holdings_exposure
    from app.portfolio_intelligence.allocation.select import select_candidates
    from app.portfolio_intelligence.allocation.service import _holdings_inputs, stock_ranking_block
    from app.portfolio_intelligence.scoring.service import current_ranking
    from app.portfolio_intelligence.sources.angel.token_store import IST
    from app.utils.time import utcnow

    now = utcnow()
    ranking = await current_ranking(db, now=now)
    _state, valuation, positions, _labels = await _holdings_inputs(db)
    total = sum((p["value"] for p in positions if p.get("value") is not None), Decimal(0))
    held = await holdings_exposure(db, positions, ranking["rows"], total if total > 0 else Decimal(1)) if positions else {}
    candidates = await select_candidates(db, now.astimezone(IST).date(), ranking=ranking, exposure=held)
    return stock_ranking_block(ranking, candidates, {"legs": []}, held, Decimal(0), in_plan=False)


@router.get("/policy")
async def policy():
    return P.declared()


@router.post("/plan")
async def make_plan(body: PlanIn, db: AsyncSession = Depends(get_db)):
    try:
        row, created = await generate_plan(db, new_money=body.new_money, what_if_band=body.what_if_band)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _payload(row, created)


@router.get("/plans")
async def plans(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AllocationPlan).where(AllocationPlan.user_id == SINGLE_USER_ID).order_by(AllocationPlan.created_at.desc()).limit(30))).scalars().all()
    return [{"plan_id": str(r.id), "created_at": r.created_at.isoformat(), "new_money": str(r.new_money), "what_if_band": r.what_if_band, "status": r.status,
             "legs": len(r.result.get("legs", []))} for r in rows]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(AllocationPlan).where(AllocationPlan.id == plan_id, AllocationPlan.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "plan not found")
    return _payload(row)
