"""What data the app holds, how old it is, how it updates, and when it will next update. Read-only; says nothing it cannot measure."""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.models.living import SchedulerRun
from app.models.fundamentals import FundamentalMetrics
from app.models.securities import MarketHoliday, Security, SecurityCandle, SecurityForecast, SecuritySignal, SecurityTer
from app.models.watchlist import MarketQuote
from app.portfolio_intelligence.market import calendar as cal
from app.portfolio_intelligence.scheduler import CLOSE_TIME
from app.portfolio_intelligence.sources.angel.token_store import IST, load_session
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4/system", tags=["v4-system"])


def _next_close(now: datetime) -> tuple[date, datetime]:
    """The next scheduled after-close run: today at 16:00 IST if that is a trading day and still ahead, else the next session."""
    ist = now.astimezone(IST)
    d = ist.date()
    if cal.is_trading_day(d) and ist.time() < CLOSE_TIME:
        pass
    else:
        d = cal.add_sessions(d, 1)
    return d, datetime.combine(d, CLOSE_TIME, tzinfo=IST)


def _last_closed_session(now: datetime) -> date:
    """The newest trading day whose final close (16:00 IST) has passed."""
    ist = now.astimezone(IST)
    d = ist.date()
    if cal.is_trading_day(d) and ist.time() >= CLOSE_TIME:
        return d
    return cal.previous_session(d)


def _item(key, title, source, needs_session, how, last, detail, state, why=None, **extra):
    return {"key": key, "title": title, "source": source, "needs_broker_session": needs_session, "how_it_updates": how,
            "last_update": last, "detail": detail, "state": state, "why": why, **extra}


@router.post("/fundamentals/refresh", status_code=202)
async def fundamentals_refresh(db: AsyncSession = Depends(get_db)):
    """Queue a company-fundamentals refresh now (the worker does it; it takes a few minutes)."""
    from app.portfolio_intelligence.fundamentals.jobs import enqueue_fundamentals

    job = await enqueue_fundamentals(db, "manual", now=utcnow())
    return {"queued": job is not None, "already_queued": job is None}


