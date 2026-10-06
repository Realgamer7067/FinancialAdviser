"""Assemble, publish and queue portfolio reviews.

compute_review: read-only; builds the outcome from the CURRENT twin using the
same deterministic modules the owner can open (risk, constraints, goals, the
action lab). publish_review: ONE transaction, fenced on the job's worker token
and on the latest state/valuation, that inserts the immutable outcome and (only
if compatible and not older than the current one) moves the current pointer.
A review that finishes after its inputs were superseded is kept as history,
labelled superseded, and a fresh review is queued."""

import asyncio
import logging
import os
import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.decisions import CurrentDecision, DecisionOutcome
from app.models.accounts import SourceAccount
from app.models.goals_v4 import GoalAllocation
from app.models.portfolio_jobs import PortfolioJob
from app.models.twin import PortfolioState
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence.decisions import engine
from app.portfolio_intelligence.decisions.review import REVIEW_BY_DAYS, REVIEW_VERSION, compose, detect_issues, reduction_amount
from app.portfolio_intelligence.goals.store import latest_allocations
from app.portfolio_intelligence.state.build import latest_state, latest_valuation
from app.utils.time import utcnow

logger = logging.getLogger("review")
POLICY = f"{engine.POLICY_VERSION}|{REVIEW_VERSION}"
_tasks: set = set()


async def compute_review(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    # Imports are local: the API modules import portfolio_intelligence, not the reverse, at import time.
    from app.api.v4.actions import ActionIn, EvaluateIn, evaluate_actions
    from app.api.v4.constraints import risk_constraints
    from app.api.v4.goals import goal_projections
    from app.api.v4.risk import get_risk, twin_positions
    from app.api.v4.state import _state_payload

    state = await latest_state(db, user_id)
    valuation = None if state is None else await latest_valuation(db, state.id)
    if state is None or valuation is None:
        return None
    payload = await _state_payload(db, state, valuation)
    risk = await get_risk(db)
    constraints = await risk_constraints(db)
    projections = await goal_projections(db)
    review_claims = sum(1 for a in await latest_allocations(db, user_id) if a.status == "needs_review")
    reconnect = [a["label"] for a in payload["state"]["accounts"]
                 if (acct := await db.get(SourceAccount, uuid.UUID(a["account_id"]))) is not None and acct.status == "reconnect_required"]
    from app.models.theses import Thesis, ThesisAssessment

    active = {}
    for t in (await db.execute(select(Thesis).where(Thesis.user_id == user_id).order_by(Thesis.chain_id, Thesis.version.desc()))).scalars():
        active.setdefault(t.chain_id, t)
    thesis_updates = []
    for chain, t in active.items():
        if t.status != "active":
            continue
        a = (await db.execute(select(ThesisAssessment).where(ThesisAssessment.thesis_chain_id == chain)
                              .order_by(ThesisAssessment.created_at.desc()).limit(1))).scalar_one_or_none()
        if a is not None and a.review_status == "pending" and a.status != "insufficient":
            thesis_updates.append({"chain": str(chain), "symbol": t.symbol, "status": a.status})
    limits = {k: engine.POLICY[k] for k in ("max_single_issuer_weight", "max_sector_weight", "min_fresh_value_share")}
    issues = detect_issues(readiness=payload["readiness"], risk=risk, constraints=constraints, projections=projections,
                           limits=limits, claims_needing_review=review_claims, reconnect_accounts=reconnect,
                           thesis_updates=thesis_updates)

    alternatives: list[dict] = []
    evaluation_id = None
    preview_error = None
    ic = next((i for i in issues if i["kind"] == "issuer_concentration"), None)
    if ic is not None:
        positions = [p for p in await twin_positions(db, state, valuation)
                     if p["asset_type"] == "listed_equity" and p["label"] == ic["issuer"] and p["value"] is not None]
        if positions:
            group = sum((p["value"] for p in positions), Decimal(0))
            biggest = max(positions, key=lambda p: p["value"])
            amount = reduction_amount(group, Decimal(risk["known_total"]), engine.POLICY["max_single_issuer_weight"], biggest["value"])
            if amount:
                try:
                    ev = await evaluate_actions(EvaluateIn(state_id=state.id, valuation_id=valuation.id, actions=[
                        ActionIn(type="REDUCE_PREVIEW", position_id=biggest["position_id"], amount=amount)]), db)
                    evaluation_id = ev["analysis_id"]
                    alternatives = [{"index": a["index"], "action": a["action"], "status": a["status"], "reasons": a["reasons"]}
                                    for a in ev["alternatives"]]
                except HTTPException as exc:
                    preview_error = str(exc.detail)

    status, headline, explanation = compose(issues, payload["readiness"], alternatives=alternatives)
    now = utcnow()
    bound = payload["state"]["bound_facts"]
    result = {
        "review_version": REVIEW_VERSION, "status": status, "headline": headline, "issues": issues, "explanation": explanation,
        "readiness": payload["readiness"], "headline_label": payload["headline_label"], "known_total": risk["known_total"],
        "alternatives": alternatives, "preview_error": preview_error,
        "evidence": {"risk_analysis_id": risk["analysis_id"], "evaluation_analysis_id": evaluation_id,
                     "state_id": str(state.id), "valuation_id": str(valuation.id)},
        "audit": {"state_version": state.version, "bound_facts": bound, "valuation_cutoff": valuation.cutoff.isoformat(),
                  "policy_versions": {"review": REVIEW_VERSION, "decision": engine.POLICY_VERSION,
                                      "capacity": constraints["policy_version"], "scenarios": "stress-v1"},
                  "code_version": os.getenv("GIT_SHA", "unknown"), "computed_at": now.isoformat(), "uses_llm": False},
        "valid": {"review_by": (now + timedelta(days=REVIEW_BY_DAYS)).isoformat(),
                  "invalidated_by": ["a new portfolio snapshot (holdings, profile, goals or commitments changed)",
                                     "a newer valuation", "the decision policy version changing"]},
    }
    return {"state_id": state.id, "state_version": state.version, "valuation_id": valuation.id, "status": status,
            "headline": headline, "result": result}


async def _lock_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"decision:{user_id}"})


