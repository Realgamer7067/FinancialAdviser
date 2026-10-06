"""Fundamentals refresh: annual statement extraction, NSE filing parsing and the chunked worker job, with Yahoo and NSE faked."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import select

from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument
from app.portfolio_intelligence.fundamentals import jobs as FJ
from app.portfolio_intelligence.fundamentals import nse as N
from app.portfolio_intelligence.fundamentals import yahoo as Y


def frames(with_prior=True):
    c = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
    bal = pd.DataFrame({c[0]: {"Total Assets": 200.0}, c[1]: {"Total Assets": 160.0}} if with_prior else {c[0]: {"Total Assets": 200.0}})
    cf = pd.DataFrame({c[0]: {"Operating Cash Flow": 50.0, "Capital Expenditure": -10.0, "Free Cash Flow": 40.0}, c[1]: {"Operating Cash Flow": 45.0}})
    inc = pd.DataFrame({c[0]: {"Net Income Common Stockholders": 48.0}, c[1]: {"Net Income": 40.0}})
    return bal, cf, inc


def test_annual_figures_come_from_one_matching_year_and_missing_stays_none():
    out = Y.annual_from_frames(*frames())
    assert out["annual_period_end"] == date(2026, 3, 31) and out["total_assets"] == 200.0 and out["total_assets_prior"] == 160.0
    assert out["annual_net_income"] == 48.0 and out["annual_operating_cash_flow"] == 50.0 and out["annual_free_cash_flow"] == 40.0
    assert Y.annual_from_frames(*frames(with_prior=False))["total_assets_prior"] is None
    bal, cf, inc = frames()
    cf2 = cf.drop(columns=[pd.Timestamp("2026-03-31")])
    out2 = Y.annual_from_frames(bal, cf2, inc)                       # the cash-flow statement lacks the newest year: use the newest year ALL three have
    assert out2["annual_period_end"] == date(2025, 3, 31) and out2["total_assets"] == 160.0
    assert Y.annual_from_frames(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()) == {}


def test_free_cash_flow_is_derived_from_ocf_and_negative_capex_when_absent():
    bal, cf, inc = frames()
    cf.loc["Free Cash Flow", pd.Timestamp("2026-03-31")] = float("nan")
    assert Y.annual_from_frames(bal, cf, inc)["annual_free_cash_flow"] == 40.0


XML = """<xbrli:xbrl><xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="OneI"><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="OneReportable1D"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period><xbrli:scenario/></xbrli:context>
<in-capmkt:RevenueFromOperations contextRef="OneD" decimals="-7" unitRef="INR">722750000000</in-capmkt:RevenueFromOperations>
<in-capmkt:ProfitOrLossAttributableToOwnersOfParent contextRef="OneD" decimals="-7" unitRef="INR">133490000000</in-capmkt:ProfitOrLossAttributableToOwnersOfParent>
<in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" decimals="INF" unitRef="INRPerShare">36.9</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
<in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneReportable1D" unitRef="INRPerShare">1.5</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
<in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated></xbrli:xbrl>"""


def test_a_quarterly_filing_is_read_from_its_own_dimensionless_three_month_context():
    q = N.parse_quarter(XML)
    assert q == {"period_end": date(2026, 6, 30), "eps": 36.9, "profit": 133490000000.0, "revenue": 722750000000.0, "nature": "Consolidated"}
    assert N.parse_quarter("<xbrli:xbrl/>") is None


def test_quarter_picking_prefers_consolidated_and_the_latest_revision_and_ttm_needs_four_consecutive_quarters():
    rows = [{"qe_Date": "30-JUN-2026", "consolidated": "Standalone", "xbrl": "https://nsearchives.nseindia.com/a", "creation_Date": "09-Jul-2026"},
            {"qe_Date": "30-JUN-2026", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/b", "creation_Date": "09-Jul-2026"},
            {"qe_Date": "31-MAR-2026", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/c", "creation_Date": "09-Apr-2026"},
            {"qe_Date": "31-MAR-2026", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/c2", "creation_Date": "20-Apr-2026"},
            {"qe_Date": "01-JAN-2026", "consolidated": "Consolidated", "xbrl": None}]
    picks = N.pick_quarters(rows)
    assert [p["xbrl"].rsplit("/", 1)[1] for p in picks] == ["b", "c2"]
    qs = [{"period_end": date(2026, 6, 30), "eps": 10.0}, {"period_end": date(2026, 3, 31), "eps": 9.0}, {"period_end": date(2025, 12, 31), "eps": 8.0}, {"period_end": date(2025, 9, 30), "eps": 7.0}]
    assert N.ttm_eps(qs) == (34.0, date(2026, 6, 30), 4)
    assert N.ttm_eps(qs[:3])[0] is None                                              # three quarters are not a year
    gap = [qs[0], qs[1], qs[2], {"period_end": date(2025, 3, 31), "eps": 7.0}]
    assert N.ttm_eps(gap)[0] is None                                                 # a missing quarter in the middle
    assert N.ttm_eps(qs[:3] + [{"period_end": date(2025, 9, 30), "eps": None}])[0] is None


@pytest.mark.asyncio
async def test_only_nse_hosts_are_ever_fetched():
    assert N._host_ok("https://nsearchives.nseindia.com/x.xml") and not N._host_ok("https://evil.example.com/x.xml") and not N._host_ok("http://www.nseindia.com/x")
    with pytest.raises(N.NseError):
        await N.fetch_quarter(N.client(), "https://evil.example.com/x.xml")


class FakeProvider:
    def __init__(self, bad=()):
        self.bad, self.calls = set(bad), []

    async def get_fundamentals(self, symbol):
        from app.providers.base import FundamentalSnapshot

        self.calls.append(symbol)
        if symbol in self.bad:
            return None
        return FundamentalSnapshot(symbol=symbol, as_of_date=date(2026, 3, 31), eps=10.0, market_cap=1e12, retrieved_at=datetime.now(timezone.utc), source="yfinance_nifty50_seed")


@pytest.mark.asyncio
async def test_refresh_symbol_saves_a_new_dated_row_with_annual_and_nse_figures_and_nothing_when_yahoo_is_empty(db_session, monkeypatch):
    ins = Instrument(symbol="TCS", name="TCS", isin="INE467B01029", sector="IT", exchange="NSE")
    db_session.add(ins)
    await db_session.commit()
    monkeypatch.setattr(FJ, "_statements", lambda t: {"annual_period_end": date(2026, 3, 31), "total_assets": 200.0, "total_assets_prior": 160.0, "annual_net_income": 48.0,
                                                      "annual_operating_cash_flow": 50.0, "annual_capex": -10.0, "annual_free_cash_flow": 40.0})

    async def fake_check(c, symbol):
        return {"nse_eps_ttm": 34.0, "nse_period_end": date(2026, 6, 30), "nse_quarters": 4}

    monkeypatch.setattr(N, "check_symbol", fake_check)
    out = await FJ.refresh_symbol(db_session, ins.id, "TCS", FakeProvider(), object())
    assert out == {"ok": True, "nse": "ok", "annual": True}
    row = (await db_session.execute(select(FundamentalMetrics))).scalars().one()
    assert row.total_assets == 200.0 and row.nse_eps_ttm == 34.0 and row.annual_free_cash_flow == 40.0 and row.as_of_date == date(2026, 3, 31)
    bad = await FJ.refresh_symbol(db_session, ins.id, "TCS", FakeProvider(bad={"TCS"}), None)
    assert bad["ok"] is False
    assert len((await db_session.execute(select(FundamentalMetrics))).scalars().all()) == 1          # no empty row written


@pytest.mark.asyncio
async def test_an_nse_failure_still_keeps_the_yahoo_row(db_session, monkeypatch):
    ins = Instrument(symbol="INFY", name="Infosys", isin="INE009A01021", sector="IT", exchange="NSE")
    db_session.add(ins)
    await db_session.commit()
    monkeypatch.setattr(FJ, "_statements", lambda t: {})

    async def boom(c, symbol):
        raise N.NseError("list returned HTTP 403")

    monkeypatch.setattr(N, "check_symbol", boom)
    out = await FJ.refresh_symbol(db_session, ins.id, "INFY", FakeProvider(), object())
    assert out["ok"] and out["nse"].startswith("failed") and out["annual"] is False
    row = (await db_session.execute(select(FundamentalMetrics))).scalars().one()
    assert row.nse_eps_ttm is None and row.total_assets is None and row.eps == 10.0                   # unknown stays unknown


@pytest.mark.asyncio
async def test_a_refresh_is_due_for_stale_or_missing_companies_but_not_right_after_an_attempt(db_session):
    from app.providers.mode import expected_fundamentals_source
    from app.models.portfolio_jobs import PortfolioJob
    from app.core.single_user import SINGLE_USER_ID

    ins = Instrument(symbol="ITC", name="ITC", isin="INE154A01025", sector="FMCG", exchange="NSE")
    db_session.add(ins)
    await db_session.commit()
    now = datetime.now(timezone.utc)
    db_session.add(FundamentalMetrics(instrument_id=ins.id, as_of_date=date(2026, 3, 31), source=expected_fundamentals_source(), retrieved_at=now - timedelta(days=9)))
    await db_session.commit()
    assert await FJ.is_due(db_session, now) is True
    db_session.add(PortfolioJob(user_id=SINGLE_USER_ID, kind=FJ.KIND, request_key="x", status="failed", attempts=1, created_at=now - timedelta(hours=1)))
    await db_session.commit()
    assert await FJ.is_due(db_session, now) is False                  # tried an hour ago: no tick-by-tick hammering
    db_session.add(FundamentalMetrics(instrument_id=ins.id, as_of_date=date(2026, 3, 31), source=expected_fundamentals_source(), retrieved_at=now))
    await db_session.commit()
    assert await FJ.is_due(db_session, now + timedelta(hours=7)) is False   # fresh row, nothing stale


BANK_XML = XML.replace("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsPerShareAfterExtraordinaryItems")
HALF_YEAR_XML = BANK_XML.replace("2026-04-01", "2026-01-01").replace("2026-06-30", "2026-06-30").replace("<xbrli:startDate>2026-01-01", "<xbrli:startDate>2025-04-01")


def test_banking_filings_use_other_eps_tag_names_and_a_half_year_filing_gives_no_quarter():
    assert N.parse_quarter(BANK_XML)["eps"] == 36.9
    assert N.parse_quarter(HALF_YEAR_XML) is None                      # a 6-12 month period is not a quarter: never used as one


def test_each_quarter_keeps_candidates_best_first_with_revisions_ordered_by_real_time():
    rows = [{"qe_Date": "30-SEP-2025", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/half", "creation_Date": "15-Oct-2025 08:48:30"},
            {"qe_Date": "30-SEP-2025", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/quarter", "creation_Date": "16-Oct-2025 08:00:00"},
            {"qe_Date": "30-SEP-2025", "consolidated": "Standalone", "xbrl": "https://nsearchives.nseindia.com/sa", "creation_Date": "17-Oct-2025 08:00:00"},
            {"qe_Date": "30-JUN-2026", "consolidated": "Consolidated", "xbrl": "https://nsearchives.nseindia.com/q1", "creation_Date": "9-Jul-2026"}]
    groups = N.group_quarters(rows)
    assert [g[0]["_qe"] for g in groups] == ["2026-06-30", "2025-09-30"]
    assert [x["xbrl"].rsplit("/", 1)[1] for x in groups[1]] == ["quarter", "half", "sa"]            # consolidated first, then newest filing


@pytest.mark.asyncio
async def test_the_newest_fetch_wins_even_when_an_older_row_carries_a_later_as_of_date(db_session):
    from app.portfolio_intelligence.scoring.service import _latest_fundamentals

    ins = Instrument(symbol="LT", name="L&T", isin="INE018A01030", sector="Industrials", exchange="NSE")
    db_session.add(ins)
    await db_session.commit()
    now = datetime.now(timezone.utc)
    db_session.add_all([FundamentalMetrics(instrument_id=ins.id, as_of_date=date(2026, 8, 23), source="s", retrieved_at=now - timedelta(days=16), eps=1.0),       # old fetch labelled with its fetch day
                        FundamentalMetrics(instrument_id=ins.id, as_of_date=date(2026, 6, 30), source="s", retrieved_at=now, eps=2.0, total_assets=5.0)])        # new fetch, real quarter end
    await db_session.commit()
    got = (await _latest_fundamentals(db_session))[ins.id]
    assert got.eps == 2.0 and got.total_assets == 5.0
