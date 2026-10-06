"""/api/v4/system/freshness: what is held, how old it is, and what will happen next, from stored facts only."""

from datetime import date, datetime, timezone

from app.models.securities import MarketHoliday
from app.portfolio_intelligence.market import calendar as cal
from app.api.v4 import freshness as F


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_next_update_and_last_closed_session_follow_the_calendar(monkeypatch):
    cal.set_holidays({date(2026, 10, 2): "Mahatma Gandhi Jayanti"}, {2026})
    try:
        # Thu 1 Oct 2026, 17:38 IST: after the close, so Thursday is the last closed session and the next run is Monday 5 Oct (Fri is a holiday)
        now = _utc(2026, 10, 1, 12, 8)
        assert F._last_closed_session(now) == date(2026, 10, 1)
        assert F._next_close(now)[0] == date(2026, 10, 5)
        # Fri 2 Oct (holiday), 13:00 IST: nothing runs today; Thursday is still the last session; next is Monday
        now = _utc(2026, 10, 2, 7, 30)
        assert F._last_closed_session(now) == date(2026, 10, 1) and F._next_close(now)[0] == date(2026, 10, 5)
        # Mon 5 Oct, 10:00 IST: the close is still ahead today
        now = _utc(2026, 10, 5, 4, 30)
        assert F._next_close(now)[0] == date(2026, 10, 5) and F._last_closed_session(now) == date(2026, 10, 1)
        # Mon 5 Oct, 16:30 IST: Monday has closed
        now = _utc(2026, 10, 5, 11, 0)
        assert F._last_closed_session(now) == date(2026, 10, 5) and F._next_close(now)[0] == date(2026, 10, 6)
    finally:
        cal.set_holidays({}, set())


async def test_endpoint_reports_each_dataset_honestly_when_nothing_has_run(client, db_session):
    r = (await client.get("/api/v4/system/freshness")).json()
    keys = {i["key"]: i for i in r["items"]}
    assert set(keys) == {"prices", "history", "signals", "forecasts", "nav", "costs", "catalogue", "fundamentals", "holidays", "holdings"}
    assert keys["prices"]["state"] == "no_data" and keys["history"]["state"] == "no_data" and keys["forecasts"]["last_update"] is None
    assert keys["prices"]["needs_broker_session"] is True and keys["nav"]["needs_broker_session"] is False
    assert r["market"]["next_update"] and "reconnect" in r["broker_session"]["daily_reconnect"]
    assert r["scheduler"]["last_daily_close"] is None


async def test_fundamentals_item_and_manual_refresh_queue_once(client):
    r = (await client.get("/api/v4/system/freshness")).json()
    item = next(i for i in r["items"] if i["key"] == "fundamentals")
    assert item["state"] == "no_data" and item["needs_broker_session"] is False
    first = (await client.post("/api/v4/system/fundamentals/refresh")).json()
    second = (await client.post("/api/v4/system/fundamentals/refresh")).json()
    assert first == {"queued": True, "already_queued": False} and second == {"queued": False, "already_queued": True}
