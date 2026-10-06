"""Portfolio Twin API (Portfolio Intelligence Engine Phase 03). Reads return
saved, immutable state/valuation by ID; nothing here re-prices history.
`is_stale` says the inputs changed since the state was built (refresh to
publish a new one)."""

import uuid
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import AccountCoverageAttestation, PositionObservation, SourceAccount
from app.models.goals_v4 import GoalAllocation
from app.models.market import Instrument
from app.models.securities import Security
from app.models.personal import FinancialProfileRevision
from app.models.twin import PortfolioPosition, PortfolioState, ValuationSnapshot
from app.portfolio_intelligence.state.build import (
    hash_for_inputs, latest_state, latest_valuation, load_inputs, refresh_state,
)
from app.portfolio_intelligence.personal.facts import missing_fields
from app.portfolio_intelligence.state.readiness import compute_readiness
from app.portfolio_intelligence.state.catalogue_identity import catalogue_securities, effective_identity

router = APIRouter(prefix="/api/v4", tags=["v4-state"])


def _iso(d: datetime | None):
    return None if d is None else d.isoformat()


async def _state_payload(db: AsyncSession, state: PortfolioState, valuation: ValuationSnapshot | None) -> dict:
    rows = (await db.execute(
        select(PortfolioPosition, PositionObservation)
        .join(PositionObservation, PositionObservation.id == PortfolioPosition.observation_id)
        .where(PortfolioPosition.state_id == state.id)
        .order_by(PortfolioPosition.source_account_id, PositionObservation.row_ordinal))).all()
    labels = {a["account_id"]: a["label"] for a in state.account_inputs}
    inst_ids = {o.instrument_id for _, o in rows if o.instrument_id}
    symbols = {i.id: i.symbol for i in (await db.execute(select(Instrument).where(Instrument.id.in_(inst_ids)))).scalars()} if inst_ids else {}
    # An ISIN in the market catalogue is a real, priceable security even when the old Nifty 50 table does not list it:
    # use its symbol for display and say so, instead of showing a bare ISIN marked "unmatched".
    isins = {o.isin for _, o in rows if o.isin}
    resolved = await catalogue_securities(db, isins)
    catalogue = {i: x for i, x in resolved.items() if x.symbol and x.kind in ("stock", "etf")}
    # Link a holding to its market page when its ISIN names exactly one active security (stock, ETF or fund).
    by_isin = {i: str(x.id) for i, x in resolved.items()}
    positions = [{
        "position_id": str(p.id), "account_id": str(p.source_account_id), "account_label": labels.get(str(p.source_account_id)),
        "asset_type": o.asset_type, "raw_identifier": o.raw_identifier, "isin": o.isin, "symbol": o.symbol,
        "display_name": symbols.get(o.instrument_id) or (catalogue[o.isin].symbol if o.isin in catalogue else None) or o.raw_identifier or "unknown",
        "in_catalogue": bool(o.isin and o.isin in catalogue),
        "security_id": by_isin.get(o.isin),
        "identity": effective_identity(o.resolution, o.isin, by_isin),
        "instrument_id": None if o.instrument_id is None else str(o.instrument_id),
        "resolution": o.resolution, "resolution_note": o.resolution_note,
        "units": None if o.units is None else str(o.units),
        "cost_basis": None if o.cost_basis is None else str(o.cost_basis),  # only if the source gave it
        "locked": o.locked, "ownership": o.ownership,
    } for p, o in rows]

    att = await db.get(AccountCoverageAttestation, state.coverage_attestation_id) if state.coverage_attestation_id else None
    att_status = att.status if att else "unknown"
    att_missing = list(att.missing_account_types or []) if att else []
    problem_accounts = []
    for a in state.account_inputs:
        acct = await db.get(SourceAccount, uuid.UUID(a["account_id"]))
        if acct is not None and acct.last_error:
            problem_accounts.append(a["label"])
    profile = await db.get(FinancialProfileRevision, state.profile_revision_id) if state.profile_revision_id else None
    alloc_ids = [uuid.UUID(x) for x in (state.allocation_revision_ids or [])]
    needs_review = 0 if not alloc_ids else len((await db.execute(
        select(GoalAllocation.id).where(GoalAllocation.id.in_(alloc_ids), GoalAllocation.status == "needs_review"))).scalars().all())
    readiness = compute_readiness(
        account_inputs=state.account_inputs, attestation_status=att_status, attestation_missing=att_missing,
        position_resolutions=[p["identity"] for p in positions],
        unknown_value_count=0 if valuation is None else valuation.unknown_value_count,
        valued_count=0 if valuation is None else valuation.coverage.get("valued_count", 0),
        stale_or_error_accounts=problem_accounts,
        profile_missing=None if profile is None else missing_fields(profile.facts),
        goal_count=len(state.goal_revision_ids or []), allocations_needing_review=needs_review)
    return {
        "state": {
            "id": str(state.id), "version": state.version, "created_at": _iso(state.created_at),
            "economic_hash": state.economic_hash, "normalization_version": state.normalization_version,
            "coverage": {"status": att_status, "missing_account_types": att_missing,
                         "attestation_version": att.version if att else 0},
            "accounts": state.account_inputs, "positions": positions,
            "bound_facts": {"profile_version": profile.version if profile else None,
                            "liability_count": len(state.liability_revision_ids or []),
                            "preference_count": len(state.preference_revision_ids or []),
                            "goal_count": len(state.goal_revision_ids or []),
                            "allocation_count": len(state.allocation_revision_ids or []),
                            "commitment_count": len(state.commitment_revision_ids or [])},
        },
        "valuation": None if valuation is None else _valuation_payload(valuation, {p["position_id"]: p["identity"] for p in positions}),
        "readiness": readiness,
        # Until the user confirms all accounts are added this is NOT total wealth.
        "headline_label": "Known portfolio value" if att_status != "complete" else "Portfolio value",
    }


