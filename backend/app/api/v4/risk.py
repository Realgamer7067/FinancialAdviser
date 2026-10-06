"""Risk observations and stress scenarios (Portfolio Intelligence Engine
Phase 05). Everything is bound to a saved Twin state + valuation, computed by
deterministic pure code, and saved as an immutable AnalysisRun that can be
replayed by id. No forecast, probability or "health score" is produced."""

import hashlib
import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.personal import profile_view
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import PositionObservation
from app.models.analysis_runs import AnalysisRun
from app.portfolio_intelligence.state.catalogue_identity import catalogue_securities
from app.models.market import Instrument, MarketCandle
from app.models.twin import PortfolioPosition, PortfolioState, ValuationSnapshot
from app.portfolio_intelligence.goals.service import current_holding_values
from app.portfolio_intelligence.goals.store import latest_allocations
from app.portfolio_intelligence.risk import exposure as exposure_mod
from app.portfolio_intelligence.risk import stress as stress_mod
from app.portfolio_intelligence.risk import volatility as vol_mod
from app.portfolio_intelligence.risk.exposure import compute_exposures, compute_liquidity
from app.portfolio_intelligence.risk.stress import CATALOG, resolve_scenario, run_scenario
from app.portfolio_intelligence.risk.volatility import portfolio_volatility
from app.portfolio_intelligence.state.build import active_liabilities, latest_profile, latest_state, latest_valuation
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-risk"])

RISK_METHOD = f"{exposure_mod.METHOD_VERSION}+{vol_mod.METHOD_VERSION}"
SCENARIO_METHOD = stress_mod.SCENARIO_VERSION


async def twin_positions(db: AsyncSession, state: PortfolioState, valuation: ValuationSnapshot) -> list[dict]:
    sel = {s["position_id"]: s for s in valuation.selections}
    labels = {a["account_id"]: a["label"] for a in state.account_inputs}
    rows = (await db.execute(select(PortfolioPosition, PositionObservation)
                             .join(PositionObservation, PositionObservation.id == PortfolioPosition.observation_id)
                             .where(PortfolioPosition.state_id == state.id)
                             .order_by(PortfolioPosition.source_account_id, PositionObservation.row_ordinal))).all()
    inst_ids = {o.instrument_id for _, o in rows if o.instrument_id}
    insts = {i.id: i for i in (await db.execute(select(Instrument).where(Instrument.id.in_(inst_ids)))).scalars()} if inst_ids else {}
    # Identity from the market catalogue by ISIN, for holdings the Nifty 50 table does not list: it says what a holding really is
    # (an ETF typed as "listed equity" is a fund, not a company) and, for larger stocks, its sector.
    cat = await catalogue_securities(db, {o.isin for _, o in rows if o.isin and o.instrument_id is None})
    out = []
    for p, o in rows:
        s = sel.get(str(p.id))
        inst = insts.get(o.instrument_id) if o.instrument_id else None
        sec = cat.get(o.isin) if o.isin and inst is None else None      # two different securities sharing an ISIN: say nothing rather than guess
        asset_type = o.asset_type
        if sec is not None and asset_type == "listed_equity" and sec.kind in ("etf", "mutual_fund"):
            asset_type = sec.kind
        out.append({
            "position_id": str(p.id), "account_label": labels.get(str(p.source_account_id), "?"), "asset_type": asset_type,
            "declared_asset_type": o.asset_type,
            "resolution": o.resolution, "instrument_id": None if o.instrument_id is None else str(o.instrument_id), "isin": o.isin,
            "label": (inst.symbol if inst else None) or (sec.symbol if sec is not None and sec.symbol else None) or o.raw_identifier or "unknown",
            "value": None if s is None or s["value"] is None else Decimal(s["value"]),
            "quality": s["quality"] if s else "unvalued", "as_of": s["as_of"] if s else o.valuation_date.isoformat(),
            "sector": inst.sector if inst else (sec.sector if sec is not None and sec.kind == "stock" else None),
            "sector_source": "instrument_master" if inst and inst.sector else ("market_catalogue" if sec is not None and sec.kind == "stock" and sec.sector else None),
        })
    return out


async def load_candle_series(db: AsyncSession, instrument_ids: list[uuid.UUID]) -> tuple[dict, dict]:
    """Adjusted daily candles only; demo-seed rows never feed a risk number. Returns (series, digest)."""
    series: dict[str, list] = {}
    digest: dict[str, list] = {}
    for iid in instrument_ids:
        rows = (await db.execute(select(MarketCandle.timestamp, MarketCandle.close, MarketCandle.retrieved_at).where(
            MarketCandle.instrument_id == iid, MarketCandle.interval == "1d", MarketCandle.adjusted.is_(True),
            MarketCandle.superseded_at.is_(None), MarketCandle.source != "demo_seed").order_by(MarketCandle.timestamp))).all()
        by_day: dict = {}
        for ts, close, retrieved in rows:  # one price per day: the most recently retrieved
            d = ts.date()
            if d not in by_day or retrieved > by_day[d][1]:
                by_day[d] = (close, retrieved)
        s = sorted((d, v[0]) for d, v in by_day.items())
        series[str(iid)] = s
        digest[str(iid)] = [len(s), s[0][0].isoformat() if s else None, s[-1][0].isoformat() if s else None,
                            hashlib.sha1(json.dumps([round(v, 6) for _, v in s]).encode()).hexdigest()[:16]]  # price-revision sensitive
    return series, digest


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