@router.get("/freshness")
async def freshness(db: AsyncSession = Depends(get_db)):
    now = utcnow()
    last_closed = _last_closed_session(now)
    next_d, next_dt = _next_close(now)
    sess = load_session(now=now)
    ist_today = now.astimezone(IST).date()

    q_last, q_n = (await db.execute(select(func.max(MarketQuote.retrieved_at), func.count()).select_from(MarketQuote))).one()
    c_last, c_n = (await db.execute(select(func.max(SecurityCandle.trade_date), func.count(func.distinct(SecurityCandle.security_id))))).one()
    s_last, s_n = (await db.execute(select(func.max(SecuritySignal.as_of_date), func.count(func.distinct(SecuritySignal.security_id))))).one()
    f_last, f_n, f_asof, f_days = (await db.execute(select(func.max(SecurityForecast.computed_at), func.count(), func.max(SecurityForecast.as_of_date),
                                                           func.count(func.distinct(SecurityForecast.as_of_date))))).one()
    nav_last = (await db.execute(select(func.max(Security.nav_date)).where(Security.kind == "mutual_fund"))).scalar_one_or_none()
    ter_last = (await db.execute(select(func.max(SecurityTer.ter_date)))).scalar_one_or_none()
    cat_last = (await db.execute(select(func.max(Security.seen_at)))).scalar_one_or_none()
    from app.portfolio_intelligence.scoring.service import _latest_fundamentals

    fu_rows = list((await _latest_fundamentals(db)).values())          # each company's newest fetch only, so an old row cannot make the dates look newer than they are
    fu_n = len(fu_rows)
    fu_last = min((r.retrieved_at for r in fu_rows), default=None)     # the OLDEST company fetch decides whether the set is current
    fu_q = max((r.as_of_date for r in fu_rows), default=None)
    fu_ann = max((r.annual_period_end for r in fu_rows if r.annual_period_end), default=None)
    fu_nse = max((r.nse_period_end for r in fu_rows if r.nse_period_end), default=None)
    hol_years = sorted({r for (r,) in (await db.execute(select(func.extract("year", MarketHoliday.trade_date)))).all()})
    sync_last = (await db.execute(select(func.max(SourceAccount.last_sync_at)).where(SourceAccount.user_id == SINGLE_USER_ID, SourceAccount.source_type == "angel_one"))).scalar_one_or_none()
    run = (await db.execute(select(SchedulerRun).where(SchedulerRun.kind == "daily_close").order_by(SchedulerRun.ran_at.desc()).limit(1))).scalar_one_or_none()

    def state_for_date(d: date | None) -> str:
        return "no_data" if d is None else "current" if d >= last_closed else "behind"

    session_text = (f"Angel session valid until {sess.expires_at.astimezone(IST):%d %b %H:%M} IST" if sess else
                    "No valid Angel session: prices, price history and holdings cannot update until you reconnect")
    items = [
        _item("prices", "Prices (Angel One)", "Angel One quotes", True, "after each trading day's close, from a saved session",
              q_last.isoformat() if q_last else None, f"{q_n} instruments; last saved {q_last:%d %b %H:%M} UTC" if q_last else "none saved",
              "no_data" if q_last is None else "current" if q_last.astimezone(IST).date() >= last_closed else "behind",
              None if sess or (q_last and q_last.astimezone(IST).date() >= last_closed) else "needs a broker session"),
        _item("history", "Price history", "Angel One daily candles", True, "one new day per instrument after each close",
              c_last.isoformat() if c_last else None, f"{c_n} securities; newest day {c_last}" if c_last else "none", state_for_date(c_last)),
        _item("signals", "Price-history signals", "computed here from the history", False, "recomputed after the history updates",
              s_last.isoformat() if s_last else None, f"{s_n} securities; as of {s_last}" if s_last else "none", state_for_date(s_last)),
        _item("forecasts", "Price forecasts (Kronos)", "a forecasting model run on this computer", False,
              "every trading night for about 90 stocks and ETFs (your watchlist, the Nifty 50, one ETF per index), after the signals",
              f_last.isoformat() if f_last else None, f"{f_n} forecasts over {f_days} day(s); newest for {f_asof}" if f_last else "none yet", state_for_date(f_asof),
              None if f_days != 1 else "only one night so far: the first run was on the day this was built; a new set arrives every trading night"),
        _item("nav", "Mutual fund NAVs", "AMFI's official file", False, "every day, no broker session needed",
              nav_last.isoformat() if nav_last else None, f"newest NAV date {nav_last}" if nav_last else "none", "current" if nav_last and nav_last >= ist_today - timedelta(days=4) else "behind"),
        _item("costs", "Fund expense ratios", "AMFI's expense-ratio API", False, "weekly, no broker session needed",
              ter_last.isoformat() if ter_last else None, f"newest figure dated {ter_last}" if ter_last else "none", "current" if ter_last and ter_last >= ist_today - timedelta(days=45) else "behind"),
        _item("catalogue", "Stock, ETF and fund lists", "NSE and AMFI files", False, "daily with the after-close run, no broker session needed",
              cat_last.isoformat() if cat_last else None, f"refreshed {cat_last:%d %b %H:%M} UTC" if cat_last else "none", "current" if cat_last and cat_last.astimezone(IST).date() >= last_closed else "behind"),
        _item("fundamentals", "Company fundamentals (Nifty 50)", "Yahoo Finance, cross-checked against NSE's quarterly filings", False,
              "weekly, no broker session needed; a company is retried if a run is cut short",
              fu_last.isoformat() if fu_last else None,
              (f"{fu_n} companies; oldest fetch {fu_last:%d %b}; Yahoo's latest quarter {fu_q}; annual statements to {fu_ann or 'none yet'}; NSE filings to {fu_nse or 'none yet'}" if fu_last else "none"),
              "no_data" if fu_last is None else "current" if (now - (fu_last if fu_last.tzinfo else fu_last.replace(tzinfo=now.tzinfo))).days <= 10 else "behind",
              "Yahoo can rate-limit; a refresh that is cut short resumes on the next weekly check" if fu_last is None else None),
        _item("holidays", "NSE trading holidays", "NSE's holiday list", False, "with the daily catalogue refresh",
              None, f"covers {', '.join(str(int(y)) for y in hol_years) or 'no year'}; other years use weekdays only", "current" if ist_today.year in {int(y) for y in hol_years} else "behind"),
        _item("holdings", "Your Angel holdings", "Angel One account", True, "after each close, from a saved session (or press Sync now)",
              sync_last.isoformat() if sync_last else None, f"last sync {sync_last:%d %b %H:%M} UTC" if sync_last else "never synced",
              "no_data" if sync_last is None else "current" if sync_last.astimezone(IST).date() >= last_closed else "behind"),
    ]
    return {
        "now": now.isoformat(),
        "market": {"today_is_trading_day": cal.is_trading_day(ist_today), "holiday": cal.holiday_name(ist_today), "last_closed_session": last_closed.isoformat(),
                   "next_update": next_dt.isoformat(), "next_update_date": next_d.isoformat()},
        "scheduler": {"last_daily_close": None if run is None else run.run_date.isoformat(), "last_ran_at": None if run is None else run.ran_at.isoformat(),
                      "runs_in": "the backend process, checked every 10 minutes; it only runs while the app and your computer are on"},
        "broker_session": {"valid": sess is not None, "expires_at": sess.expires_at.isoformat() if sess else None, "text": session_text,
                           "daily_reconnect": "Angel sessions end at midnight IST, so reconnect once each trading day (VPN on first) or the next close cannot refresh prices, history, signals, forecasts or holdings."},
        "items": items,
    }
