"""NSE equity trading calendar: weekends plus the exchange's published holidays (segment CM).

The published list covers only the CURRENT year, so holidays are applied ONLY for years the loaded calendar covers; for any other year the
calendar falls back to weekdays and says so (`coverage()`), so a stale or missing calendar can never silently invent or hide a holiday.
Stored candle dates remain the truth for history; this calendar is for FORWARD dates: the last final session, market open/closed, maturity
dates, the daily close pass.

The process-wide state is set at startup and after each refresh (`set_holidays`); functions here are pure reads of it."""

import logging
from datetime import date, timedelta

logger = logging.getLogger("calendar")

_holidays: dict[date, str] = {}
_years: set[int] = set()


def set_holidays(rows: dict[date, str], years: set[int] | None = None) -> None:
    """Replace the loaded calendar. `years` are the years the source actually covered (default: the years present in `rows`)."""
    global _holidays, _years
    _holidays = dict(rows)
    _years = set(years) if years is not None else {d.year for d in rows}


def covers(d: date) -> bool:
    return d.year in _years


def is_holiday(d: date) -> bool:
    return covers(d) and d in _holidays


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def holiday_name(d: date) -> str | None:
    return _holidays.get(d) if covers(d) else None


def previous_session(d: date, *, inclusive: bool = False) -> date:
    """The latest trading day before `d` (or on it when inclusive)."""
    x = d if inclusive else d - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(x):
            return x
        x -= timedelta(days=1)
    return x


def add_sessions(d: date, n: int) -> date:
    """`n` trading days after `d`."""
    x = d
    while n > 0:
        x += timedelta(days=1)
        if is_trading_day(x):
            n -= 1
    return x


def coverage() -> dict:
    return {"years_covered": sorted(_years), "holidays_loaded": len(_holidays), "fallback": "weekdays only for any year not covered"}