async def enqueue_review(db: AsyncSession, user_id: uuid.UUID, *, key: str | None = None) -> PortfolioJob:
    """At most one live review job per user: reuse a queued/running one (a running review that
    finishes on stale inputs enqueues its own fresh successor)."""
    await _lock_user(db, user_id)
    live = (await db.execute(select(PortfolioJob).where(PortfolioJob.user_id == user_id, PortfolioJob.kind == "review",
                                                        PortfolioJob.status.in_(("queued", "running"))).limit(1))).scalar_one_or_none()
    if live is not None:
        return live
    job = PortfolioJob(user_id=user_id, kind="review", account_id=None, request_key=key or f"review-{uuid.uuid4()}", status="queued",
                       attempts=0, created_at=utcnow())
    db.add(job)
    await db.commit()
    return job


async def publish_review(db: AsyncSession, job_id: uuid.UUID, worker_token: str, computed: dict) -> DecisionOutcome:
    job = (await db.execute(select(PortfolioJob).where(PortfolioJob.id == job_id).with_for_update()
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if job is None or job.worker_token != worker_token or job.status != "running":
        raise StalePublicationError("review attempt no longer owns the job")
    user_id = job.user_id
    await _lock_user(db, user_id)

    # Freshest truth, read inside the publishing transaction.
    cur_state = await latest_state(db, user_id)
    cur_val = None if cur_state is None else await latest_valuation(db, cur_state.id)
    pointer = (await db.execute(select(CurrentDecision).where(CurrentDecision.user_id == user_id).with_for_update()
                                .execution_options(populate_existing=True))).scalar_one_or_none()
    current_outcome = None if pointer is None else await db.get(DecisionOutcome, pointer.outcome_id, populate_existing=True)

    superseded_reason = None
    if cur_state is None or cur_state.id != computed["state_id"]:
        superseded_reason = "inputs changed: a newer portfolio snapshot exists"
    elif cur_val is None or cur_val.id != computed["valuation_id"]:
        superseded_reason = "inputs changed: a newer valuation exists"
    elif current_outcome is not None and current_outcome.state_version > computed["state_version"]:
        superseded_reason = "a decision for a newer snapshot is already current"

    now = utcnow()
    outcome = DecisionOutcome(user_id=user_id, job_id=job.id, state_id=computed["state_id"], state_version=computed["state_version"],
                              valuation_id=computed["valuation_id"], policy_version=POLICY, status=computed["status"],
                              headline=computed["headline"], result=computed["result"], created_at=now,
                              superseded_at=now if superseded_reason else None, superseded_reason=superseded_reason)
    db.add(outcome)
    await db.flush()
    if superseded_reason is None:
        from app.portfolio_intelligence.decisions.inbox import sync_inbox

        await sync_inbox(db, user_id, outcome, now)  # same transaction as the pointer move
        if pointer is None:
            db.add(CurrentDecision(user_id=user_id, outcome_id=outcome.id, updated_at=now))
        else:
            pointer.outcome_id = outcome.id
            pointer.updated_at = now
    job.status = "done"
    job.result_outcome_id = outcome.id
    job.completed_at = now
    if superseded_reason is not None and cur_state is not None:
        # keep history, then queue a fresh review (the running job is still 'running' here, so insert directly)
        db.add(PortfolioJob(user_id=user_id, kind="review", account_id=None, request_key=f"review-{uuid.uuid4()}", status="queued",
                            attempts=0, created_at=now))
    await db.commit()
    return outcome


async def run_queued_reviews() -> int:
    """Inline executor: claim and process queued REVIEW jobs through the same claim/fence path the worker uses."""
    from app.core.db import AsyncSessionLocal
    from app.portfolio_intelligence.jobs import claim_next_portfolio_job, process_portfolio_job

    done = 0
    for _ in range(5):  # bounded: a superseded review queues one successor, never a loop
        async with AsyncSessionLocal() as db:
            job = await claim_next_portfolio_job(db, kinds=("review",))
        if job is None:
            break
        await process_portfolio_job(job.id, job.worker_token)
        done += 1
    return done


def kick_inline_reviews() -> None:
    if not settings.inline_reviews:
        return
    try:
        task = asyncio.get_running_loop().create_task(run_queued_reviews())
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(lambda t: (_tasks.discard(t), t.exception() and logger.error("inline review failed: %s", t.exception())))
