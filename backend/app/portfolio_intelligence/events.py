"""Typed change events (plan section 6). Duplicates coalesce on the dedup key,
so a burst of identical triggers is one row. The dependency chain these feed:

  import -> state -> valuation -> exposures -> risk/goals -> decision

Artifacts are keyed by the state/valuation ids they were computed from, so a
change invalidates only what is downstream of it; a price-only valuation does
not change the state or the economics that depend on it."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.living import PortfolioEvent
from app.utils.time import utcnow


async def record_event(db: AsyncSession, user_id: uuid.UUID, kind: str, *, dedup_key: str, source_id: str | None = None,
                       affected: dict | None = None, occurred_at=None) -> bool:
    """Returns True if a NEW event was stored. Never raises into the caller's transaction path."""
    now = utcnow()
    if (await db.execute(select(PortfolioEvent.id).where(PortfolioEvent.user_id == user_id, PortfolioEvent.dedup_key == dedup_key))).first():
        return False
    db.add(PortfolioEvent(user_id=user_id, kind=kind, source_id=source_id, dedup_key=dedup_key, affected=affected or {},
                          occurred_at=occurred_at or now, received_at=now))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False
    return True