def _valuation_payload(v: ValuationSnapshot, identity_by_pos: dict[str, str] | None = None) -> dict:
    coverage = v.coverage
    if identity_by_pos is not None:
        # Recomputed at read time: the stored share was fixed when the snapshot was built, but the catalogue (and so which
        # holdings are recognised) can change afterwards.
        known = [(Decimal(x["value"]), x["position_id"]) for x in v.selections if x["value"] is not None]
        total = sum((val for val, _ in known), Decimal(0))
        if total > 0:
            ok = sum((val for val, pid in known if identity_by_pos.get(pid) not in ("unresolved", "ambiguous")), Decimal(0))
            coverage = {**coverage, "identity_resolved_value_share": str((ok / total).quantize(Decimal("0.0001")))}
    return {
        "id": str(v.id), "state_id": str(v.state_id), "price_policy_version": v.price_policy_version,
        "cutoff": _iso(v.cutoff), "known_total": str(v.known_total), "unknown_value_count": v.unknown_value_count,
        "coverage": coverage, "selections": v.selections,
    }


@router.get("/state/current")
async def current_state(db: AsyncSession = Depends(get_db)):
    state = await latest_state(db, SINGLE_USER_ID)
    if state is None:
        return {"state": None, "valuation": None, "is_stale": False,
                "readiness": compute_readiness(account_inputs=[], attestation_status="unknown", attestation_missing=[],
                                               position_resolutions=[], unknown_value_count=0, valued_count=0,
                                               stale_or_error_accounts=[]),
                "headline_label": "Known portfolio value"}
    payload = await _state_payload(db, state, await latest_valuation(db, state.id))
    payload["is_stale"] = hash_for_inputs(await load_inputs(db, SINGLE_USER_ID)) != state.economic_hash
    return payload


@router.post("/state/refresh")
async def refresh(db: AsyncSession = Depends(get_db)):
    res = await refresh_state(db, SINGLE_USER_ID)
    if res.state is None:
        raise HTTPException(409, "no included accounts; add an account and import holdings first")
    payload = await _state_payload(db, res.state, res.valuation)
    payload.update(is_stale=False, state_created=res.state_created, valuation_created=res.valuation_created)
    return payload


@router.get("/states")
async def list_states(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PortfolioState).where(PortfolioState.user_id == SINGLE_USER_ID)
                             .order_by(PortfolioState.version.desc()).limit(50))).scalars().all()
    return [{"id": str(s.id), "version": s.version, "created_at": _iso(s.created_at), "economic_hash": s.economic_hash[:12]} for s in rows]


@router.get("/states/{state_id}")
async def get_state(state_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    state = (await db.execute(select(PortfolioState).where(PortfolioState.id == state_id, PortfolioState.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if state is None:
        raise HTTPException(404, "state not found")
    return await _state_payload(db, state, await latest_valuation(db, state.id))


@router.get("/valuations/{valuation_id}")
async def get_valuation(valuation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    v = await db.get(ValuationSnapshot, valuation_id)
    if v is None:
        raise HTTPException(404, "valuation not found")
    state = await db.get(PortfolioState, v.state_id)
    if state is None or state.user_id != SINGLE_USER_ID:
        raise HTTPException(404, "valuation not found")
    return _valuation_payload(v)
