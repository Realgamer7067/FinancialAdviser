"""Watchlist alerts. Evaluated whenever quotes refresh; state-based (a condition
that stays true is ONE inbox item that updates, not a stream of notifications),
and the item resolves itself when the condition clears. Alerts are information
for the owner; they never trade, never change a review outcome and never imply
a recommendation."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.watchlist import BrokerInstrument, MarketQuote, WatchAlert, Watchlist, WatchlistItem
from app.portfolio_intelligence.decisions.inbox import clear_external, raise_external
from app.portfolio_intelligence.market.quotes import quote_freshness

KINDS = ("price_above", "price_below", "day_move_up", "day_move_down")


def describe(kind: str, threshold: Decimal) -> str:
    t = format(threshold.normalize(), "f")
    return {"price_above": f"is at or above ₹{t}", "price_below": f"is at or below ₹{t}",
            "day_move_up": f"is up {t}% or more today", "day_move_down": f"is down {t}% or more today"}[kind]


def condition(kind: str, threshold: Decimal, ltp: Decimal, percent_change: Decimal | None) -> bool | None:
    """None when the needed data is missing (never guessed true)."""
    if kind == "price_above":
        return ltp >= threshold
    if kind == "price_below":
        return ltp <= threshold
    if percent_change is None:
        return None
    return percent_change >= threshold if kind == "day_move_up" else percent_change <= -threshold


async def evaluate_alerts(db: AsyncSession, user_id, now: datetime) -> dict:
    rows = (await db.execute(
        select(WatchAlert, WatchlistItem, BrokerInstrument, MarketQuote)
        .join(WatchlistItem, WatchlistItem.id == WatchAlert.item_id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .join(BrokerInstrument, BrokerInstrument.id == WatchlistItem.broker_instrument_id)
        .join(MarketQuote, MarketQuote.broker_instrument_id == BrokerInstrument.id)
        .where(Watchlist.user_id == user_id, WatchAlert.active.is_(True)))).all()
    stats = {"evaluated": 0, "triggered": 0, "cleared": 0}
    for alert, item, bi, q in rows:
        met = condition(alert.kind, alert.threshold, q.ltp, q.percent_change)
        if met is None:
            continue
        stats["evaluated"] += 1
        fp = f"watch_alert:{alert.id}"
        if met:
            alert.triggered, alert.last_triggered_at = True, now
            fresh = quote_freshness(q.retrieved_at, now)
            await raise_external(
                db, user_id, fingerprint=fp, kind="watch_alert", severity="information",
                title=f"{bi.symbol} {describe(alert.kind, alert.threshold)}",
                detail=f"Last price ₹{format(q.ltp.normalize(), 'f')} ({'live' if fresh == 'live' else 'last session' if fresh == 'last_session' else 'a little delayed'}). "
                       "This is your own alert, not a recommendation.", measure=q.ltp, now=now)
            stats["triggered"] += 1
        else:
            alert.triggered = False
            if await clear_external(db, user_id, fp, now):
                stats["cleared"] += 1
    await db.commit()
    return stats
