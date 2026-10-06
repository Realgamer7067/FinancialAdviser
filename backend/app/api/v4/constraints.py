"""Effective risk constraints and monthly budget (Portfolio Intelligence
Engine Phase 04). Read-only derived views over the user's confirmed facts;
Phase 06's action gates consume `/risk-constraints` and `/budget`."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.personal import profile_view
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.portfolio_intelligence.goals.service import monthly_equivalent
from app.portfolio_intelligence.goals.store import latest_allocations, latest_commitments, latest_goals
from app.portfolio_intelligence.personal.constraints import compute_effective_constraints, short_horizon_funds
from app.portfolio_intelligence.state.build import active_liabilities, active_preferences, latest_profile

router = APIRouter(prefix="/api/v4", tags=["v4-constraints"])


def _f(d: Decimal) -> str:
    return format(d.normalize(), "f")


@router.get("/risk-constraints")
async def risk_constraints(db: AsyncSession = Depends(get_db)):
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    goals = [{"chain_id": g.chain_id, "description": g.description, "target_date": g.target_date}
             for g in await latest_goals(db, SINGLE_USER_ID)]
    allocs = [{"goal_chain_id": a.goal_chain_id, "amount": a.amount, "status": a.status}
              for a in await latest_allocations(db, SINGLE_USER_ID)]
    restrictions = [{"kind": p.kind, "value": p.value, "expires_on": p.expires_on.isoformat() if p.expires_on else None}
                    for p in await active_preferences(db, SINGLE_USER_ID)]
    out = compute_effective_constraints(tolerance=pv["tolerance"], capacity=pv["capacity"],
                                        short_horizon=short_horizon_funds(goals, allocs), restrictions=restrictions)
    out["profile_version"] = pv["version"]
    return out


@router.get("/budget")
async def budget(db: AsyncSession = Depends(get_db)):
    """How much monthly money is left for NEW investing, using each running
    contribution's stated `budget_interpretation`:
    - includes_existing_commitments: already part of the amount you said you can invest, so it is deducted from it;
    - additional_to_existing_commitments: paid on top, not deducted, but checked against income left after essentials.
    Proposed, paused, ended and not-yet-started streams are listed, never counted."""
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    stated = pv["capacity"]["stated_investable_surplus"]
    computed = pv["capacity"]["computed_monthly_surplus"]
    today = date.today()
    counted_in, counted_on_top, excluded = Decimal(0), Decimal(0), []
    for c in await latest_commitments(db, SINGLE_USER_ID):
        live = (c.status == "active" and c.source == "existing_user_reported" and c.start_date <= today
                and (c.end_date is None or c.end_date >= today))
        m = monthly_equivalent(c.amount, c.frequency)
        if not live:
            excluded.append({"chain_id": str(c.chain_id), "description": c.description, "monthly_equivalent": _f(m.quantize(Decimal("0.01"))),
                             "status": c.status, "source": c.source})
        elif c.budget_interpretation == "includes_existing_commitments":
            counted_in += m
        else:
            counted_on_top += m
    out: dict = {"monthly_committed_included_in_surplus": _f(counted_in.quantize(Decimal("0.01"))),
                 "monthly_committed_on_top_of_surplus": _f(counted_on_top.quantize(Decimal("0.01"))),
                 "excluded_streams": excluded, "stated_investable_surplus": stated, "computed_monthly_surplus": computed}
    if stated is None:
        out.update(remaining_for_new_monthly=None, status="unknown", missing=["monthly_investable_surplus"])
        return out
    remaining = Decimal(stated) - counted_in
    out["remaining_for_new_monthly"] = _f(max(remaining, Decimal(0)))
    out["over_committed"] = remaining < 0
    out["status"] = "known"
    if computed is not None:
        out["exceeds_income_after_essentials"] = Decimal(stated) + counted_on_top > Decimal(computed)
    else:
        out["exceeds_income_after_essentials"] = None
    return out
