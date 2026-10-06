"""Allocation-claim logic (plan sections 4, 12.2, Phase 04).

A claim is rupees on an ACCOUNT-SPECIFIC holding key (account + asset type +
identifier), never a ticker alone and never a row id. Invariants:
- the sum of claims (active AND needs_review, i.e. reserved conservatively) on
  one holding never exceeds that holding's known current value;
- a claim is never moved to another account because ticker text matches;
- needs_review is sticky: the system flags it, only the user clears it."""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import PositionObservation, SourceAccount
from app.models.goals_v4 import GoalAllocation
from app.models.market import Instrument
from app.models.twin import PortfolioPosition
from app.portfolio_intelligence.goals.store import latest_allocations
from app.portfolio_intelligence.state.build import latest_state, latest_valuation
from app.utils.time import utcnow


def holding_key(account_id: uuid.UUID, asset_type: str, identifier: str) -> str:
    payload = json.dumps({"account": str(account_id), "asset_type": asset_type, "identifier": identifier.strip().lower()},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def monthly_equivalent(amount: Decimal, frequency: str) -> Decimal:
    return {"monthly": amount, "quarterly": amount / 3, "annual": amount / 12}[frequency]


@dataclass
class HoldingInfo:
    key: str
    account_id: uuid.UUID
    account_label: str
    label: str
    asset_type: str
    value: Decimal | None  # None if ANY matching position has no value
    position_ids: list[str] = field(default_factory=list)


async def current_holding_values(db: AsyncSession, user_id: uuid.UUID) -> dict[str, HoldingInfo]:
    state = await latest_state(db, user_id)
    if state is None:
        return {}
    val = await latest_valuation(db, state.id)
    sel = {s["position_id"]: s for s in (val.selections if val else [])}
    labels = {a["account_id"]: a["label"] for a in state.account_inputs}
    rows = (await db.execute(select(PortfolioPosition, PositionObservation)
                             .join(PositionObservation, PositionObservation.id == PortfolioPosition.observation_id)
                             .where(PortfolioPosition.state_id == state.id))).all()
    inst_ids = {o.instrument_id for _, o in rows if o.instrument_id}
    symbols = {i.id: i.symbol for i in (await db.execute(select(Instrument).where(Instrument.id.in_(inst_ids)))).scalars()} if inst_ids else {}
    out: dict[str, HoldingInfo] = {}
    for pos, o in rows:
        ident = (o.isin or o.symbol or o.raw_identifier or "")
        key = holding_key(pos.source_account_id, o.asset_type, ident)
        s = sel.get(str(pos.id))
        v = None if s is None or s["value"] is None else Decimal(s["value"])
        info = out.get(key)
        if info is None:
            out[key] = HoldingInfo(key, pos.source_account_id, labels.get(str(pos.source_account_id), "?"),
                                   symbols.get(o.instrument_id) or o.raw_identifier or ident, o.asset_type, v, [str(pos.id)])
        else:
            info.position_ids.append(str(pos.id))
            info.value = None if info.value is None or v is None else info.value + v
    return out


async def lock_holding(db: AsyncSession, key: str) -> None:
    """Serialize concurrent claims on one holding (Postgres only; SQLite has no
    concurrent writers to guard against)."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": key})


def claimed_total(allocations: list[GoalAllocation], key: str, exclude_chain: uuid.UUID | None = None) -> Decimal:
    return sum((a.amount for a in allocations
                if a.holding_key == key and a.chain_id != exclude_chain and a.status in ("active", "needs_review")), Decimal(0))


def _new_revision(prev: GoalAllocation, *, status: str, reason: str | None, amount: Decimal | None = None) -> GoalAllocation:
    return GoalAllocation(
        user_id=prev.user_id, chain_id=prev.chain_id, version=prev.version + 1, goal_chain_id=prev.goal_chain_id,
        source_account_id=prev.source_account_id, holding_key=prev.holding_key, holding_label=prev.holding_label,
        amount=prev.amount if amount is None else amount, status=status, reason=reason, created_at=utcnow())


async def reconcile_allocations(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Re-check every live claim against the current twin. Writes a NEW revision
    (active -> needs_review) only on a problem; returns how many were written.
    A holding that disappears, loses its value or falls below the total claimed
    flags ALL claims on it (conservative); nothing is released or moved."""
    allocations = await latest_allocations(db, user_id)
    if not allocations:
        return 0
    values = await current_holding_values(db, user_id)
    included = {a.id for a in (await db.execute(select(SourceAccount).where(
        SourceAccount.user_id == user_id, SourceAccount.included.is_(True)))).scalars()}
    by_key: dict[str, list[GoalAllocation]] = {}
    for a in allocations:
        by_key.setdefault(a.holding_key, []).append(a)
    written = 0
    for key, claims in by_key.items():
        info = values.get(key)
        reason = None
        if info is None or claims[0].source_account_id not in included:
            reason = "holding_not_found"
        elif info.value is None:
            reason = "value_unknown"
        elif sum((c.amount for c in claims), Decimal(0)) > info.value:
            reason = "value_below_claims"
        if reason is None:
            continue
        for c in claims:
            if c.status == "active":
                db.add(_new_revision(c, status="needs_review", reason=reason))
                written += 1
    if written:
        await db.commit()
    return written
