"""Deduplicated issue inbox (plan sections 6, 7). One row per issue FINGERPRINT;
quote churn or repeated reviews never create a second row. Lifecycle:

  open -> snoozed (until a date) | dismissed (with a reason) | resolved (condition gone)

A dismissed issue is remembered: it stays dismissed (even if the condition goes
away and comes back) unless the issue becomes MATERIALLY worse than when it was
dismissed (higher severity, or a measure that grew by a clear margin). A
snoozed issue returns when the snooze date passes. A resolved issue that
reappears is reopened (and counted). Called inside the publication transaction."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decisions import DecisionOutcome
from app.models.living import InboxIssue

SEV_RANK = {"information": 0, "review": 1, "urgent": 2}
MATERIAL_WEIGHT_GROWTH = Decimal("0.05")  # +5 percentage points for weights; +1 for counts (see below)


def is_material(row: InboxIssue, severity: str, measure: Decimal | None) -> bool:
    if SEV_RANK[severity] > SEV_RANK.get(row.dismissed_severity or "information", 0):
        return True
    if measure is not None and row.dismissed_measure is not None:
        growth = measure - row.dismissed_measure
        return growth >= (Decimal(1) if row.dismissed_measure >= 1 else MATERIAL_WEIGHT_GROWTH)
    return False


async def sync_inbox(db: AsyncSession, user_id: uuid.UUID, outcome: DecisionOutcome, now: datetime) -> dict:
    rows = (await db.execute(select(InboxIssue).where(InboxIssue.user_id == user_id)
                             .with_for_update().execution_options(populate_existing=True))).scalars().all()
    existing = {r.fingerprint: r for r in rows}
    seen: set[str] = set()
    stats = {"created": 0, "updated": 0, "reopened": 0, "resolved": 0}
    today = now.date()
    for it in outcome.result.get("issues", []):
        fp = it.get("fingerprint") or it["kind"]  # outcomes published before Phase 08 carry no fingerprint
        seen.add(fp)
        measure = None if it.get("measure") is None else Decimal(str(it["measure"]))
        row = existing.get(fp)
        if row is None:
            db.add(InboxIssue(user_id=user_id, fingerprint=fp, kind=it["kind"], severity=it["severity"], title=it["title"],
                              detail=it["detail"], measure=measure, status="open", first_seen_at=now, last_seen_at=now,
                              last_outcome_id=outcome.id, state_version_seen=outcome.state_version, reopen_count=0, version=1))
            stats["created"] += 1
            continue
        row.last_seen_at, row.last_outcome_id, row.state_version_seen = now, outcome.id, outcome.state_version
        row.title, row.detail, row.kind = it["title"], it["detail"], it["kind"]
        prev_severity = row.severity
        row.severity, row.measure = it["severity"], measure
        if row.status == "resolved":
            row.status, row.resolved_at = "open", None
            row.reopen_count += 1
            stats["reopened"] += 1
        elif row.status == "snoozed" and (row.snooze_until is None or row.snooze_until <= today):
            row.status, row.snooze_until = "open", None
            stats["reopened"] += 1
        elif row.status == "dismissed" and is_material(row, it["severity"], measure):
            row.status = "open"
            row.reopen_count += 1
            stats["reopened"] += 1
        else:
            stats["updated"] += 1
        row.version += 1
    for fp, row in existing.items():
        if row.kind in EXTERNALLY_OWNED_KINDS:  # owned by the watchlist refresh / the nightly signal pass, not by reviews
            continue
        # A dismissed issue is NOT auto-resolved: its dismissal is remembered if it returns.
        if fp not in seen and row.status in ("open", "snoozed"):
            row.status, row.resolved_at = "resolved", now
            row.version += 1
            stats["resolved"] += 1
    return stats


# Issue kinds raised and cleared by other processes. A review must never resolve them (it would close and the next pass reopen them,
# bumping reopen_count and flapping the inbox).
EXTERNALLY_OWNED_KINDS = frozenset({"watch_alert", "signal_change"})


class InboxError(ValueError):
    pass


async def get_issue(db: AsyncSession, user_id: uuid.UUID, issue_id: uuid.UUID) -> InboxIssue | None:
    return (await db.execute(select(InboxIssue).where(InboxIssue.id == issue_id, InboxIssue.user_id == user_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


def dismiss(row: InboxIssue, reason: str, now: datetime) -> None:
    if not reason.strip():
        raise InboxError("a dismissal needs a reason (it is remembered so the issue is not re-raised without new evidence)")
    row.status, row.dismissed_reason, row.dismissed_at = "dismissed", reason.strip()[:300], now
    row.dismissed_measure, row.dismissed_severity = row.measure, row.severity
    row.snooze_until = None
    row.version += 1


def snooze(row: InboxIssue, until: date, today: date) -> None:
    if until <= today:
        raise InboxError("snooze until a future date")
    row.status, row.snooze_until = "snoozed", until
    row.version += 1


def reopen(row: InboxIssue) -> None:
    if row.status == "open":
        raise InboxError("already open")
    row.status, row.snooze_until = "open", None
    row.reopen_count += 1
    row.version += 1


async def raise_external(db: AsyncSession, user_id: uuid.UUID, *, fingerprint: str, kind: str, severity: str, title: str, detail: str,
                         measure: Decimal | None, now: datetime) -> str:
    """For issues owned by something other than a review (e.g. a watchlist alert). Same lifecycle rules:
    a dismissed item stays dismissed, a snoozed one returns after its date, a resolved one reopens."""
    row = (await db.execute(select(InboxIssue).where(InboxIssue.user_id == user_id, InboxIssue.fingerprint == fingerprint)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        db.add(InboxIssue(user_id=user_id, fingerprint=fingerprint, kind=kind, severity=severity, title=title, detail=detail, measure=measure,
                          status="open", first_seen_at=now, last_seen_at=now, reopen_count=0, version=1))
        return "created"
    row.last_seen_at, row.title, row.detail, row.measure = now, title, detail, measure
    row.version += 1
    if row.status == "resolved":
        row.status, row.resolved_at = "open", None
        row.reopen_count += 1
        return "reopened"
    if row.status == "snoozed" and (row.snooze_until is None or row.snooze_until <= now.date()):
        row.status, row.snooze_until = "open", None
        return "reopened"
    return "updated"


async def clear_external(db: AsyncSession, user_id: uuid.UUID, fingerprint: str, now: datetime) -> bool:
    row = (await db.execute(select(InboxIssue).where(InboxIssue.user_id == user_id, InboxIssue.fingerprint == fingerprint)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is not None and row.status in ("open", "snoozed"):
        row.status, row.resolved_at = "resolved", now
        row.version += 1
        return True
    return False
