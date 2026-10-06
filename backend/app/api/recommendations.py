"""Recommendation read API (Sections 16/44). Renders the persisted, auditable
council output -- the frontend never talks to Qwen directly (Section 3)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilOutput, CouncilRun
from app.models.market import Instrument
from app.models.recommendation import Recommendation
from app.schemas.recommendation import CouncilRoleOutput, CouncilRunSummary, RecommendationCard

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


async def _build_summary(db: AsyncSession, council_run: CouncilRun) -> CouncilRunSummary:
    rows = (
        await db.execute(
            select(Recommendation, Instrument)
            .join(Instrument, Recommendation.instrument_id == Instrument.id)
            .where(Recommendation.council_run_id == council_run.id)
            .order_by(Recommendation.score.desc())
        )
    ).all()

    # One extra query for all roles across all candidates in this run, grouped
    # in Python by instrument_id -- council_outputs was always persisted, just
    # never read by any endpoint before Phase 0B #1.
    outputs_by_instrument: dict = {}
    if rows:
        output_rows = (
            await db.execute(
                select(CouncilOutput).where(
                    CouncilOutput.council_run_id == council_run.id,
                    CouncilOutput.instrument_id.in_([instrument.id for _, instrument in rows]),
                )
            )
        ).scalars().all()
        for out in output_rows:
            outputs_by_instrument.setdefault(out.instrument_id, []).append(
                CouncilRoleOutput(
                    role=out.role,
                    content=out.content,
                    model_name=out.model_name,
                    model_version=out.model_version,
                    prompt_version=out.prompt_version,
                    created_at=out.created_at,
                )
            )

    cards = [
        RecommendationCard(
            id=rec.id,
            symbol=instrument.symbol,
            name=instrument.name,
            recommendation=rec.recommendation,
            confidence=rec.confidence,
            confidence_band=rec.confidence_band,
            score=rec.score,
            risk_level=rec.risk_level,
            risk_tier=rec.risk_tier,
            risk_tier_score=rec.risk_tier_score,
            risk_tier_breakdown=rec.risk_tier_breakdown,
            suggested_horizon=rec.suggested_horizon,
            strengths=rec.strengths,
            risks=rec.risks,
            rationale=rec.rationale,
            evidence=rec.evidence,
            fundamental_score=rec.fundamental_score,
            technical_score=rec.technical_score,
            kronos_score=rec.kronos_score,
            news_score=rec.news_score,
            portfolio_score=rec.portfolio_score,
            risk_score=rec.risk_score,
            model_agreement=rec.model_agreement,
            data_quality=rec.data_quality,
            generated_at=rec.generated_at,
            council_outputs=outputs_by_instrument.get(instrument.id, []),
        )
        for rec, instrument in rows
    ]
    return CouncilRunSummary(
        id=council_run.id,
        status=council_run.status,
        market_regime=council_run.market_regime,
        universe_size=council_run.universe_size,
        candidates_after_screen=council_run.candidates_after_screen,
        candidates_after_kronos_news=council_run.candidates_after_kronos_news,
        candidates_to_council=council_run.candidates_to_council,
        plan=council_run.plan,
        started_at=council_run.started_at,
        completed_at=council_run.completed_at,
        recommendations=cards,
    )


@router.get("/latest", response_model=CouncilRunSummary)
async def latest_recommendations(db: AsyncSession = Depends(get_db)):
    # Must be the newest COMPLETED run, full stop -- never skip past it just
    # because it happened to produce zero recommendation rows (a legitimate
    # "no opportunity" outcome, Section 20). Filtering runs by "has at least
    # one Recommendation row" silently served an older, stale run instead and
    # let a user mistake a past opportunity for the current one
    # (docs/V2-RETHINK.md P0). "running"/"failed" runs are excluded here --
    # they're surfaced through job status, not as a stale prior result.
    council_run = (
        await db.execute(
            select(CouncilRun)
            .where(CouncilRun.user_id == SINGLE_USER_ID, CouncilRun.status == "done")
            .order_by(CouncilRun.completed_at.desc())
        )
    ).scalars().first()
    if council_run is None:
        raise HTTPException(status_code=404, detail="No recommendation runs yet -- trigger analysis first")
    return await _build_summary(db, council_run)


@router.get("/{council_run_id}", response_model=CouncilRunSummary)
async def get_recommendations(council_run_id: UUID, db: AsyncSession = Depends(get_db)):
    council_run = await db.get(CouncilRun, council_run_id)
    if council_run is None or council_run.user_id != SINGLE_USER_ID:
        raise HTTPException(status_code=404, detail="Recommendation run not found")
    return await _build_summary(db, council_run)
