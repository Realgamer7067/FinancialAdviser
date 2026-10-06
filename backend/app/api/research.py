"""Research session API (V3 Phase 08, light backend wiring for Phase 07's
service-layer logic -- `app/services/research_orchestrator.py`).

Updated 2026-09-16 now that a real Gemini key exists: POST now (1) auto
-discovers source URLs via Gemini search grounding for any branch the
caller left empty (`app/services/web_search.py` -- degrades to nothing
found on the known search-quota wall, never blocks the session), then (2)
after reaching `ready_to_publish`, makes one real synthesis call
(`synthesize_and_publish`) to turn verified evidence into an actual
`CompanyAssessment` report and publish it. A session can still legitimately
land at `ready_to_publish` with `report: null` if synthesis fails (model
call failed, or literally zero facts passed verification) -- that is a
disclosed missing signal (`synthesis_error` explains why), never a crash
and never a fabricated report.

Two endpoints, both synchronous (no background job for this pass -- V3
Phase 08 task explicitly keeps this simple/fast):
- POST /api/research/sessions: runs a full session end to end, commits, returns it.
- GET /api/research/sessions/{id}: re-queries ResearchSession/ResearchBranch/ResearchReport directly.

Note on GET's shape vs POST's: `verification` (the claim-ledger tally) and
`contradictions` are NOT persisted anywhere by the orchestrator/workflow
models -- they only exist as the in-memory `OrchestrationResult` returned
from the synchronous run. So GET always returns `verification: null` and
`contradictions: []`; only `named_gaps` (persisted on ResearchSession),
branch status/gap_reason (persisted on ResearchBranch), and the published
`report` (persisted on ResearchReport, if synthesis succeeded) survive a
re-query.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.research import ResearchBranch, ResearchSession
from app.models.research_report import ResearchReport
from app.services.research_orchestrator import OrchestrationResult, run_research_session, synthesize_and_publish
from app.services.retrieval import FetchPolicy
from app.services.web_search import discover_branch_urls

router = APIRouter(prefix="/api/research", tags=["research"])

# Real network fetches, same shape used by the orchestrator's own test --
# generous but bounded limits for a synchronous request/response cycle.
_DEFAULT_RETRIEVAL_POLICY = FetchPolicy(
    allowed_hosts=None,
    max_bytes=2_000_000,
    max_pages=None,
    timeout_seconds=10,
    max_redirects=3,
)


class ResearchSessionCreate(BaseModel):
    question: str
    instrument_ids: list[str] = Field(default_factory=list)
    # {branch_type: [urls]} -- explicit URLs always take priority. Any of
    # the 3 standard branches the caller leaves empty gets auto-discovered
    # URLs via Gemini search grounding instead, when find_sources is true.
    branch_fetch_urls: dict[str, list[str]] = Field(default_factory=dict)
    find_sources: bool = True
    budget_envelope: dict = Field(default_factory=lambda: {"max_fetches": 10})
    cutoff_policy: dict = Field(default_factory=dict)


class BranchOut(BaseModel):
    id: UUID
    branch_type: str
    status: str
    gap_reason: str | None
    fact_ids: list

    model_config = {"from_attributes": True}


class VerificationOut(BaseModel):
    total_material_claims: int
    supported_count: int
    unsupported_count: int
    unknown_count: int
    contradicted_count: int
    unresolved_critical_claim_ids: list[str]
    fully_verifiable: bool  # internal-consistency check only -- see ReportVerificationSummary.fully_verifiable docstring; not an independent-corroboration or factuality score


class ResearchSessionOut(BaseModel):
    id: UUID
    state: str
    question: str
    named_gaps: list[str]
    branches: list[BranchOut]
    verification: VerificationOut | None
    contradictions: list[dict]
    stopped_reason: str | None
    report: dict | None = None  # CompanyAssessment content, only present once state == "published"
    synthesis_error: str | None = None  # why synthesis didn't run/succeed, when report is null


def _to_out(
    result: OrchestrationResult, *, report: dict | None = None, synthesis_error: str | None = None
) -> ResearchSessionOut:
    verification = None
    if result.verification is not None:
        v = result.verification
        verification = VerificationOut(
            total_material_claims=v.total_material_claims,
            supported_count=v.supported_count,
            unsupported_count=v.unsupported_count,
            unknown_count=v.unknown_count,
            contradicted_count=v.contradicted_count,
            unresolved_critical_claim_ids=v.unresolved_critical_claim_ids,
            fully_verifiable=v.fully_verifiable,
        )
    return ResearchSessionOut(
        id=result.session.id,
        state=result.session.state,
        question=result.session.question,
        named_gaps=result.named_gaps,
        branches=[BranchOut.model_validate(b) for b in result.branches],
        verification=verification,
        contradictions=result.contradictions,
        stopped_reason=result.stopped_reason,
        report=report,
        synthesis_error=synthesis_error,
    )


_STANDARD_BRANCHES = ("financials_valuation", "events_governance", "peers_downside")


@router.post("/sessions", response_model=ResearchSessionOut, status_code=201)
async def create_research_session(
    payload: ResearchSessionCreate, db: AsyncSession = Depends(get_db)
) -> ResearchSessionOut:
    branch_fetch_urls = dict(payload.branch_fetch_urls)
    if payload.find_sources:
        for branch_type in _STANDARD_BRANCHES:
            if branch_fetch_urls.get(branch_type):
                continue  # explicit URLs always win over auto-discovery
            discovered = await discover_branch_urls(payload.question, branch_type)
            if discovered:
                branch_fetch_urls[branch_type] = discovered

    result = await run_research_session(
        db,
        user_id=SINGLE_USER_ID,
        question=payload.question,
        instrument_ids=payload.instrument_ids,
        cutoff_policy=payload.cutoff_policy,
        budget_envelope=payload.budget_envelope,
        branch_fetch_urls=branch_fetch_urls,
        retrieval_policy=_DEFAULT_RETRIEVAL_POLICY,
    )
    # Persist what previously existed only in this synchronous response, so a later GET can restore it.
    v = result.verification
    result.session.verification = None if v is None else {
        "total_material_claims": v.total_material_claims, "supported_count": v.supported_count, "unsupported_count": v.unsupported_count,
        "unknown_count": v.unknown_count, "contradicted_count": v.contradicted_count,
        "unresolved_critical_claim_ids": v.unresolved_critical_claim_ids, "fully_verifiable": v.fully_verifiable}
    result.session.contradictions = result.contradictions
    await db.commit()

    report_content: dict | None = None
    synthesis_error: str | None = None
    if result.session.state == "ready_to_publish":
        synth = await synthesize_and_publish(db, result.session.id)
        if synth.report is not None:
            report_content = synth.report.content
            result.session = synth.session
        else:
            synthesis_error = synth.error

    return _to_out(result, report=report_content, synthesis_error=synthesis_error)


@router.get("/sessions/{session_id}", response_model=ResearchSessionOut)
async def get_research_session(session_id: UUID, db: AsyncSession = Depends(get_db)) -> ResearchSessionOut:
    session = await db.get(ResearchSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="research session not found")

    branches = list(
        (
            await db.execute(select(ResearchBranch).where(ResearchBranch.session_id == session_id))
        )
        .scalars()
        .all()
    )

    report_content: dict | None = None
    if session.state == "published":
        report = (
            await db.execute(
                select(ResearchReport)
                .where(ResearchReport.session_id == session_id)
                .order_by(ResearchReport.published_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if report is not None:
            report_content = report.content

    return ResearchSessionOut(
        id=session.id,
        state=session.state,
        question=session.question,
        named_gaps=session.named_gaps or [],
        branches=[BranchOut.model_validate(b) for b in branches],
        verification=VerificationOut(**session.verification) if session.verification else None,
        contradictions=session.contradictions or [],
        stopped_reason=session.budget_exhausted_reason,
        report=report_content,
    )
