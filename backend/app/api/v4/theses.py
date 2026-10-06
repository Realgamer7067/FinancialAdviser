"""Theses and evidence-backed assessments (Portfolio Intelligence Engine Phase 09).

A thesis is the owner's own confirmed reason + falsifiable conditions for a
holding (or a seriously considered stock). Evidence never edits it: a refresh
produces a ThesisAssessment, a qualitative PROPOSAL (supported / mixed /
weakened / insufficient) with the sources, lineage and verification behind it,
which the owner reviews. A price move is recorded as a price event and never
changes a thesis' status. No numeric conviction score exists, and a thesis
never overrides a portfolio decision or suitability gate."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.risk import twin_positions
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument, MarketCandle
from app.models.research import ResearchSession
from app.models.theses import Thesis, ThesisAssessment, ThesisEvent
from app.portfolio_intelligence.research import thesis as logic
from app.portfolio_intelligence.research.independence import fact_provenance
from app.portfolio_intelligence.research.researcher import ThesisResearcher, get_thesis_researcher
from app.portfolio_intelligence.state.build import latest_state, latest_valuation
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-theses"])

MAX_CONDITIONS = 8
PRICE_MOVE_5D = 0.08
PRICE_MOVE_20D = 0.15


class ConditionIn(BaseModel):
    text: str = Field(min_length=5, max_length=300)
    kind: Literal["supports", "invalidates"]


class ThesisBody(BaseModel):
    instrument_id: uuid.UUID
    ownership: Literal["owned", "considered"]
    reason: str = Field(min_length=10, max_length=1000)
    conditions: list[ConditionIn] = Field(min_length=1, max_length=MAX_CONDITIONS)
    horizon_date: date | None = None
    review_date: date | None = None
    confirmed: bool = False

    @field_validator("conditions")
    @classmethod
    def _distinct(cls, v):
        texts = [c.text.strip().lower() for c in v]
        if len(set(texts)) != len(texts):
            raise ValueError("conditions must be distinct")
        return v


class ThesisUpdate(ThesisBody):
    expected_version: int
    status: Literal["active", "closed"] = "active"


def thesis_out(t: Thesis, latest: ThesisAssessment | None = None) -> dict:
    return {"chain_id": str(t.chain_id), "version": t.version, "instrument_id": str(t.instrument_id), "symbol": t.symbol,
            "ownership": t.ownership, "reason": t.reason, "conditions": t.conditions,
            "horizon_date": t.horizon_date.isoformat() if t.horizon_date else None,
            "review_date": t.review_date.isoformat() if t.review_date else None, "status": t.status,
            "confirmed_at": t.confirmed_at.isoformat(),
            "latest_assessment": None if latest is None else assessment_out(latest, brief=True),
            "note": "Your reason and conditions are yours: evidence creates an assessment for you to review and never edits them."}


def assessment_out(a: ThesisAssessment, *, brief: bool = False) -> dict:
    base = {"assessment_id": str(a.id), "thesis_chain_id": str(a.thesis_chain_id), "thesis_version": a.thesis_version, "status": a.status,
            "change_log": a.change_log, "review_status": a.review_status, "created_at": a.created_at.isoformat(),
            "policy_version": a.policy_version, "research_session_id": None if a.research_session_id is None else str(a.research_session_id),
            "portfolio_effect": "none: a thesis never overrides your portfolio review or suitability checks"}
    if brief:
        return base
    return {**base, "per_condition": a.per_condition, "evidence": a.evidence, "verification": a.verification,
            "contradictions": a.contradictions, "gaps": a.gaps, "model_info": a.model_info,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None}


async def _latest_thesis(db: AsyncSession, chain_id: uuid.UUID) -> Thesis | None:
    return (await db.execute(select(Thesis).where(Thesis.chain_id == chain_id, Thesis.user_id == SINGLE_USER_ID)
                             .order_by(Thesis.version.desc()).limit(1))).scalar_one_or_none()


async def _latest_assessment(db: AsyncSession, chain_id: uuid.UUID) -> ThesisAssessment | None:
    return (await db.execute(select(ThesisAssessment).where(ThesisAssessment.thesis_chain_id == chain_id, ThesisAssessment.user_id == SINGLE_USER_ID)
                             .order_by(ThesisAssessment.created_at.desc()).limit(1))).scalar_one_or_none()


async def _check_instrument(db: AsyncSession, body: ThesisBody) -> Instrument:
    inst = await db.get(Instrument, body.instrument_id)
    if inst is None:
        raise HTTPException(422, "unknown instrument")
    if not body.confirmed:
        raise HTTPException(422, "a thesis needs your explicit confirmation (confirmed=true); it is never inferred")
    if body.ownership == "owned":
        state = await latest_state(db, SINGLE_USER_ID)
        val = None if state is None else await latest_valuation(db, state.id)
        owned = state is not None and val is not None and any(
            p["asset_type"] == "listed_equity" and p["instrument_id"] == str(inst.id) and p["value"] is not None
            for p in await twin_positions(db, state, val))
        if not owned:
            raise HTTPException(422, "this stock is not a matched, valued holding in your latest snapshot; "
                                     "choose ownership=considered if you are only thinking about it")
    return inst


def _conditions(new: list[ConditionIn], old: list[dict] | None) -> list[dict]:
    by_text = {c["text"].strip().lower(): c["id"] for c in (old or [])}
    used = {c["id"] for c in (old or [])}
    n = len(used)
    out = []
    for c in new:
        cid = by_text.get(c.text.strip().lower())
        if cid is None:
            n += 1
            while f"c{n}" in used:
                n += 1
            cid = f"c{n}"
            used.add(cid)
        out.append({"id": cid, "text": c.text.strip(), "kind": c.kind})
    return out


@router.get("/theses")
async def list_theses(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Thesis).where(Thesis.user_id == SINGLE_USER_ID).order_by(Thesis.chain_id, Thesis.version.desc()))).scalars().all()
    latest: dict = {}
    for r in rows:
        latest.setdefault(r.chain_id, r)
    out = []
    for t in sorted(latest.values(), key=lambda t: t.symbol):
        out.append(thesis_out(t, await _latest_assessment(db, t.chain_id)))
    return out


@router.post("/theses", status_code=201)
async def create_thesis(body: ThesisBody, db: AsyncSession = Depends(get_db)):
    inst = await _check_instrument(db, body)
    now = utcnow()
    t = Thesis(user_id=SINGLE_USER_ID, chain_id=uuid.uuid4(), version=1, instrument_id=inst.id, symbol=inst.symbol, ownership=body.ownership,
               reason=body.reason.strip(), horizon_date=body.horizon_date, conditions=_conditions(body.conditions, None),
               review_date=body.review_date, status="active", confirmed_at=now, created_at=now)
    db.add(t)
    await db.commit()
    return thesis_out(t)


@router.get("/theses/{chain_id}")
async def get_thesis(chain_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    t = await _latest_thesis(db, chain_id)
    if t is None:
        raise HTTPException(404, "thesis not found")
    events = (await db.execute(select(ThesisEvent).where(ThesisEvent.thesis_chain_id == chain_id, ThesisEvent.user_id == SINGLE_USER_ID)
                               .order_by(ThesisEvent.occurred_at.desc()).limit(20))).scalars().all()
    return {**thesis_out(t, await _latest_assessment(db, chain_id)),
            "events": [{"kind": e.kind, "observed": e.observed, "occurred_at": e.occurred_at.isoformat(),
                        "effect_on_thesis": "none: a price move never changes a thesis' status"} for e in events]}


@router.put("/theses/{chain_id}")
async def edit_thesis(chain_id: uuid.UUID, body: ThesisUpdate, db: AsyncSession = Depends(get_db)):
    cur = await _latest_thesis(db, chain_id)
    if cur is None:
        raise HTTPException(404, "thesis not found")
    if body.expected_version != cur.version:
        raise HTTPException(409, f"stale version: thesis is at version {cur.version}")
    if body.instrument_id != cur.instrument_id:
        raise HTTPException(422, "a thesis is about one stock; create a new thesis for another")
    await _check_instrument(db, body) if body.status == "active" and body.ownership == "owned" else None
    if not body.confirmed:
        raise HTTPException(422, "a thesis needs your explicit confirmation (confirmed=true)")
    now = utcnow()
    t = Thesis(user_id=SINGLE_USER_ID, chain_id=chain_id, version=cur.version + 1, instrument_id=cur.instrument_id, symbol=cur.symbol,
               ownership=body.ownership, reason=body.reason.strip(), horizon_date=body.horizon_date,
               conditions=_conditions(body.conditions, cur.conditions), review_date=body.review_date, status=body.status,
               confirmed_at=now, created_at=now)
    db.add(t)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "thesis changed concurrently; reload and retry")
    return thesis_out(t, await _latest_assessment(db, chain_id))


@router.get("/theses/{chain_id}/assessments")
async def list_assessments(chain_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ThesisAssessment).where(ThesisAssessment.thesis_chain_id == chain_id, ThesisAssessment.user_id == SINGLE_USER_ID)
                             .order_by(ThesisAssessment.created_at.desc()))).scalars().all()
    return [assessment_out(a) for a in rows]


@router.post("/theses/{chain_id}/refresh", status_code=201)
async def refresh_thesis(chain_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                         researcher: ThesisResearcher = Depends(get_thesis_researcher)):
    """On-demand evidence refresh. Bounded, never automatic. The result is a PROPOSED assessment for the owner to review."""
    t = await _latest_thesis(db, chain_id)
    if t is None:
        raise HTTPException(404, "thesis not found")
    if t.status != "active":
        raise HTTPException(422, "this thesis is closed")
    outcome = await researcher.gather(db, t)
    session = None if outcome.session_id is None else await db.get(ResearchSession, outcome.session_id)
    if session is not None:  # persist what used to exist only in the POST response
        session.verification, session.contradictions = outcome.verification, outcome.contradictions
        await db.commit()

    prov = await fact_provenance(db, outcome.fact_ids)
    supported = [p for p in prov.values() if p["support_status"] == "supported"]
    gaps = list(outcome.gaps)
    model_info = {"used": False, "prompt_version": logic.PROMPT_VERSION, "model": None, "error": None,
                  "role": "maps verified facts to your conditions only; it never sets the status or writes a number"}
    verdicts: list[logic.ConditionVerdict] = []
    if not outcome.fact_ids:
        gaps.append("no evidence was retrieved")
    elif not supported:
        gaps.append(f"{len(outcome.fact_ids)} fact(s) were retrieved but none passed verification, so nothing is citable")
    else:
        mapping = await researcher.map_conditions(t, supported)
        model_info.update(mapping.info)
        verdicts = mapping.verdicts
        if not mapping.info.get("used"):
            gaps.append("evidence was retrieved but could not be mapped to your conditions (model unavailable); nothing was assessed")
    gaps = list(dict.fromkeys(gaps))  # the same gap is often reported by several branches
    per_condition = logic.validate_verdicts(t.conditions, verdicts, prov)
    status, reasons = logic.aggregate_status(per_condition)
    prior = await _latest_assessment(db, chain_id)
    log = logic.change_log(prior.status if prior else None, status, per_condition, prior.per_condition if prior else None)
    a = ThesisAssessment(
        user_id=SINGLE_USER_ID, thesis_chain_id=chain_id, thesis_version=t.version, research_session_id=outcome.session_id, status=status,
        prior_assessment_id=prior.id if prior else None, change_log=log + " " + " ".join(reasons),
        per_condition=per_condition,
        evidence={fid: p for fid, p in prov.items()}, verification=outcome.verification, contradictions=outcome.contradictions,
        gaps=gaps, model_info=model_info, policy_version=logic.POLICY_VERSION, review_status="pending", created_at=utcnow())
    db.add(a)
    await db.commit()
    return assessment_out(a)


@router.post("/theses/{chain_id}/assessments/{assessment_id}/acknowledge")
async def acknowledge(chain_id: uuid.UUID, assessment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(ThesisAssessment).where(ThesisAssessment.id == assessment_id, ThesisAssessment.thesis_chain_id == chain_id,
                                                         ThesisAssessment.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "assessment not found")
    if a.review_status != "acknowledged":
        a.review_status, a.acknowledged_at = "acknowledged", utcnow()
        await db.commit()
    return assessment_out(a)


async def observe_price(db: AsyncSession, t: Thesis, *, today: date | None = None) -> dict:
    """5- and 20-session moves from adjusted, non-demo daily candles. Records a `price_move` event (once per day)
    when a threshold is crossed. NEVER touches a thesis or its assessments."""
    rows = (await db.execute(select(MarketCandle.timestamp, MarketCandle.close).where(
        MarketCandle.instrument_id == t.instrument_id, MarketCandle.interval == "1d", MarketCandle.adjusted.is_(True),
        MarketCandle.superseded_at.is_(None), MarketCandle.source != "demo_seed").order_by(MarketCandle.timestamp.desc()).limit(25))).all()
    closes = [(ts.date(), float(c)) for ts, c in rows if c and c > 0]
    obs: dict = {"symbol": t.symbol, "sessions_available": len(closes), "event_recorded": False}
    if len(closes) < 6:
        obs["status"] = "insufficient_history"
        return obs
    last_day, last = closes[0]
    obs["as_of"] = last_day.isoformat()
    m5 = last / closes[5][1] - 1
    obs["move_5_sessions"] = round(m5, 4)
    m20 = last / closes[20][1] - 1 if len(closes) > 20 else None
    obs["move_20_sessions"] = None if m20 is None else round(m20, 4)
    crossed = abs(m5) >= PRICE_MOVE_5D or (m20 is not None and abs(m20) >= PRICE_MOVE_20D)
    obs["status"] = "threshold_crossed" if crossed else "within_normal_range"
    if crossed:
        ev = ThesisEvent(user_id=SINGLE_USER_ID, thesis_chain_id=t.chain_id, kind="price_move", observed=obs,
                         dedup_key=f"price:{t.chain_id}:{last_day.isoformat()}", occurred_at=utcnow(), created_at=utcnow())
        db.add(ev)
        try:
            await db.commit()
            obs["event_recorded"] = True
        except IntegrityError:
            await db.rollback()
    obs["effect_on_thesis"] = "none: price movement alone does not weaken or strengthen a thesis"
    return obs


@router.post("/theses/{chain_id}/price-check")
async def price_check(chain_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    t = await _latest_thesis(db, chain_id)
    if t is None:
        raise HTTPException(404, "thesis not found")
    return await observe_price(db, t)
