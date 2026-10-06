"""Issue inbox and recent events (Portfolio Intelligence Engine Phase 08).
Items are deduplicated by issue fingerprint; every change is an
expected-version update (409 on a stale one)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.living import InboxIssue, PortfolioEvent
from app.portfolio_intelligence.decisions import inbox as inbox_mod
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-inbox"])

CATEGORY = {"urgent": "urgent", "review": "review", "information": "information"}


def issue_out(r: InboxIssue) -> dict:
    cat = "resolved" if r.status == "resolved" else CATEGORY[r.severity]
    return {"id": str(r.id), "fingerprint": r.fingerprint, "kind": r.kind, "category": cat, "severity": r.severity, "title": r.title,
            "detail": r.detail, "status": r.status, "first_seen_at": r.first_seen_at.isoformat(), "last_seen_at": r.last_seen_at.isoformat(),
            "snooze_until": r.snooze_until.isoformat() if r.snooze_until else None, "dismissed_reason": r.dismissed_reason,
            "reopen_count": r.reopen_count, "version": r.version,
            "decision_id": None if r.last_outcome_id is None else str(r.last_outcome_id)}


@router.get("/inbox")
async def list_inbox(status: str | None = None, db: AsyncSession = Depends(get_db)):
    """Default view: open issues, most severe first. `status` = open|snoozed|dismissed|resolved|all."""
    rows = (await db.execute(select(InboxIssue).where(InboxIssue.user_id == SINGLE_USER_ID))).scalars().all()
    today = date.today()
    # A snooze that has passed is shown as open immediately (the next review also persists it).
    def effective(r: InboxIssue) -> str:
        return "open" if r.status == "snoozed" and r.snooze_until is not None and r.snooze_until <= today else r.status
    want = status or "open"
    pick = [r for r in rows if want == "all" or effective(r) == want]
    order = {"urgent": 0, "review": 1, "information": 2}
    pick.sort(key=lambda r: (order[r.severity], r.first_seen_at))
    counts = {s: sum(1 for r in rows if effective(r) == s) for s in ("open", "snoozed", "dismissed", "resolved")}
    return {"counts": counts, "items": [{**issue_out(r), "status": effective(r)} for r in pick]}


class DismissIn(BaseModel):
    expected_version: int
    reason: str = Field(min_length=1, max_length=300)


class SnoozeIn(BaseModel):
    expected_version: int
    until: date


class VersionIn(BaseModel):
    expected_version: int


async def _load(db: AsyncSession, issue_id: uuid.UUID, expected: int) -> InboxIssue:
    row = await inbox_mod.get_issue(db, SINGLE_USER_ID, issue_id)
    if row is None:
        raise HTTPException(404, "inbox item not found")
    if row.version != expected:
        raise HTTPException(409, f"stale version: item is at version {row.version}")
    return row


@router.post("/inbox/{issue_id}/dismiss")
async def dismiss_issue(issue_id: uuid.UUID, payload: DismissIn, db: AsyncSession = Depends(get_db)):
    row = await _load(db, issue_id, payload.expected_version)
    try:
        inbox_mod.dismiss(row, payload.reason, utcnow())
    except inbox_mod.InboxError as exc:
        raise HTTPException(422, str(exc))
    await db.commit()
    return issue_out(row)


@router.post("/inbox/{issue_id}/snooze")
async def snooze_issue(issue_id: uuid.UUID, payload: SnoozeIn, db: AsyncSession = Depends(get_db)):
    row = await _load(db, issue_id, payload.expected_version)
    try:
        inbox_mod.snooze(row, payload.until, date.today())
    except inbox_mod.InboxError as exc:
        raise HTTPException(422, str(exc))
    await db.commit()
    return issue_out(row)


@router.post("/inbox/{issue_id}/reopen")
async def reopen_issue(issue_id: uuid.UUID, payload: VersionIn, db: AsyncSession = Depends(get_db)):
    row = await _load(db, issue_id, payload.expected_version)
    try:
        inbox_mod.reopen(row)
    except inbox_mod.InboxError as exc:
        raise HTTPException(422, str(exc))
    await db.commit()
    return issue_out(row)


@router.get("/events")
async def recent_events(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PortfolioEvent).where(PortfolioEvent.user_id == SINGLE_USER_ID)
                             .order_by(PortfolioEvent.received_at.desc()).limit(20))).scalars().all()
    return [{"kind": e.kind, "occurred_at": e.occurred_at.isoformat(), "received_at": e.received_at.isoformat(), "affected": e.affected} for e in rows]
