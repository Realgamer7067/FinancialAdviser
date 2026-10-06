"""Worker-only side effects of the suggestion view: inbox issues (state-based, information severity only) and the immutable log.

- An issue is raised while its condition holds and cleared only when the condition clears (the detectors already have hysteresis, so
  clearing means the price crossed back by a margin). Reviews never touch these (see EXTERNALLY_OWNED_KINDS).
- A dismissed issue stays dismissed: `raise_external` never reopens it.
- One log row per (fingerprint, trigger date), first-seen time kept separately from the trigger date."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.single_user import SINGLE_USER_ID
from app.models.living import InboxIssue
from app.models.securities import SuggestionLog
from app.portfolio_intelligence.decisions.inbox import clear_external, raise_external
from app.portfolio_intelligence.suggestions import detect as D

KIND = "signal_change"


def fingerprint(obs_kind: str, security_id: str) -> str:
    return f"{KIND}:{obs_kind}:{security_id}"


async def persist_suggestions(db: AsyncSession, built: dict, now: datetime, user_id=SINGLE_USER_ID) -> dict:
    active: set[str] = set()
    stats = {"raised": 0, "updated": 0, "reopened": 0, "cleared": 0, "logged": 0}
    seen_items = {}
    for item in built["held"] + built["watched"]:
        seen_items[item["security_id"]] = item
    for sid, item in seen_items.items():
        for obs in item["observations"]:
            fp = fingerprint(obs["kind"], sid)
            active.add(fp)
            res = await raise_external(db, user_id, fingerprint=fp, kind=KIND, severity="information", title=obs["title"], detail=obs["detail"],
                                       measure=None if obs["measure"] is None else Decimal(str(obs["measure"])), now=now)
            stats["raised" if res == "created" else "reopened" if res == "reopened" else "updated"] += 1
            trigger = date.fromisoformat(obs["since"]) if obs["since"] else date.fromisoformat(item["signal_as_of"])
            exists = (await db.execute(select(SuggestionLog.id).where(SuggestionLog.user_id == user_id, SuggestionLog.fingerprint == fp, SuggestionLog.trigger_date == trigger))).first()
            if exists is None:
                db.add(SuggestionLog(user_id=user_id, fingerprint=fp, kind=obs["kind"], security_id=uuid.UUID(sid), context=item["context"], trigger_date=trigger,
                                     as_of_date=date.fromisoformat(item["signal_as_of"]), method_version=D.METHOD_VERSION, origin="live",
                                     signal_input_marker=item.get("signal_input_marker"),
                                     metrics={"measure": obs["measure"], "sessions_since": obs["sessions_since"], "attention": obs["attention"], "title": obs["title"],
                                              "changes_1y": obs.get("changes_1y"), "raw_crossings_1y": obs.get("raw_crossings_1y"), "policy_version": D.POLICY_VERSION},
                                     logged_at=now))
                try:
                    await db.flush()
                    stats["logged"] += 1
                except IntegrityError:
                    await db.rollback()
    rows = (await db.execute(select(InboxIssue).where(InboxIssue.user_id == user_id, InboxIssue.kind == KIND, InboxIssue.status.in_(("open", "snoozed"))))).scalars().all()
    for row in rows:
        if row.fingerprint not in active and await clear_external(db, user_id, row.fingerprint, now):
            stats["cleared"] += 1
    await db.commit()
    return stats
