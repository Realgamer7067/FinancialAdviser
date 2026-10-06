"""Portfolio Twin construction (plan sections 4, 12.2).

State = latest COMPLETE import of every INCLUDED account, the coverage
attestation, and (later phases) bound profile/goal versions. Its economic hash
covers identities/units/ownership only, never prices or timestamps, so a
price-only refresh yields a new ValuationSnapshot on the SAME state.

Valuation policy v1 (per-asset, dated, never invented):
- units-based listed rows: source-reported value (broker LTP x units at
  retrieval time, or user-entered); fresh if <= 5 calendar days old.
- value-only rows (deposit/gold/cash/other/unclassified): user-dated value;
  stale after 90 days.
- No value => value stays None (unknown), never 0."""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import AccountCoverageAttestation, PositionObservation, SourceAccount, SourceImport
from app.models.personal import FinancialProfileRevision, LiabilityRevision, PreferenceRevision
from app.models.goals_v4 import CommitmentRevision, GoalAllocation, GoalRevision
from app.portfolio_intelligence.goals.store import latest_allocations, latest_commitments, latest_goals
from app.models.twin import PortfolioPosition, PortfolioState, ValuationSnapshot
from app.utils.time import utcnow
from app.portfolio_intelligence.state.catalogue_identity import effective_identity, unique_catalogue_isins

logger = logging.getLogger("twin")

NORMALIZATION_VERSION = "twin-norm-v3"
PRICE_POLICY_VERSION = "pv1"
UNITS_FRESH_DAYS = 5
VALUE_ONLY_STALE_DAYS = 90
UNRESOLVED = ("unresolved", "ambiguous")


def _s(v) -> str | None:
    return None if v is None else str(Decimal(str(v)).normalize())


def economic_key(o: PositionObservation, account_id: uuid.UUID) -> dict:
    """Economics only. Value participates only when there are no units (a
    value-only holding IS its value); for unit-based rows price is valuation."""
    return {
        "account": str(account_id),
        "asset_type": o.asset_type,
        "identifier": (o.isin or o.symbol or o.raw_identifier or "").strip().lower(),
        "instrument": None if o.instrument_id is None else str(o.instrument_id),
        "resolution": o.resolution,
        "units": _s(o.units),
        "value_if_no_units": _s(o.value) if o.units is None else None,
        "cost_basis": _s(o.cost_basis),
        "locked": bool(o.locked),
        "ownership": o.ownership,
    }


