"""End-to-end research orchestration glue (V3 Phase 07 integration).

Ties together, in one real call, the pieces Phase 07's three workers built
in isolation: session/checklist/branches (research_workflow.py),
contradiction detection, verification (research_verification.py), and
publication/reuse (research_reuse.py). No piece here reimplements logic
those modules already own -- this module is composition only.

`run_research_session` makes NO model call -- it gets a session all the way
to `ready_to_publish` with real, verified evidence, deterministically.
`synthesize_and_publish` (added 2026-09-16, now that a real Gemini key
exists) is the separate function that DOES make one live model call,
turning verified evidence into `CompanyAssessment` prose and publishing it.
Kept as a second function rather than folded into `run_research_session` so
the deterministic retrieval/verification path stays testable and usable
with no model configured at all -- exactly the "deterministic code over LLM
reasoning" split this whole codebase follows everywhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.council.research_prompts import PROMPT_VERSION, SYNTHESIS_PROMPT_V1
from app.models.evidence import Fact
from app.models.research import ResearchBranch, ResearchSession
from app.models.research_report import ResearchReport
from app.models_iface.llm import QwenOpenAICompatibleProvider, StructuredOutputError
from app.schemas.research_assessment import CompanyAssessment
from app.services.research_reuse import compute_artifact_key, publish_report
from app.services.research_verification import ReportVerificationSummary, verify_report_claims
from app.services.research_workflow import (
    BudgetExhausted,
    InvalidStateTransition,
    cancel_session,
    check_material_contradiction,
    create_session,
    run_branch,
    run_standard_checklist,
    transition,
)
from app.utils.time import utcnow

RESEARCH_POLICY_VERSION = "v1"  # bump if the synthesis prompt/evidence-selection rules change materially


@dataclass
class OrchestrationResult:
    session: ResearchSession
    branches: list[ResearchBranch]
    contradictions: list[dict]
    verification: ReportVerificationSummary | None
    named_gaps: list[str] = field(default_factory=list)
    stopped_reason: str | None = None  # None if reached ready_to_publish cleanly


async def run_research_session(
    db: AsyncSession,
    *,
    user_id,
    question: str,
    instrument_ids: list,
    cutoff_policy: dict,
    budget_envelope: dict,
    branch_fetch_urls: dict[str, list[str]],
    retrieval_policy,
    resolver=None,
    mode: str = "standard",
    parent_session_id=None,
) -> OrchestrationResult:
    """Runs a STANDARD-mode session start to finish, through real branch
    fetches and real fact verification, stopping at `ready_to_publish`
    (never `published` -- that requires synthesized `content`, a model
    call this module doesn't make).

    `branch_fetch_urls`: {branch_type: [urls]} -- the caller supplies which
    URLs each of the 3 deterministic branches should fetch (this module
    doesn't invent search results; V3 9.3's actual search/entity-resolution
    tools are a later integration, not built here).

    Deep mode (2 follow-up rounds instead of 1) is out of scope for this
    pass -- `mode="deep"` is accepted and stored on the session but this
    function's contradiction-follow-up behavior does not yet differ by
    mode (see Return notes in the calling report for this gap).

    Session-state safety (a gap Phase 07's Workflow worker explicitly
    flagged: `run_branch` itself doesn't check session state): THIS
    function is the caller that checks state before every dispatch, so a
    concurrently-cancelled session stops being worked on as soon as this
    function next checks -- it is not a perfect mid-branch abort (a branch
    already in flight when cancellation lands still finishes that one
    fetch), but no NEW branch or fetch starts after cancellation is
    observed.
    """
    session = await create_session(
        db,
        user_id=user_id,
        question=question,
        instrument_ids=instrument_ids,
        mode=mode,
        cutoff_policy=cutoff_policy,
        budget_envelope=budget_envelope,
        parent_session_id=parent_session_id,
    )

    async def _still_active() -> ResearchSession:
        current = await db.get(ResearchSession, session.id)
        if current.state == "cancelled":
            raise InvalidStateTransition(f"research session {session.id} was cancelled mid-run")
        return current

    try:
        await transition(db, session.id, "resolving")
        await _still_active()

        branches = await run_standard_checklist(db, session.id)

        await transition(db, session.id, "retrieving")
        for branch in branches:
            await _still_active()
            urls = branch_fetch_urls.get(branch.branch_type, [])
            try:
                await run_branch(
                    db, branch.id, fetch_urls=urls, retrieval_policy=retrieval_policy, resolver=resolver
                )
            except BudgetExhausted as exc:
                session = await db.get(ResearchSession, session.id)
                session.budget_exhausted_reason = str(exc)
                await db.flush()
                # Budget exhaustion stops further branch dispatch entirely
                # (not just the current branch) -- V3 9.2: "Stop when...
                # any budget/deadline expires."
                break

        refreshed_branches = list(
            (await db.execute(_branches_query(session.id))).scalars().all()
        )

        await transition(db, session.id, "calculating")
        # No new calculations are derived here (that's a synthesis-time
        # concern, out of this module's scope per its own docstring) --
        # this state transition exists so the session's state accurately
        # reflects V3 9.2's sequence even though this pass has nothing
        # extra to compute beyond what run_branch already registered as facts.

        await transition(db, session.id, "synthesizing")
        # Real synthesis (prose generation from facts) needs a live model
        # call -- not made here. The session sits in this state until a
        # caller with a ModelAdapter finishes the job.

        await transition(db, session.id, "verifying")
        all_fact_ids = [fid for b in refreshed_branches for fid in (b.fact_ids or [])]
        contradictions = await check_material_contradiction(db, session.id)
        verification = (
            await verify_report_claims(db, all_fact_ids) if all_fact_ids else None
        )

        named_gaps = [b.gap_reason for b in refreshed_branches if b.gap_reason]
        session = await db.get(ResearchSession, session.id)
        session.named_gaps = named_gaps
        await db.flush()

        await transition(db, session.id, "ready_to_publish")
        session = await db.get(ResearchSession, session.id)

        return OrchestrationResult(
            session=session,
            branches=refreshed_branches,
            contradictions=contradictions,
            verification=verification,
            named_gaps=named_gaps,
            stopped_reason=session.budget_exhausted_reason,
        )
    except InvalidStateTransition as exc:
        # Cancellation observed mid-run, or a concurrent state change --
        # never force a transition past what actually happened.
        session = await db.get(ResearchSession, session.id)
        refreshed_branches = list(
            (await db.execute(_branches_query(session.id))).scalars().all()
        )
        return OrchestrationResult(
            session=session,
            branches=refreshed_branches,
            contradictions=[],
            verification=None,
            named_gaps=session.named_gaps or [],
            stopped_reason=str(exc),
        )


def _branches_query(session_id):
    return select(ResearchBranch).where(ResearchBranch.session_id == session_id)


@dataclass
class SynthesisResult:
    report: ResearchReport | None
    session: ResearchSession
    error: str | None = None  # None on success; a missing-signal reason otherwise, never a fabricated report


async def synthesize_and_publish(
    db: AsyncSession,
    session_id,
    *,
    llm=None,
) -> SynthesisResult:
    """Turns a session's `ready_to_publish` verified evidence into a real
    `CompanyAssessment` via one live structured-output model call, then
    publishes it (`ResearchSession.state` -> "published").

    Only facts that are ALREADY `support_status == "supported"` (persisted
    by `evidence_ledger.verify_fact`, called during `run_branch`) are handed
    to the model as citable evidence -- an unsupported/unknown/contradicted
    fact never reaches the prompt, so the model cannot cite something the
    deterministic ledger didn't actually verify. `SYNTHESIS_PROMPT_V1`
    additionally instructs the model never to cite a fact_id it wasn't
    given, but that instruction is a second layer, not the only guard.

    Returns `SynthesisResult(report=None, error=...)` on any failure
    (session not ready, no supported evidence, model call/parse failure) --
    never raises past this function and never fabricates a report from a
    failed call (Section 50/V3 9.4: a failed model call is a missing
    signal, not a crash, and never a fabricated result)."""
    session = await db.get(ResearchSession, session_id)
    if session is None:
        return SynthesisResult(report=None, session=None, error=f"no research session {session_id!r}")
    if session.state != "ready_to_publish":
        return SynthesisResult(
            report=None, session=session, error=f"session is {session.state!r}, not ready_to_publish -- cannot synthesize"
        )

    branches = list((await db.execute(_branches_query(session.id))).scalars().all())
    all_fact_ids = [fid for b in branches for fid in (b.fact_ids or [])]
    if not all_fact_ids:
        return SynthesisResult(report=None, session=session, error="no evidence was retrieved for this session")

    facts = list(
        (await db.execute(select(Fact).where(Fact.id.in_([uuid.UUID(str(f)) for f in all_fact_ids]))))
        .scalars()
        .all()
    )
    supported_facts = [f for f in facts if f.support_status == "supported"]
    if not supported_facts:
        return SynthesisResult(
            report=None,
            session=session,
            error=f"{len(facts)} fact(s) retrieved but none passed verification (supported) -- nothing citable to synthesize from",
        )

    provider = llm or QwenOpenAICompatibleProvider()
    payload = {
        "question": session.question,
        "facts": [
            {
                "fact_id": str(f.id),
                "text": f.text,
                "entity": f.entity,
                "period": f.period,
                "units": f.units,
                "value": f.value,
            }
            for f in supported_facts
        ],
    }
    try:
        assessment, meta = await provider.complete_structured(
            SYNTHESIS_PROMPT_V1, payload, CompanyAssessment, PROMPT_VERSION
        )
    except StructuredOutputError as exc:
        return SynthesisResult(report=None, session=session, error=f"synthesis model call failed: {exc}")

    entity = supported_facts[0].entity
    cutoff_date = str(session.cutoff_policy.get("cutoff_date") or utcnow().date())
    artifact_key = compute_artifact_key(
        entity=entity,
        question_scope=session.question,
        cutoff_date=cutoff_date,
        prompt_version=PROMPT_VERSION,
        model_version=meta.get("model_version", "unknown"),
        research_policy_version=RESEARCH_POLICY_VERSION,
    )
    generated_at = utcnow().isoformat()
    manifest_snapshot = {
        "fact_ids": [str(f.id) for f in supported_facts],
        "model_name": meta.get("model_name"),
        "model_version": meta.get("model_version"),
        "synthesized_at": generated_at,
    }
    # `manifest_version`/`generated_at` are real deterministic values this
    # code owns -- overriding whatever the model wrote for them rather than
    # trusting a model-invented version string or timestamp, same reasoning
    # as every other "never let the model invent what we can supply"
    # boundary in this codebase (Section 8/50).
    assessment = assessment.model_copy(update={"manifest_version": artifact_key, "generated_at": generated_at})
    report = await publish_report(
        db,
        session_id=session.id,
        content=assessment.model_dump(),
        artifact_key=artifact_key,
        manifest_snapshot=manifest_snapshot,
    )
    await transition(db, session.id, "published")
    await db.commit()
    session = await db.get(ResearchSession, session.id)
    return SynthesisResult(report=report, session=session, error=None)
