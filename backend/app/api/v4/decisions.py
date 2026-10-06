"""Current decision, history and review requests (Portfolio Intelligence
Engine Phase 07). `GET /actions/current` returns the published outcome only
while its inputs are still the latest; otherwise it is shown as the last known
outcome with `status: pending_review`, never passed off as current."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.decisions import CurrentDecision, DecisionOutcome
from app.models.portfolio_jobs import PortfolioJob
from app.portfolio_intelligence.decisions.runner import POLICY, enqueue_review, kick_inline_reviews
from app.portfolio_intelligence.state.build import latest_state, latest_valuation
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-decisions"])


def outcome_out(o: DecisionOutcome, *, full: bool = True) -> dict:
    base = {"outcome_id": str(o.id), "status": o.status, "headline": o.headline, "state_id": str(o.state_id),
            "state_version": o.state_version, "valuation_id": str(o.valuation_id), "policy_version": o.policy_version,
            "created_at": o.created_at.isoformat(), "superseded": o.superseded_at is not None,
            "superseded_reason": o.superseded_reason}
    if full:
        base["result"] = o.result
    return base


async def _live_job(db: AsyncSession) -> PortfolioJob | None:
    return (await db.execute(select(PortfolioJob).where(PortfolioJob.user_id == SINGLE_USER_ID, PortfolioJob.kind == "review",
                                                        PortfolioJob.status.in_(("queued", "running")))
                             .order_by(PortfolioJob.created_at.desc()).limit(1))).scalar_one_or_none()


async def current_view(db: AsyncSession) -> dict:
    state = await latest_state(db, SINGLE_USER_ID)
    pointer = (await db.execute(select(CurrentDecision).where(CurrentDecision.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    outcome = None if pointer is None else await db.get(DecisionOutcome, pointer.outcome_id)
    job = await _live_job(db)
    pending = None if job is None else {"job_id": str(job.id), "status": job.status}
    if outcome is None:
        return {"status": "none", "outcome": None, "pending_review": pending,
                "message": "No review yet. Add an account and your financial picture; a review runs automatically."
                           if state is None else "A review is being prepared." if pending else "No review has been published yet."}
    val = await latest_valuation(db, state.id) if state is not None else None
    compatible = state is not None and outcome.state_id == state.id and outcome.policy_version == POLICY
    prev = (await db.execute(select(DecisionOutcome).where(
        DecisionOutcome.user_id == SINGLE_USER_ID, DecisionOutcome.superseded_at.is_(None), DecisionOutcome.created_at < outcome.created_at)
        .order_by(DecisionOutcome.created_at.desc()).limit(1))).scalar_one_or_none()
    now_fps = {i.get("fingerprint") or i["kind"] for i in outcome.result.get("issues", [])}
    prev_fps = {i.get("fingerprint") or i["kind"] for i in prev.result.get("issues", [])} if prev else set()
    since = {"previous_outcome_id": None if prev is None else str(prev.id),
             "nothing_material_changed": prev is not None and prev.status == outcome.status and now_fps == prev_fps,
             "new_issues": sorted(now_fps - prev_fps), "resolved_issues": sorted(prev_fps - now_fps)}
    review_by = outcome.result.get("valid", {}).get("review_by")
    overdue = bool(review_by) and utcnow() > datetime.fromisoformat(review_by)
    return {
        "status": "current" if compatible and not overdue else "pending_review",
        "outcome": outcome_out(outcome),
        "valuation_newer": bool(compatible and val is not None and val.id != outcome.valuation_id),
        "review_overdue": overdue,
        "since_previous": since,
        "pending_review": pending,
        "message": None if compatible and not overdue else
                   ("Your snapshot changed since this review; a new review is pending." if not compatible else "This review is older than 7 days."),
    }


@router.get("/actions/current")
async def get_current(db: AsyncSession = Depends(get_db)):
    return await current_view(db)


@router.get("/actions/{outcome_id}")
async def get_outcome(outcome_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    o = (await db.execute(select(DecisionOutcome).where(DecisionOutcome.id == outcome_id, DecisionOutcome.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if o is None:
        raise HTTPException(404, "decision not found")
    return outcome_out(o)


@router.get("/timeline")
async def timeline(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DecisionOutcome).where(DecisionOutcome.user_id == SINGLE_USER_ID)
                             .order_by(DecisionOutcome.created_at.desc()).limit(50))).scalars().all()
    pointer = (await db.execute(select(CurrentDecision).where(CurrentDecision.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    return [{**outcome_out(o, full=False), "is_current": pointer is not None and pointer.outcome_id == o.id} for o in rows]


class ReviewIn(BaseModel):
    force: bool = False


@router.post("/reviews", status_code=202)
async def request_review(payload: ReviewIn | None = None, db: AsyncSession = Depends(get_db)):
    """Queue a review of the latest snapshot (idempotent: at most one live review job). If the
    current decision already covers the latest snapshot and valuation, say so instead of repeating it."""
    state = await latest_state(db, SINGLE_USER_ID)
    if state is None:
        raise HTTPException(409, "no portfolio snapshot yet; add an account and import holdings first")
    view = await current_view(db)
    val = await latest_valuation(db, state.id)
    if (not (payload and payload.force) and view["status"] == "current" and not view["valuation_newer"] and val is not None
            and view["outcome"]["valuation_id"] == str(val.id)):
        return {"already_current": True, "current": view}
    job = await enqueue_review(db, SINGLE_USER_ID)
    kick_inline_reviews()
    return {"already_current": False, "job_id": str(job.id), "status": job.status}
