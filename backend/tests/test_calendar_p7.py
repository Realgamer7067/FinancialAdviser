"""P7 holidays: the calendar applies holidays only for covered years, drives the last-session / market-status logic, and refreshes safely."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.securities import MarketHoliday
from app.portfolio_intelligence.market import calendar as cal
from app.portfolio_intelligence.market import candles as cm
from app.portfolio_intelligence.market import holidays as hol
from app.portfolio_intelligence.market import quotes as qm

HOLIDAYS_2026 = {date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 10, 20): "Dussehra", date(2026, 11, 10): "Diwali-Balipratipada", date(2026, 8, 15): "Independence Day"}   # 08-15 is a Saturday


@pytest.fixture(autouse=True)
def reset_calendar():
    cal.set_holidays({})
    yield
    cal.set_holidays({})


def payload(rows=None, key="CM"):
    rows = rows if rows is not None else [{"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Mahatma  Gandhi Jayanti", "morning_session": None, "evening_session": None},
                                           {"tradingDate": "08-Nov-2026", "weekDay": "Sunday", "description": "Diwali Laxmi Pujan*", "morning_session": None, "evening_session": None},
                                           {"tradingDate": "garbage", "description": "x"}]
    return {key: rows, "CD": [{"tradingDate": "01-Jan-2026", "description": "not equities"}]}


def test_the_calendar_applies_holidays_only_for_covered_years_and_otherwise_falls_back_to_weekdays():
    assert cal.is_trading_day(date(2026, 10, 2)) is True                          # nothing loaded: a weekday is a session
    cal.set_holidays(HOLIDAYS_2026)
    assert cal.is_trading_day(date(2026, 10, 2)) is False and cal.holiday_name(date(2026, 10, 2)) == "Mahatma Gandhi Jayanti"
    assert cal.is_trading_day(date(2026, 10, 1)) is True and cal.is_trading_day(date(2026, 10, 3)) is False       # Saturday
    assert cal.is_trading_day(date(2027, 1, 26)) is True and cal.holiday_name(date(2027, 1, 26)) is None            # 2027 is NOT covered: no invented holiday
    assert cal.coverage()["years_covered"] == [2026]


def test_sessions_skip_holidays_and_weekends():
    cal.set_holidays(HOLIDAYS_2026)
    assert cal.previous_session(date(2026, 10, 5)) == date(2026, 10, 1)            # Mon -> back over the weekend AND the Friday holiday
    assert cal.previous_session(date(2026, 10, 2), inclusive=True) == date(2026, 10, 1)
    assert cal.add_sessions(date(2026, 10, 1), 1) == date(2026, 10, 5)
    assert cal.add_sessions(date(2026, 10, 19), 1) == date(2026, 10, 21)             # the Tuesday between is Dussehra
    assert cal.add_sessions(date(2026, 10, 1), 0) == date(2026, 10, 1)


def test_the_last_final_session_and_market_status_respect_a_holiday():
    cal.set_holidays(HOLIDAYS_2026)
    fri_noon = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)                    # Fri 12:00 IST, a holiday
    assert cm.expected_last_session(fri_noon) == date(2026, 10, 1)
    st = qm.market_status(fri_noon)
    assert st["open"] is False and st["holiday"] == "Mahatma Gandhi Jayanti" and "Market closed for Mahatma Gandhi Jayanti" in st["label"] and "2026" in st["note"]
    assert qm.last_close_time(fri_noon).date() == date(2026, 10, 1)
    thu_noon = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)
    assert qm.market_status(thu_noon)["open"] is True and qm.market_status(thu_noon)["holiday"] is None
    cal.set_holidays({})
    assert cm.expected_last_session(fri_noon) == date(2026, 10, 1)                  # without the calendar Friday noon is a session in progress, so the last FINAL one is Thursday
    assert qm.market_status(fri_noon)["open"] is True and "not loaded" in qm.market_status(fri_noon)["note"]


def test_parse_keeps_the_equity_segment_and_rejects_empty_or_missing_lists():
    out = hol.parse_holidays(payload())
    assert out == {date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 11, 8): "Diwali Laxmi Pujan"}      # CM only, spacing and the trailing * cleaned, bad rows skipped
    for bad in ({}, {"CM": []}, {"CM": [{"tradingDate": "garbage"}]}, {"CD": [{"tradingDate": "01-Jan-2026"}]}, None, []):
        with pytest.raises(ValueError):
            hol.parse_holidays(bad)


async def test_store_replaces_the_covered_year_keeps_other_years_and_loads_the_calendar(db_session):
    old = {date(2025, 12, 25): "Christmas", date(2026, 3, 3): "Holi", date(2026, 10, 2): "old name"}
    await hol.store_holidays(db_session, old)
    res = await hol.store_holidays(db_session, {date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 10, 20): "Dussehra"})
    rows = {r.trade_date: r.description for r in (await db_session.execute(select(MarketHoliday))).scalars()}
    assert rows == {date(2025, 12, 25): "Christmas", date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 10, 20): "Dussehra"}      # Holi was withdrawn from 2026; 2025 untouched
    assert res["years"] == [2026] and cal.is_holiday(date(2026, 10, 20)) and cal.is_holiday(date(2025, 12, 25)) and not cal.is_holiday(date(2026, 3, 3))


async def test_refresh_uses_the_fetcher_and_a_bad_payload_changes_nothing(db_session):
    async def good():
        return payload()

    async def bad():
        return {"CM": []}

    await hol.refresh_holidays(db_session, fetch=good)
    assert cal.is_holiday(date(2026, 10, 2))
    with pytest.raises(ValueError):
        await hol.refresh_holidays(db_session, fetch=bad)
    assert cal.is_holiday(date(2026, 10, 2)) and len((await db_session.execute(select(MarketHoliday))).scalars().all()) == 2        # the stored calendar survives a bad answer


async def test_the_close_pass_skips_an_exchange_holiday(db_session):
    from app.portfolio_intelligence import scheduler
    from tests.test_living import setup_user

    await setup_user(db_session)
    cal.set_holidays({date(2026, 9, 30): "Test Holiday"})
    r = await scheduler.tick(db_session, datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))                                          # Wed 17:30 IST
    assert r == {"ran": False, "reason": "exchange holiday (Test Holiday)"}


def test_maturity_dates_use_the_calendar():
    from app.portfolio_intelligence.ledger import score as sc

    cal.set_holidays(HOLIDAYS_2026)
    assert sc.add_sessions(date(2026, 10, 1), 1) == date(2026, 10, 5)