async def _get_or_create(db: AsyncSession, *, kind: str, state_id, valuation_id, method: str, inputs_hash: str,
                         params: dict, result_fn) -> tuple[AnalysisRun, bool]:
    q = select(AnalysisRun).where(AnalysisRun.user_id == SINGLE_USER_ID, AnalysisRun.kind == kind, AnalysisRun.state_id == state_id,
                                  AnalysisRun.valuation_id == valuation_id, AnalysisRun.method_version == method,
                                  AnalysisRun.inputs_hash == inputs_hash)
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    run = AnalysisRun(user_id=SINGLE_USER_ID, kind=kind, state_id=state_id, valuation_id=valuation_id, method_version=method,
                      inputs_hash=inputs_hash, params=params, result=result_fn(), created_at=utcnow())
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return (await db.execute(q)).scalar_one(), False
    return run, True


def _payload(run: AnalysisRun, created: bool | None = None) -> dict:
    out = {"analysis_id": str(run.id), "kind": run.kind, "state_id": str(run.state_id), "valuation_id": str(run.valuation_id),
           "method_version": run.method_version, "created_at": run.created_at.isoformat(), "params": run.params, **run.result}
    if created is not None:
        out["created"] = created
    return out


def _needs_state(state, valuation):
    if state is None or valuation is None:
        raise HTTPException(409, "no portfolio snapshot yet; add an account and import holdings first")


async def claims_by_position(db: AsyncSession) -> dict[str, Decimal]:
    """Goal claims (active + needs_review reserve) mapped to the current twin's position ids."""
    holdings = await current_holding_values(db, SINGLE_USER_ID)
    allocs = await latest_allocations(db, SINGLE_USER_ID)
    out: dict[str, Decimal] = {}
    for h in holdings.values():
        claimed = sum((a.amount for a in allocs if a.holding_key == h.key and a.status in ("active", "needs_review")), Decimal(0))
        if claimed and h.position_ids:
            out[h.position_ids[0]] = claimed
    return out


@router.get("/risk")
async def get_risk(db: AsyncSession = Depends(get_db)):
    state = await latest_state(db, SINGLE_USER_ID)
    valuation = None if state is None else await latest_valuation(db, state.id)
    _needs_state(state, valuation)
    positions = await twin_positions(db, state, valuation)
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    claims_by_pos = await claims_by_position(db)
    eq = [p for p in positions if p["asset_type"] == "listed_equity" and p["resolution"] == "resolved" and p["value"] is not None
          and p["instrument_id"]]
    inst_ids = sorted({uuid.UUID(p["instrument_id"]) for p in eq})
    series, digest = await load_candle_series(db, inst_ids)
    total = sum((p["value"] for p in positions if p["value"] is not None), Decimal(0))
    values: dict[str, Decimal] = {}
    for p in eq:
        values[p["instrument_id"]] = values.get(p["instrument_id"], Decimal(0)) + p["value"]

    def compute():
        return {
            "as_of": valuation.cutoff.isoformat(), "valuation_cutoff": valuation.cutoff.isoformat(),
            "known_total": format(total.normalize(), "f"),
            **compute_exposures(positions),
            "liquidity": compute_liquidity(positions, claims_by_pos, pv["capacity"]),
            "volatility": portfolio_volatility({k: v for k, v in series.items()}, values, total),
            "correlation_clusters": {"status": "unsupported", "reason": "not built yet; needs aligned adjusted history and a shrinkage method"},
            "not_computed": ["factor exposures", "probabilistic goal outcomes", "fund look-through"],
            "limitations": ["weights are concentrations of value, not independent risk factors",
                            "unmatched, unvalued and fund holdings stay in explicit unknown buckets"],
        }

    inputs = {"state": str(state.id), "valuation": str(valuation.id), "candles": digest, "capacity_policy": pv["capacity"]["policy_version"],
              "outgo": pv["capacity"]["monthly_essential_outgo"], "obligations": pv["capacity"]["near_term_obligations_12m"],
              "claims": {k: str(v) for k, v in sorted(claims_by_pos.items())}}
    run, created = await _get_or_create(db, kind="risk", state_id=state.id, valuation_id=valuation.id, method=RISK_METHOD,
                                        inputs_hash=_hash(inputs), params={}, result_fn=compute)
    return _payload(run, created)


@router.get("/scenarios/catalog")
async def scenario_catalog():
    return {"version": SCENARIO_METHOD, "scenarios": CATALOG,
            "custom": {"kinds": ["broad_equity", "sector"], "shock_range": [str(stress_mod.MIN_SHOCK), str(stress_mod.MAX_SHOCK)]},
            "note": "Illustrations under stated assumptions; a broad-market and a sector shock are separate scenarios and are never stacked."}


class ScenarioIn(BaseModel):
    state_id: uuid.UUID
    valuation_id: uuid.UUID
    scenario: dict


@router.post("/scenarios/evaluate")
async def evaluate_scenario(payload: ScenarioIn, db: AsyncSession = Depends(get_db)):
    state = (await db.execute(select(PortfolioState).where(PortfolioState.id == payload.state_id,
                                                           PortfolioState.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    valuation = await db.get(ValuationSnapshot, payload.valuation_id)
    if state is None or valuation is None or valuation.state_id != state.id:
        raise HTTPException(404, "state/valuation not found, or the valuation does not belong to that state")
    try:
        scn = resolve_scenario(payload.scenario)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc))
    positions = await twin_positions(db, state, valuation)
    params = {k: scn.get(k) for k in ("id", "kind", "sector", "shock")}
    run, created = await _get_or_create(db, kind="scenario", state_id=state.id, valuation_id=valuation.id, method=SCENARIO_METHOD,
                                        inputs_hash=_hash({"params": params}), params=params,
                                        result_fn=lambda: run_scenario(scn, positions))
    return _payload(run, created)


@router.get("/analysis/{analysis_id}")
async def replay_analysis(analysis_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    run = (await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id, AnalysisRun.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "analysis not found")
    return _payload(run)
