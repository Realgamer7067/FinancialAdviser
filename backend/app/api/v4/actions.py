"""Counterfactual action lab (Portfolio Intelligence Engine Phase 06).

`POST /actions/evaluate` freezes the chosen state + valuation, applies the SAME
external flows to HOLD and every user-supplied alternative, runs independent
gates, recomputes the whole risk picture and compares each alternative with
HOLD. The result is saved as an immutable AnalysisRun (replay via
`GET /analysis/{id}`); a saved simulation NEVER publishes a current action."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.constraints import budget, risk_constraints
from app.api.v4.personal import profile_view
from app.api.v4.risk import _get_or_create, _hash, _payload, claims_by_position, twin_positions
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.analysis_runs import AnalysisRun
from app.models.market import Instrument, MarketCandle
from app.models.twin import PortfolioState, ValuationSnapshot
from app.portfolio_intelligence.decisions import engine
from app.portfolio_intelligence.goals.service import monthly_equivalent
from app.portfolio_intelligence.goals.store import latest_allocations, latest_commitments, latest_goals
from app.portfolio_intelligence.state.build import active_liabilities, active_preferences, latest_profile

router = APIRouter(prefix="/api/v4", tags=["v4-actions"])

METHOD = f"{engine.ENGINE_VERSION}+{engine.POLICY_VERSION}"
MAX_ACTIONS = 20


class ActionIn(BaseModel):
    type: Literal["BUY", "REDUCE_PREVIEW", "RESERVE", "ADJUST_CONTRIBUTION"]
    amount: Decimal | None = None
    instrument_id: uuid.UUID | None = None       # BUY: from the instrument master
    account_id: uuid.UUID | None = None          # BUY: which account the purchase lands in
    funding: Literal["new_money", "existing_cash"] | None = None  # BUY: where the cash comes from (required)
    position_id: str | None = None               # REDUCE_PREVIEW: a position of the chosen state
    commitment_chain_id: uuid.UUID | None = None  # ADJUST_CONTRIBUTION
    new_monthly_amount: Decimal | None = None

    @field_validator("amount", "new_monthly_amount")
    @classmethod
    def _pos(cls, v):
        if v is not None and (not v.is_finite() or v <= 0):
            raise ValueError("must be a positive amount")
        return v


class EvaluateIn(BaseModel):
    state_id: uuid.UUID
    valuation_id: uuid.UUID
    external_contribution: Decimal = Decimal(0)
    external_withdrawal: Decimal = Decimal(0)
    fee_pct: Decimal | None = None
    priorities: list[str] = Field(default_factory=list, max_length=10)
    actions: list[ActionIn] = Field(default_factory=list, max_length=MAX_ACTIONS)

    @field_validator("external_contribution", "external_withdrawal")
    @classmethod
    def _flow(cls, v):
        if not v.is_finite() or v < 0:
            raise ValueError("must be zero or a positive amount")
        return v


async def _prices(db: AsyncSession, instrument_ids: list[uuid.UUID], cutoff) -> dict:
    out = {}
    for iid in instrument_ids:
        row = (await db.execute(select(MarketCandle.timestamp, MarketCandle.close).where(
            MarketCandle.instrument_id == iid, MarketCandle.interval == "1d", MarketCandle.adjusted.is_(True),
            MarketCandle.superseded_at.is_(None), MarketCandle.source != "demo_seed", MarketCandle.timestamp <= cutoff)
            .order_by(MarketCandle.timestamp.desc()).limit(1))).first()
        if row is not None and row[1] and row[1] > 0:
            out[str(iid)] = {"price": Decimal(str(row[1])).quantize(Decimal("0.01")), "as_of": row[0].date()}
    return out


@router.post("/actions/evaluate")
async def evaluate_actions(payload: EvaluateIn, db: AsyncSession = Depends(get_db)):
    state = (await db.execute(select(PortfolioState).where(PortfolioState.id == payload.state_id,
                                                           PortfolioState.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    valuation = await db.get(ValuationSnapshot, payload.valuation_id)
    if state is None or valuation is None or valuation.state_id != state.id:
        raise HTTPException(404, "state/valuation not found, or the valuation does not belong to that state")

    baseline = await twin_positions(db, state, valuation)
    labels = {a["account_id"]: a["label"] for a in state.account_inputs}
    claims = await claims_by_position(db)
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    constraints = await risk_constraints(db)
    bud = await budget(db)
    restrictions = [{"kind": p.kind, "value": p.value} for p in await active_preferences(db, SINGLE_USER_ID)]

    inst_ids = sorted({a.instrument_id for a in payload.actions if a.type == "BUY" and a.instrument_id})
    insts = {str(i.id): {"symbol": i.symbol, "sector": i.sector, "isin": i.isin, "lot_size": i.lot_size, "asset_type": "listed_equity"}
             for i in (await db.execute(select(Instrument).where(Instrument.id.in_(inst_ids)))).scalars()} if inst_ids else {}
    prices = await _prices(db, inst_ids, valuation.cutoff)
    today = valuation.cutoff.date()  # replay-stable: ages are measured at the valuation's cutoff

    commitments_all = await latest_commitments(db, SINGLE_USER_ID)
    live = [c for c in commitments_all if c.status == "active" and c.source == "existing_user_reported"
            and c.start_date <= today and (c.end_date is None or c.end_date >= today)]
    commitments = {str(c.chain_id): {"chain_id": str(c.chain_id), "goal_chain_id": None if c.goal_chain_id is None else str(c.goal_chain_id),
                                     "monthly": monthly_equivalent(c.amount, c.frequency)} for c in live}
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    goals = {}
    for g in await latest_goals(db, SINGLE_USER_ID):
        cid = str(g.chain_id)
        goals[cid] = {"chain_id": cid, "description": g.description, "target_amount": g.target_amount, "target_basis": g.target_basis,
                      "target_date": g.target_date, "inflation": g.inflation_assumption,
                      "starting": sum((a.amount for a in allocs if a.goal_chain_id == g.chain_id and a.status == "active"), Decimal(0)),
                      "monthly": sum((c["monthly"] for c in commitments.values() if c["goal_chain_id"] == cid), Decimal(0))}

    actions = []
    for a in payload.actions:
        d: dict = {"type": a.type}
        if a.type == "BUY":
            if a.instrument_id is None or a.amount is None or a.account_id is None or a.funding is None:
                raise HTTPException(422, "BUY needs instrument_id, account_id, amount and funding (new_money or existing_cash)")
            label = labels.get(str(a.account_id))
            if label is None:
                raise HTTPException(422, "that account is not part of the chosen state")
            d.update(instrument_id=str(a.instrument_id), amount=a.amount, funding=a.funding, account_label=label)
        elif a.type == "REDUCE_PREVIEW":
            if a.position_id is None or a.amount is None:
                raise HTTPException(422, "REDUCE_PREVIEW needs position_id and amount")
            d.update(position_id=a.position_id, amount=a.amount)
        elif a.type == "RESERVE":
            if a.amount is None:
                raise HTTPException(422, "RESERVE needs amount")
            d.update(amount=a.amount)
        else:
            if a.commitment_chain_id is None or a.new_monthly_amount is None:
                raise HTTPException(422, "ADJUST_CONTRIBUTION needs commitment_chain_id and new_monthly_amount")
            d.update(commitment_chain_id=str(a.commitment_chain_id), new_monthly_amount=a.new_monthly_amount)
        actions.append(d)

    fee = payload.fee_pct if payload.fee_pct is not None else engine.POLICY["default_fee_pct"]
    ctx = {"baseline": baseline, "claims": claims, "capacity": pv["capacity"], "constraints": constraints, "restrictions": restrictions,
           "instruments": insts, "prices": prices, "commitments": commitments, "goals": goals, "budget": bud,
           "contribution": payload.external_contribution, "withdrawal": payload.external_withdrawal, "actions": actions,
           "priorities": payload.priorities, "fee_pct": fee, "today": today}

    def compute():
        try:
            return engine.evaluate(ctx)
        except engine.ActionInvalid as exc:
            raise HTTPException(422, str(exc))

    params = {"flows": [str(payload.external_contribution), str(payload.external_withdrawal)], "fee_pct": str(fee),
              "priorities": payload.priorities, "actions": [{k: (str(v) if v is not None else None) for k, v in d.items()} for d in actions]}
    inputs = {"params": params, "prices": {k: [str(v["price"]), v["as_of"].isoformat()] for k, v in sorted(prices.items())},
              "constraints": constraints, "budget": bud, "claims": {k: str(v) for k, v in sorted(claims.items())},
              "restrictions": restrictions, "capacity_policy": pv["capacity"]["policy_version"]}
    result = compute()  # validate BEFORE persisting (a 422 must not leave a half-saved run)
    run, created = await _get_or_create(db, kind="actions", state_id=state.id, valuation_id=valuation.id, method=METHOD,
                                        inputs_hash=_hash(inputs), params=params, result_fn=lambda: result)
    return _payload(run, created)


@router.get("/actions/evaluations")
async def list_evaluations(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AnalysisRun).where(AnalysisRun.user_id == SINGLE_USER_ID, AnalysisRun.kind == "actions")
                             .order_by(AnalysisRun.created_at.desc()).limit(30))).scalars().all()
    return [{"analysis_id": str(r.id), "state_id": str(r.state_id), "valuation_id": str(r.valuation_id), "created_at": r.created_at.isoformat(),
             "alternatives": len(r.result["alternatives"]), "headline": r.result["summary"]["headline"]} for r in rows]


@router.get("/instruments")
async def list_instruments(q: str | None = None, db: AsyncSession = Depends(get_db)):
    """The instrument master available for what-if purchases (the Nifty universe seed)."""
    stmt = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    if q:
        ql = q.lower()
        rows = [i for i in rows if ql in i.symbol.lower() or ql in i.name.lower()]
    return [{"id": str(i.id), "symbol": i.symbol, "name": i.name, "sector": i.sector, "isin": i.isin, "lot_size": i.lot_size} for i in rows]
