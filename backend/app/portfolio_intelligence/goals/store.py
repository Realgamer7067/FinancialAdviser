"""Latest-revision loaders for goal chains, allocation claims and commitments.
No dependency on the state builder (the builder imports this module)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goals_v4 import CommitmentRevision, GoalAllocation, GoalRevision


def _latest_per_chain(rows):
    latest: dict = {}
    for r in rows:  # ordered chain_id, version desc
        latest.setdefault(r.chain_id, r)
    return sorted(latest.values(), key=lambda r: str(r.chain_id))


async def latest_goals(db: AsyncSession, user_id: uuid.UUID, *, include_closed: bool = False) -> list[GoalRevision]:
    rows = (await db.execute(select(GoalRevision).where(GoalRevision.user_id == user_id)
                             .order_by(GoalRevision.chain_id, GoalRevision.version.desc()))).scalars().all()
    out = _latest_per_chain(rows)
    return out if include_closed else [g for g in out if g.status == "active"]


async def latest_allocations(db: AsyncSession, user_id: uuid.UUID, *, include_released: bool = False) -> list[GoalAllocation]:
    rows = (await db.execute(select(GoalAllocation).where(GoalAllocation.user_id == user_id)
                             .order_by(GoalAllocation.chain_id, GoalAllocation.version.desc()))).scalars().all()
    out = _latest_per_chain(rows)
    return out if include_released else [a for a in out if a.status != "released"]


async def latest_commitments(db: AsyncSession, user_id: uuid.UUID, *, include_ended: bool = False) -> list[CommitmentRevision]:
    rows = (await db.execute(select(CommitmentRevision).where(CommitmentRevision.user_id == user_id)
                             .order_by(CommitmentRevision.chain_id, CommitmentRevision.version.desc()))).scalars().all()
    out = _latest_per_chain(rows)
    return out if include_ended else [c for c in out if c.status != "ended"]