def economic_hash(rows: list[dict], included_account_ids: list[uuid.UUID], attestation_id: uuid.UUID | None,
                  profile_id: uuid.UUID | None = None, liability_ids: list[uuid.UUID] | None = None,
                  preference_ids: list[uuid.UUID] | None = None, goal_ids: list[uuid.UUID] | None = None,
                  allocation_ids: list[uuid.UUID] | None = None, commitment_ids: list[uuid.UUID] | None = None) -> str:
    payload = {
        "norm": NORMALIZATION_VERSION,
        "accounts": sorted(str(a) for a in included_account_ids),
        "attestation": None if attestation_id is None else str(attestation_id),
        "profile": None if profile_id is None else str(profile_id),
        "liabilities": sorted(str(x) for x in (liability_ids or [])),
        "preferences": sorted(str(x) for x in (preference_ids or [])),
        "goals": sorted(str(x) for x in (goal_ids or [])),
        "allocations": sorted(str(x) for x in (allocation_ids or [])),
        "commitments": sorted(str(x) for x in (commitment_ids or [])),
        "rows": sorted(json.dumps(r, sort_keys=True) for r in rows),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def select_value(o: PositionObservation, position_id: uuid.UUID, source_type: str, retrieved_at: datetime, cutoff: datetime) -> dict:
    """Pure per-position valuation selection under policy pv1."""
    if o.value is None:
        return {"position_id": str(position_id), "observation_id": str(o.id), "value": None, "source": None,
                "as_of": o.valuation_date.isoformat(), "retrieved_at": retrieved_at.isoformat(), "quality": "unvalued"}
    age = (cutoff.date() - o.valuation_date).days
    limit = UNITS_FRESH_DAYS if o.units is not None else VALUE_ONLY_STALE_DAYS
    if o.units is not None:
        source = "broker_ltp_x_units" if source_type == "angel_one" else "user_entered_value"
    else:
        source = "user_reported_value"
    return {"position_id": str(position_id), "observation_id": str(o.id), "value": str(o.value), "source": source,
            "as_of": o.valuation_date.isoformat(), "retrieved_at": retrieved_at.isoformat(),
            "quality": "fresh" if age <= limit else "stale"}


def observation_set_hash(selections: list[dict]) -> str:
    core = sorted((s["position_id"], s["value"], s["as_of"]) for s in selections)
    return hashlib.sha256(json.dumps([PRICE_POLICY_VERSION, core]).encode()).hexdigest()


def valuation_coverage(selections: list[dict], resolution_by_pos: dict[str, str]) -> tuple[Decimal, int, dict]:
    known = [(Decimal(s["value"]), s) for s in selections if s["value"] is not None]
    total = sum((v for v, _ in known), Decimal(0))
    unknown = len(selections) - len(known)
    if total > 0:
        resolved = sum((v for v, s in known if resolution_by_pos[s["position_id"]] not in UNRESOLVED), Decimal(0))
        fresh = sum((v for v, s in known if s["quality"] == "fresh"), Decimal(0))
        resolved_share, fresh_share = str((resolved / total).quantize(Decimal("0.0001"))), str((fresh / total).quantize(Decimal("0.0001")))
    else:
        resolved_share = fresh_share = None
    dates = sorted(s["as_of"] for s in selections)
    cov = {
        "position_count": len(selections),
        "valued_count": len(known),
        "identity_resolved_value_share": resolved_share,
        "fresh_value_share": fresh_share,
        "earliest_as_of": dates[0] if dates else None,
        "latest_as_of": dates[-1] if dates else None,
        "price_policy": PRICE_POLICY_VERSION,
    }
    return total, unknown, cov


@dataclass
class Inputs:
    accounts: list[SourceAccount]  # included, ordered
    imports: dict[uuid.UUID, SourceImport | None]  # account_id -> latest complete import
    observations: dict[uuid.UUID, list[PositionObservation]]  # account_id -> rows
    attestation: AccountCoverageAttestation | None
    profile: FinancialProfileRevision | None = None
    liabilities: list[LiabilityRevision] | None = None
    preferences: list[PreferenceRevision] | None = None
    goals: list[GoalRevision] | None = None
    allocations: list[GoalAllocation] | None = None
    commitments: list[CommitmentRevision] | None = None


async def latest_profile(db: AsyncSession, user_id: uuid.UUID) -> FinancialProfileRevision | None:
    return (await db.execute(select(FinancialProfileRevision).where(FinancialProfileRevision.user_id == user_id)
                             .order_by(FinancialProfileRevision.version.desc()).limit(1))).scalar_one_or_none()


async def active_liabilities(db: AsyncSession, user_id: uuid.UUID) -> list[LiabilityRevision]:
    """Latest revision per chain, excluding closed ones."""
    rows = (await db.execute(select(LiabilityRevision).where(LiabilityRevision.user_id == user_id)
                             .order_by(LiabilityRevision.chain_id, LiabilityRevision.version.desc()))).scalars().all()
    latest: dict = {}
    for r in rows:
        latest.setdefault(r.chain_id, r)
    return sorted((r for r in latest.values() if r.status == "active"), key=lambda r: str(r.chain_id))


async def active_preferences(db: AsyncSession, user_id: uuid.UUID) -> list[PreferenceRevision]:
    rows = (await db.execute(select(PreferenceRevision).where(PreferenceRevision.user_id == user_id)
                             .order_by(PreferenceRevision.chain_id, PreferenceRevision.version.desc()))).scalars().all()
    latest: dict = {}
    for r in rows:
        latest.setdefault(r.chain_id, r)
    today = date.today()
    return sorted((r for r in latest.values() if r.status == "active" and (r.expires_on is None or r.expires_on >= today)),
                  key=lambda r: str(r.chain_id))


async def load_inputs(db: AsyncSession, user_id: uuid.UUID) -> Inputs:
    accounts = (
        (await db.execute(select(SourceAccount).where(SourceAccount.user_id == user_id, SourceAccount.included.is_(True))
                          .order_by(SourceAccount.created_at, SourceAccount.id)))
        .scalars().all()
    )
    imports: dict = {}
    obs: dict = {}
    for a in accounts:
        imp = (await db.execute(select(SourceImport).where(SourceImport.account_id == a.id, SourceImport.status == "complete")
                                .order_by(SourceImport.created_at.desc(), SourceImport.id.desc()).limit(1))).scalar_one_or_none()
        imports[a.id] = imp
        obs[a.id] = [] if imp is None else list((await db.execute(
            select(PositionObservation).where(PositionObservation.import_id == imp.id).order_by(PositionObservation.row_ordinal))).scalars())
    att = (await db.execute(select(AccountCoverageAttestation).where(AccountCoverageAttestation.user_id == user_id)
                            .order_by(AccountCoverageAttestation.version.desc()).limit(1))).scalar_one_or_none()
    return Inputs(list(accounts), imports, obs, att, await latest_profile(db, user_id),
                  await active_liabilities(db, user_id), await active_preferences(db, user_id),
                  await latest_goals(db, user_id), await latest_allocations(db, user_id),
                  await latest_commitments(db, user_id))


def hash_for_inputs(inp: Inputs) -> str:
    rows = [economic_key(o, a.id) for a in inp.accounts for o in inp.observations[a.id]]
    return economic_hash(rows, [a.id for a in inp.accounts], inp.attestation.id if inp.attestation else None,
                         inp.profile.id if inp.profile else None,
                         [l.id for l in inp.liabilities or []], [p.id for p in inp.preferences or []],
                         [g.id for g in inp.goals or []], [a.id for a in inp.allocations or []],
                         [c.id for c in inp.commitments or []])


async def latest_state(db: AsyncSession, user_id: uuid.UUID) -> PortfolioState | None:
    return (await db.execute(select(PortfolioState).where(PortfolioState.user_id == user_id)
                             .order_by(PortfolioState.version.desc()).limit(1))).scalar_one_or_none()


async def latest_valuation(db: AsyncSession, state_id: uuid.UUID) -> ValuationSnapshot | None:
    return (await db.execute(select(ValuationSnapshot).where(ValuationSnapshot.state_id == state_id)
                             .order_by(ValuationSnapshot.created_at.desc(), ValuationSnapshot.id.desc()).limit(1))).scalar_one_or_none()


@dataclass
class RefreshResult:
    state: PortfolioState | None
    valuation: ValuationSnapshot | None
    state_created: bool = False
    valuation_created: bool = False


async def refresh_state(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> RefreshResult:
    """Idempotent. New state only if the economic hash changed; otherwise at
    most a new valuation when observed values/dates changed. Returns the
    current state/valuation. No included accounts => no state."""
    now = now or utcnow()
    for attempt in (1, 2):
        inp = await load_inputs(db, user_id)
        if not inp.accounts:
            return RefreshResult(None, None)
        h = hash_for_inputs(inp)
        current = await latest_state(db, user_id)
        created_state = False
        try:
            pos_by_key: dict[str, list[uuid.UUID]] = {}
            if current is None or current.economic_hash != h:
                current = PortfolioState(
                    user_id=user_id, version=(current.version + 1) if current else 1, economic_hash=h,
                    normalization_version=NORMALIZATION_VERSION,
                    coverage_attestation_id=inp.attestation.id if inp.attestation else None,
                    profile_revision_id=inp.profile.id if inp.profile else None,
                    liability_revision_ids=[str(l.id) for l in inp.liabilities or []],
                    preference_revision_ids=[str(p.id) for p in inp.preferences or []],
                    goal_revision_ids=[str(g.id) for g in inp.goals or []],
                    allocation_revision_ids=[str(a.id) for a in inp.allocations or []],
                    commitment_revision_ids=[str(c.id) for c in inp.commitments or []],
                    account_inputs=[{
                        "account_id": str(a.id), "label": a.label, "source_type": a.source_type,
                        "import_id": None if inp.imports[a.id] is None else str(inp.imports[a.id].id),
                        "status": "no_import" if inp.imports[a.id] is None else "imported",
                        "position_count": len(inp.observations[a.id]),
                    } for a in inp.accounts],
                    created_at=now,
                )
                db.add(current)
                await db.flush()
                for a in inp.accounts:
                    for o in inp.observations[a.id]:
                        pid = uuid.uuid4()
                        db.add(PortfolioPosition(id=pid, state_id=current.id, observation_id=o.id, source_account_id=a.id,
                                                 import_id=inp.imports[a.id].id))  # type: ignore[union-attr]
                        pos_by_key.setdefault(json.dumps(economic_key(o, a.id), sort_keys=True), []).append(pid)
                created_state = True
            else:
                # Same economics: the state's positions stay bound to the observations they were built
                # from; a newer import (e.g. price-only sync) is matched onto them by economic key.
                rows = (await db.execute(
                    select(PortfolioPosition, PositionObservation)
                    .join(PositionObservation, PositionObservation.id == PortfolioPosition.observation_id)
                    .where(PortfolioPosition.state_id == current.id)
                    .order_by(PositionObservation.import_id, PositionObservation.row_ordinal))).all()
                for pos, o in rows:
                    pos_by_key.setdefault(json.dumps(economic_key(o, pos.source_account_id), sort_keys=True), []).append(pos.id)
            selections, res_by_pos = [], {}
            cat = await unique_catalogue_isins(db, {o.isin for a in inp.accounts for o in inp.observations[a.id] if o.resolution in UNRESOLVED and o.isin})
            for a in inp.accounts:
                imp = inp.imports[a.id]
                for o in inp.observations[a.id]:
                    pid = pos_by_key[json.dumps(economic_key(o, a.id), sort_keys=True)].pop(0)
                    selections.append(select_value(o, pid, a.source_type, imp.created_at, now))  # type: ignore[union-attr]
                    res_by_pos[str(pid)] = effective_identity(o.resolution, o.isin, cat)
            oh = observation_set_hash(selections)
            val = (await db.execute(select(ValuationSnapshot).where(
                ValuationSnapshot.state_id == current.id, ValuationSnapshot.observation_set_hash == oh,
                ValuationSnapshot.price_policy_version == PRICE_POLICY_VERSION))).scalar_one_or_none()
            created_val = False
            if val is None:
                total, unknown, cov = valuation_coverage(selections, res_by_pos)
                val = ValuationSnapshot(state_id=current.id, observation_set_hash=oh, price_policy_version=PRICE_POLICY_VERSION,
                                        cutoff=now, known_total=total, unknown_value_count=unknown, coverage=cov,
                                        selections=selections, created_at=now)
                db.add(val)
                created_val = True
            await db.commit()
            return RefreshResult(current, val, created_state, created_val)
        except IntegrityError:
            await db.rollback()
            if attempt == 2:
                raise
    raise RuntimeError("unreachable")


async def safe_refresh(db: AsyncSession, user_id: uuid.UUID) -> None:
    """For hooks after an import/sync/setting change: a twin refresh problem
    must never fail the user's original action (the next refresh retries).
    Callers MUST build their response before calling this: a failed refresh
    rolls back, which expires every ORM object held by the session."""
    try:
        res = await refresh_state(db, user_id)
        # Allocation claims are re-checked against the new twin; a status change is a
        # new bound revision, so the twin is refreshed once more (converges: idempotent).
        from app.portfolio_intelligence.goals.service import reconcile_allocations

        from app.portfolio_intelligence.events import record_event

        if res.state_created and res.state is not None:
            await record_event(db, user_id, "state_built", dedup_key=f"state:{res.state.id}", source_id=str(res.state.id),
                               affected={"state_id": str(res.state.id), "version": res.state.version})
        elif res.valuation_created and res.valuation is not None:
            await record_event(db, user_id, "valuation_published", dedup_key=f"valuation:{res.valuation.id}", source_id=str(res.valuation.id),
                               affected={"state_id": str(res.valuation.state_id)})
        created = res.state_created
        if await reconcile_allocations(db, user_id):
            created = created or (await refresh_state(db, user_id)).state_created
        if created:  # a new snapshot deserves a (bounded, cheap) review; reviews never run the legacy pipeline
            from app.portfolio_intelligence.decisions.runner import enqueue_review, kick_inline_reviews

            await enqueue_review(db, user_id)
            kick_inline_reviews()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("portfolio twin refresh failed")
