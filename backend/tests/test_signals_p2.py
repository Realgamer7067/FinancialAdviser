"""P2: deterministic signals, rank placement, append-only storage, families, API. No network, no model."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import CandleSync, CorporateAction, Security, SecurityCandle, SecuritySignal
from app.portfolio_intelligence.risk.volatility import portfolio_volatility
from app.portfolio_intelligence.signals import compute as sg
from app.portfolio_intelligence.signals import run as sr

D = Decimal
EXPECTED = date(2026, 9, 30)                       # Wed
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)   # 17:30 IST: the 30th's close is final


def weekdays_ending(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def walk(n: int, seed: int, drift: float = 0.0004, vol: float = 0.012, start: float = 100.0) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(start * np.exp(np.cumsum(rng.normal(drift, vol, n))))


def metrics(closes, *, vols=None, highs=None, lows=None, unreliable=None, last=EXPECTED):
    dates = weekdays_ending(last, len(closes))
    vols = vols if vols is not None else [1_000_000] * len(closes)
    return sg.compute_metrics(dates, closes, highs or closes, lows or closes, vols, expected_last_session=EXPECTED, unreliable_dates=unreliable)


# --- metrics ------------------------------------------------------------------------------------------------------------

def test_metrics_match_independent_numpy_calculations():
    c = walk(300, 1)
    m = metrics(c)
    a = np.array(c)
    assert m["quality"] == "ok" and m["history_len"] == 300
    assert m["sma200_ratio"] == pytest.approx(a[-1] / a[-200:].mean() - 1)
    assert m["trend_state"] == ("above" if a[-1] > a[-200:].mean() else "below")
    assert m["mom_12_1"] == pytest.approx(a[-22] / a[-253] - 1)           # 12 months back to 1 month ago: the last month is skipped
    assert m["mom_6_1"] == pytest.approx(a[-22] / a[-127] - 1)
    r = a[1:] / a[:-1] - 1
    assert m["vol_252"] == pytest.approx(r[-252:].std(ddof=1) * np.sqrt(252))
    assert m["vol_60"] == pytest.approx(r[-60:].std(ddof=1) * np.sqrt(252))
    assert m["vol_ratio"] == pytest.approx(m["vol_60"] / m["vol_252"])
    assert m["drawdown_current"] == pytest.approx(a[-1] / a[-252:].max() - 1)
    assert m["week52_pos"] == pytest.approx((a[-1] - a[-252:].min()) / (a[-252:].max() - a[-252:].min()))
    path = np.cumprod(1 + r[-252:])
    assert m["max_dd_1y"] == pytest.approx(float(np.min(path / np.maximum(np.maximum.accumulate(path), 1.0) - 1)), abs=1e-12)


def test_volatility_is_the_same_number_on_the_market_and_risk_pages():
    c = walk(253, 7)      # exactly the Risk page's minimum: 252 returns
    dates = weekdays_ending(EXPECTED, 253)
    risk = portfolio_volatility({"a": list(zip(dates, c))}, {"a": D(1)}, D(1))
    assert risk["status"] == "ready"
    m = metrics(c)
    assert round(m["vol_252"], 4) == risk["annualized_volatility"]
    assert round(m["max_dd_1y"], 4) == risk["max_drawdown_in_window"]


def test_minimum_history_gives_no_number_not_an_approximation():
    short = metrics(walk(252, 2))          # 251 returns: one short
    assert short["quality"] == "insufficient_data" and short["vol_252"] is None and short["mom_12_1"] is None and short["drawdown_current"] is None
    assert short["sma200_ratio"] is not None and short["vol_60"] is not None   # what CAN be measured honestly still is
    assert metrics(walk(253, 2))["quality"] == "ok"
    assert metrics([])["quality"] == "insufficient_data"


def test_bad_closes_are_never_computed_on():
    c = walk(300, 3)
    c[100] = 0.0
    m = metrics(c)
    assert m["quality"] == "insufficient_data" and m["vol_252"] is None and "non-positive" in m["reasons"][0]
    c[100] = float("nan")
    assert metrics(c)["quality"] == "insufficient_data"


def test_stale_series_is_marked_and_kept_out_of_ranks():
    m = metrics(walk(300, 4), last=EXPECTED - timedelta(days=12))
    assert m["quality"] == "stale" and "behind the last session" in m["reasons"][0]
    assert metrics(walk(300, 4), last=EXPECTED - timedelta(days=3))["quality"] == "ok"   # a long weekend is not stale


def test_unreliable_window_only_matters_inside_the_lookback():
    c = walk(400, 5)
    dates = weekdays_ending(EXPECTED, 400)
    inside, outside = dates[-100], dates[-300]
    assert metrics(c, unreliable=[inside])["quality"] == "unreliable_window"
    assert metrics(c, unreliable=[outside])["quality"] == "ok"      # RELIANCE's 2023 demerger sits outside a 1-year lookback


def test_liquidity_is_a_median_and_circuit_days_are_counted():
    c = walk(300, 6)
    vols = [10_000] * 300
    vols[-1] = 10_000_000_000                       # one huge day must not move a MEDIAN
    m = metrics(c, vols=vols)
    assert m["liquidity_value"] == pytest.approx(float(np.median([c[-i] * vols[-i] for i in range(1, 21)])))
    assert sg.liquidity_flag(m["liquidity_value"]) == ("ok" if m["liquidity_value"] >= sg.LIQUIDITY_FLOOR_RUPEES else "thin")
    highs, lows = list(c), list(c)
    for i in range(1, 6):
        highs[-i] = c[-i] * 1.0
        lows[-i] = c[-i] * 1.0                      # high == low with volume: circuit-locked
    for i in range(6, 21):
        highs[-i], lows[-i] = c[-i] * 1.01, c[-i] * 0.99
    assert metrics(c, highs=highs, lows=lows, vols=vols)["circuit_days_20"] == 5
    assert metrics(c, vols=[None] * 300)["liquidity_value"] is None and sg.liquidity_flag(None) == "unknown"


# --- ranks --------------------------------------------------------------------------------------------------------------

def test_percentile_places_outsiders_without_moving_the_reference():
    ref = np.array([1.0, 2.0, 3.0, 4.0])
    assert sg.percentile_in(ref, 2.5) == 50.0 and sg.percentile_in(ref, 0.0) == 0.0 and sg.percentile_in(ref, 99.0) == 100.0
    assert sg.percentile_in(ref, 2.0) == 37.5                              # strictly below 1 + half the tie = 1.5 of 4
    assert sg.percentile_in(np.array([]), 1.0) is None and sg.percentile_in(ref, None) is None and ref.size == 4


def test_rank_reference_excludes_thin_unclassified_and_unclean_names_but_still_places_them():
    rows = [{"quality": "ok", "mom_12_1": v, "vol_252": v / 10} for v in (0.1, 0.2, 0.3, 0.4)]
    rows.append({"quality": "ok", "mom_12_1": 0.25, "vol_252": 0.025})        # thin: not in the reference, still ranked
    rows.append({"quality": "stale", "mom_12_1": 0.5, "vol_252": 0.05})       # stale: no rank at all
    sg.rank_against_reference(rows, [True, True, True, True, False, False])
    assert [r["mom_12_1_rank"] for r in rows[:4]] == [12.5, 37.5, 62.5, 87.5]
    assert rows[4]["mom_12_1_rank"] == 50.0 and rows[5]["mom_12_1_rank"] is None
    assert all(r["rank_universe_size"] == 4 for r in rows)                    # the thin name did not join the universe


# --- families -------------------------------------------------------------------------------------------------------------

def row(**k):
    base = {"quality": "ok", "trend_state": "above", "mom_12_1_rank": 70.0, "vol_252_rank": 30.0, "drawdown_current": -0.05, "liquidity_value": 5e7, "circuit_days_20": 0}
    base.update(k)
    return base


def test_trend_and_risk_families_and_the_votes():
    s = sg.summarize(row())
    assert (s["trend"]["state"], s["risk"]["state"], s["liquidity"]["state"], s["net_vote"]) == ("positive", "positive", "ok", 2)
    neg = sg.summarize(row(trend_state="below", mom_12_1_rank=20.0, vol_252_rank=90.0))
    assert (neg["trend"]["vote"], neg["risk"]["vote"], neg["net_vote"]) == (-1, -1, -2)
    assert sg.summarize(row(drawdown_current=-0.35))["risk"]["state"] == "positive"          # distance from the high is NOT a risk vote (it duplicates trend)
    assert sg.summarize(row(vol_252_rank=65.0))["risk"]["state"] == "mixed"
    assert sg.summarize(row(vol_252_rank=80.0))["risk"]["state"] == "negative" and sg.summarize(row(vol_252_rank=50.0))["risk"]["state"] == "positive"
    assert sg.summarize(row(trend_state="above", mom_12_1_rank=30.0))["trend"]["state"] == "mixed"
    assert sg.summarize(row(quality="stale"))["trend"] == {"state": "unavailable", "vote": 0, "text": "not enough clean history"}
    assert sg.summarize(row(liquidity_value=1e6, circuit_days_20=3))["liquidity"]["state"] == "thin"


def test_a_model_forecast_is_shown_but_never_counted():
    s = sg.summarize(row(), {"direction": "bullish"})
    assert s["forecast"]["vote"] == 0 and s["forecast"]["state"] == "bullish" and s["net_vote"] == 2
    assert sg.summarize(row())["forecast"]["state"] == "none"


def test_no_advice_wording_in_any_family_text():
    texts = []
    for r in (row(), row(trend_state="below", mom_12_1_rank=10.0, vol_252_rank=95.0, drawdown_current=-0.4), row(quality="stale"), row(liquidity_value=1e5, circuit_days_20=2)):
        s = sg.summarize(r)
        texts += [s["trend"]["text"], s["risk"]["text"], s["liquidity"]["text"], s["forecast"]["text"]]
    banned = ("buy", "sell", "should", "recommend", "target", "will rise", "will fall")
    assert not [t for t in texts if any(b in t.lower() for b in banned)]


# --- DB: the run --------------------------------------------------------------------------------------------------------------

async def make_security(db, symbol, closes, *, kind="stock", sector="Energy", last=EXPECTED, vol=2_000_000, full_refetches=0):
    s = Security(source_key=f"isin:{symbol}", kind=kind, isin=None, symbol=symbol, name=symbol, series="EQ", sector=sector, source="nse_equity_l", is_active=True, seen_at=NOW)
    db.add(s)
    await db.flush()
    dates = weekdays_ending(last, len(closes))
    for d, c in zip(dates, closes):
        db.add(SecurityCandle(security_id=s.id, trade_date=d, open=D(str(c)), high=D(str(c * 1.01)), low=D(str(c * 0.99)), close=D(str(c)), volume=vol))
    db.add(CandleSync(security_id=s.id, first_date=dates[0], last_date=dates[-1], row_count=len(closes), fetched_at=NOW, full_refetches=full_refetches))
    await db.commit()
    return s


async def test_run_stores_point_in_time_rows_and_is_append_only(db_session):
    a = await make_security(db_session, "AAA", walk(300, 11))
    a_id = a.id
    b = await make_security(db_session, "BBB", walk(300, 12, drift=-0.0006))
    first = await sr.run_signals(db_session, NOW)
    assert first["securities"] == 2 and first["inserted"] == 2 and first["skipped_existing"] == 0 and first["quality"] == {"ok": 2}
    rows = {r.security_id: r for r in (await db_session.execute(select(SecuritySignal))).scalars()}
    ra = rows[a_id]
    assert (ra.origin, ra.method_version, ra.as_of_date, ra.universe, ra.quality) == ("live", "signals-v1", EXPECTED, "stock", "ok")
    assert ra.input_marker.startswith("0:300:2026-09-30:") and ra.rank_universe_size == 2 and ra.detail["policy_version"] == sg.POLICY_VERSION
    before = {k: (r.computed_at, r.vol_252, r.mom_12_1_rank) for k, r in rows.items()}
    second = await sr.run_signals(db_session, NOW + timedelta(hours=1))
    assert second["inserted"] == 0 and second["skipped_existing"] == 2                       # same day: a no-op
    db_session.expire_all()
    after = {r.security_id: (r.computed_at, r.vol_252, r.mom_12_1_rank) for r in (await db_session.execute(select(SecuritySignal))).scalars()}
    assert after == before                                                                   # never rewritten
    # a new trading day is a NEW row; the old one is untouched
    db_session.add(SecurityCandle(security_id=a_id, trade_date=date(2026, 10, 1), open=D(100), high=D(101), low=D(99), close=D(100), volume=2_000_000))
    sync = await db_session.get(CandleSync, a_id)
    sync.last_date, sync.row_count = date(2026, 10, 1), 301
    await db_session.commit()
    third = await sr.run_signals(db_session, NOW + timedelta(days=1))
    assert third["inserted"] == 1 and (await db_session.execute(select(func.count()).select_from(SecuritySignal).where(SecuritySignal.security_id == a_id))).scalar_one() == 2


async def test_an_unadjusted_split_is_adjusted_before_signals_are_computed(db_session):
    c = walk(300, 21, drift=0.0, vol=0.004)
    ex_idx = 150
    raw = [x if i >= ex_idx else x * 2 for i, x in enumerate(c)]          # price halves at the ex-date: still raw in the source
    s = await make_security(db_session, "SPLITCO", raw)
    ex = weekdays_ending(EXPECTED, 300)[ex_idx]
    db_session.add(CorporateAction(symbol="SPLITCO", ex_date=ex, subject="Bonus 1:1", kind="bonus", price_factor=D("0.5"), needs_review=False, source="nse", fetched_at=NOW))
    await db_session.commit()
    res = await sr.run_signals(db_session, NOW)
    row = (await db_session.execute(select(SecuritySignal).where(SecuritySignal.security_id == s.id))).scalar_one()
    assert res["quality"] == {"ok": 1} and row.detail["adjustments_applied"] == 1
    assert abs(float(row.mom_12_1)) < 0.6 and float(row.drawdown_current) > -0.5          # on the raw series this would read as about -50%


async def test_a_demerger_inside_the_lookback_marks_the_row_unreliable_and_out_of_the_ranks(db_session):
    s = await make_security(db_session, "DEMCO", walk(300, 31))
    ex = weekdays_ending(EXPECTED, 300)[-80]
    db_session.add(CorporateAction(symbol="DEMCO", ex_date=ex, subject="Demerger", kind="demerger", needs_review=True, source="nse", fetched_at=NOW))
    await db_session.commit()
    await sr.run_signals(db_session, NOW)
    row = (await db_session.execute(select(SecuritySignal).where(SecuritySignal.security_id == s.id))).scalar_one()
    assert row.quality == "unreliable_window" and row.mom_12_1_rank is None and "not adjusted automatically" in row.detail["unreliable"][0]["reason"]


async def test_stocks_and_etfs_rank_against_their_own_kind(db_session):
    for i in range(6):
        await make_security(db_session, f"S{i}", walk(300, 40 + i, drift=0.0001 * i))
    for i in range(3):
        await make_security(db_session, f"E{i}", walk(300, 60 + i), kind="etf", sector=None)
    res = await sr.run_signals(db_session, NOW)
    assert res["reference_sizes"] == {"stock": 6, "etf": 3}
    sizes = {r.universe: r.rank_universe_size for r in (await db_session.execute(select(SecuritySignal))).scalars()}
    assert sizes == {"stock": 6, "etf": 3}


async def test_unclassified_and_thin_stocks_are_not_in_the_reference(db_session):
    for i in range(4):
        await make_security(db_session, f"C{i}", walk(300, 70 + i))
    await make_security(db_session, "NOSECTOR", walk(300, 80), sector=None)
    await make_security(db_session, "THIN", walk(300, 81), vol=10)
    res = await sr.run_signals(db_session, NOW)
    assert res["reference_sizes"]["stock"] == 4
    rows = {(await db_session.get(Security, r.security_id)).symbol: r for r in (await db_session.execute(select(SecuritySignal))).scalars()}
    assert rows["NOSECTOR"].mom_12_1_rank is not None and rows["THIN"].mom_12_1_rank is not None and rows["THIN"].rank_universe_size == 4


async def test_independence_matrix_reports_correlated_pairs(db_session):
    for i in range(40):
        await make_security(db_session, f"X{i}", walk(300, 100 + i, drift=0.0004 + 0.00005 * (i % 9), vol=0.008 + 0.0004 * (i % 11)), vol=1_000_000 + 50_000 * i)
    res = await sr.run_signals(db_session, NOW)
    ind = res["independence"]
    assert ind["status"] == "ready" and ind["n"] == 40 and "trend_sma200~momentum_12_1" in ind["pairs"] and all(-1 <= v <= 1 for v in ind["pairs"].values())


def test_independence_needs_enough_names():
    assert sr.independence([{"quality": "ok", "kind": "stock", "sma200_ratio": 0.1, "mom_12_1": 0.2, "vol_252": 0.3, "drawdown_current": -0.1, "liquidity_value": 1e7}] * 5)["status"] == "insufficient_data"


# --- API + job -------------------------------------------------------------------------------------------------------------------

async def seeded(db_session):
    for i in range(6):
        await make_security(db_session, f"S{i}", walk(300, 200 + i, drift=0.0008 - 0.0003 * i))
    await make_security(db_session, "FRESHIPO", walk(100, 300))
    await sr.run_signals(db_session, NOW)


async def test_list_filters_and_sorts_on_signals_with_unsignaled_last(client, db_session):
    await seeded(db_session)
    allrows = (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "sort": "momentum", "order": "desc", "limit": 50})).json()["items"]
    ranks = [i["signals"]["mom_12_1_rank"] for i in allrows if i.get("signals") and i["signals"]["mom_12_1_rank"] is not None]
    assert ranks == sorted(ranks, reverse=True) and allrows[-1]["symbol"] == "FRESHIPO"       # insufficient history sorts last
    assert allrows[-1]["signals"]["quality"] == "insufficient_data" and allrows[-1]["signals"]["mom_12_1_rank"] is None
    above = (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "trend": "above"})).json()
    below = (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "trend": "below"})).json()
    assert above["total"] + below["total"] == 6 and all(i["signals"]["trend_state"] == "above" for i in above["items"])   # FRESHIPO has no 200-day state? 100 bars
    assert (await client.get("/api/v4/catalogue/securities", params={"trend": "sideways"})).status_code == 422
    vol = (await client.get("/api/v4/catalogue/securities", params={"kind": "stock", "sort": "volatility", "order": "asc"})).json()["items"]
    assert [i["signals"]["vol_252"] for i in vol if i["signals"]["vol_252"] is not None] == sorted(i["signals"]["vol_252"] for i in vol if i["signals"]["vol_252"] is not None)


async def test_signals_endpoint_families_and_wording(client, db_session):
    await seeded(db_session)
    sid = (await client.get("/api/v4/catalogue/securities", params={"q": "S0", "kind": "stock"})).json()["items"][0]["id"]
    r = (await client.get(f"/api/v4/catalogue/securities/{sid}/signals")).json()
    assert r["status"] == "ready" and r["latest"]["method_version"] == "signals-v1" and r["latest"]["origin"] == "live"
    assert set(r["families"]) >= {"trend", "risk", "liquidity", "forecast", "net_vote", "policy_version"} and r["forecast"] is None
    assert "not forecasts or recommendations" in r["note"] and len(r["history"]) == 1
    assert (await client.get(f"/api/v4/catalogue/securities/{uuid.uuid4()}/signals")).status_code == 404
    fund = Security(source_key="amfi:1", kind="mutual_fund", scheme_code="1", name="A Fund", source="amfi_navall", is_active=True, seen_at=NOW)
    db_session.add(fund)
    await db_session.commit()
    f = (await client.get(f"/api/v4/catalogue/securities/{fund.id}/signals")).json()
    assert f["status"] == "none" and "exchange-traded stocks and ETFs only" in f["message"]


async def test_refresh_and_status(client, db_session):
    from tests.test_living import setup_user

    await setup_user(db_session)
    assert (await client.post("/api/v4/catalogue/signals/refresh")).json() == {"queued": True, "already_queued": False}
    assert (await client.post("/api/v4/catalogue/signals/refresh")).json()["already_queued"] is True
    st = (await client.get("/api/v4/catalogue/signals/status")).json()
    assert st["last_job"]["status"] == "queued" and st["stored_rows"] == 0 and st["method_version"] == "signals-v1"


async def test_signals_job_end_to_end_and_chain_end_queues_it(db_session, test_engine, monkeypatch):
    from app.portfolio_intelligence import jobs as jobs_mod
    from app.portfolio_intelligence.market import jobs as mj
    from app.portfolio_intelligence.signals import jobs as sj
    from tests.test_living import setup_user

    await setup_user(db_session)
    await make_security(db_session, "AAA", walk(300, 11))
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, sj):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(sr, "utcnow", lambda: NOW)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="signals_compute", request_key="k", status="running", attempts=1, worker_token="tok", created_at=NOW)
    db_session.add(job)
    await db_session.commit()
    monkeypatch.setattr(sj, "utcnow", lambda: NOW)
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    assert job.status == "done" and job.result["inserted"] == 1 and job.result["method_version"] == "signals-v1"
    # the candle chain reporting nothing remaining queues a signals job
    assert await sj.enqueue_signals(db_session, "after-backfill", NOW) is not None


# --- Kronos job (fake model: no weights, no CPU burn) ---------------------------------------------------------------------------

class FakeKronos:
    _model_version = "fake-kronos+sc8"

    def __init__(self, fail=None, bias=0.05):
        self.fail, self.bias, self.calls = fail or {}, bias, []

    async def forecast_strict(self, symbol, candles, horizon):
        from app.models_iface.base import TimeSeriesForecast

        self.calls.append((symbol, len(candles), horizon))
        if symbol in self.fail:
            raise self.fail[symbol]
        k = len(self.calls)
        return TimeSeriesForecast(forecast_horizon=horizon, direction="bullish", predicted_return=self.bias + 0.001 * k, predicted_return_p10=-0.01, predicted_return_p90=0.1,
                                  direction_agreement=0.9, sample_count=8, confidence=0.77, input_timeframe="x", model_name="Fake", model_version=self._model_version)


async def test_forecast_shortlist_is_watched_nifty_and_one_liquid_etf_per_underlying(db_session):
    from app.models.market import Instrument
    from app.models.user import User  # noqa: F401
    from app.models.watchlist import BrokerInstrument, Watchlist, WatchlistItem
    from app.portfolio_intelligence.signals import forecast as fc
    from tests.test_living import setup_user

    await setup_user(db_session)
    inst = Instrument(symbol="N50", exchange="NSE", isin="INE000N50011", name="N50", sector="X")
    db_session.add(inst)
    await db_session.commit()
    nifty = await make_security(db_session, "N50", walk(300, 1))
    nifty.instrument_id = inst.id
    other = await make_security(db_session, "OTHER", walk(300, 2))
    watched = await make_security(db_session, "WATCHED", walk(300, 3))
    e1 = await make_security(db_session, "GOLD1", walk(300, 4), kind="etf", sector=None, vol=5_000_000)
    e2 = await make_security(db_session, "GOLD2", walk(300, 5), kind="etf", sector=None, vol=9_000_000)
    e3 = await make_security(db_session, "SILV1", walk(300, 6), kind="etf", sector=None, vol=1_000_000)
    for e, cat in ((e1, "Gold"), (e2, "Gold"), (e3, "Silver")):
        e.category = cat
    bi = BrokerInstrument(provider="angel_one", exchange="NSE", token="9", trading_symbol="WATCHED-EQ", symbol="WATCHED", name="W", series="EQ", seen_at=NOW, security_id=watched.id)
    wl = Watchlist(user_id=SINGLE_USER_ID, name="L", created_at=NOW)
    db_session.add_all([bi, wl])
    await db_session.flush()
    db_session.add(WatchlistItem(watchlist_id=wl.id, broker_instrument_id=bi.id, added_at=NOW))
    await db_session.commit()
    await sr.run_signals(db_session, NOW)            # liquidity per ETF comes from the stored signals
    names = {(await db_session.get(Security, i)).symbol for i in await fc.shortlist(db_session)}
    assert names == {"WATCHED", "N50", "GOLD2", "SILV1"}     # not OTHER; only the more liquid gold ETF


async def test_forecast_run_stores_point_in_time_rows_marks_them_uncounted_and_never_reruns(db_session):
    from app.portfolio_intelligence.signals import forecast as fc
    from app.models.market import Instrument

    inst = Instrument(symbol="A", exchange="NSE", isin="INE000A00011", name="A", sector="X")
    db_session.add(inst)
    await db_session.commit()
    s = await make_security(db_session, "AAA", walk(300, 1), full_refetches=2)
    s.instrument_id = inst.id
    await db_session.commit()
    model = FakeKronos()
    r = await fc.run_forecasts(db_session, NOW, model=model)
    assert r["done"] == 1 and r["errors"] == [] and model.calls == [("AAA", 300, "30d")]
    row = (await db_session.execute(select(fc.SecurityForecast))).scalar_one()
    assert (row.origin, row.model_version, row.horizon, row.as_of_date, row.bars_used, row.sample_count) == ("live", "fake-kronos+sc8", "30d", EXPECTED, 300, 8)
    assert row.calibrated_confidence is None and row.input_marker.startswith("2:300:2026-09-30:")    # the model's own 0.77 is NOT stored as a probability
    assert row.detail["counts_toward_checks"] is False and "not a probability" in row.detail["calibration"]
    again = await fc.run_forecasts(db_session, NOW + timedelta(hours=2), model=model)
    assert again["done"] == 0 and len(model.calls) == 1                                                # same data: nothing to do


async def test_forecast_failures_are_reported_by_type_not_swallowed(db_session, test_engine, monkeypatch):
    from app.models.market import Instrument
    from app.portfolio_intelligence import jobs as jobs_mod
    from app.portfolio_intelligence.signals import forecast as fc
    from tests.test_living import setup_user

    await setup_user(db_session)
    inst = Instrument(symbol="A", exchange="NSE", isin="INE000A00011", name="A", sector="X")
    db_session.add(inst)
    await db_session.commit()
    s = await make_security(db_session, "AAA", walk(300, 1))
    s.instrument_id = inst.id
    await db_session.commit()
    boom = FakeKronos(fail={"AAA": ModuleNotFoundError("No module named 'model'")})
    r = await fc.run_forecasts(db_session, NOW, model=boom)
    assert r["done"] == 0 and r["errors"][0]["error"] == "ModuleNotFoundError"            # a missing vendor path is visible, not "no signal"
    assert (await db_session.execute(select(func.count()).select_from(fc.SecurityForecast))).scalar_one() == 0
    # through the job: nothing worked this round -> not "done"; retried with backoff
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(fc, "AsyncSessionLocal", factory)
    monkeypatch.setattr(fc, "utcnow", lambda: NOW)
    import app.models_iface.kronos as km
    monkeypatch.setattr(km, "KronosModel", lambda: boom)
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="kronos_forecast", request_key="k", status="running", attempts=1, worker_token="tok", created_at=NOW)
    db_session.add(job)
    await db_session.commit()
    await jobs_mod.process_portfolio_job(job.id, "tok")
    await db_session.refresh(job)
    assert job.status == "queued" and job.error_code == "UNAVAILABLE" and job.result["errors"][0]["error"] == "ModuleNotFoundError"


async def test_forecast_chunks_chain_and_only_fresh_long_histories_qualify(db_session, monkeypatch):
    from app.models.market import Instrument
    from app.portfolio_intelligence.signals import forecast as fc

    monkeypatch.setattr(fc, "CHUNK", 2)
    for i in range(5):
        inst = Instrument(symbol=f"N{i}", exchange="NSE", isin=f"INE00{i}A00011", name=f"N{i}", sector="X")
        db_session.add(inst)
        await db_session.commit()
        s = await make_security(db_session, f"N{i}", walk(300, i))
        s.instrument_id = inst.id
    stale_inst = Instrument(symbol="OLD", exchange="NSE", isin="INE009A00011", name="OLD", sector="X")
    db_session.add(stale_inst)
    await db_session.commit()
    old = await make_security(db_session, "OLD", walk(300, 9), last=EXPECTED - timedelta(days=30))
    old.instrument_id = stale_inst.id
    short_inst = Instrument(symbol="NEW", exchange="NSE", isin="INE008A00011", name="NEW", sector="X")
    db_session.add(short_inst)
    await db_session.commit()
    new = await make_security(db_session, "NEW", walk(120, 8))
    new.instrument_id = short_inst.id
    await db_session.commit()
    model = FakeKronos()
    r1 = await fc.run_forecasts(db_session, NOW, model=model, limit=2)
    assert r1["done"] == 2 and r1["remaining_after"] == 3                                   # 5 eligible; stale and short histories excluded
    r2 = await fc.run_forecasts(db_session, NOW, model=model, limit=10)
    assert r2["done"] == 3 and {c[0] for c in model.calls} == {f"N{i}" for i in range(5)}


async def test_signals_endpoint_shows_the_forecast_with_relative_rank_only_against_enough_peers(client, db_session):
    from app.portfolio_intelligence.signals import forecast as fc

    await seeded(db_session)
    sid0 = (await client.get("/api/v4/catalogue/securities", params={"q": "S0", "kind": "stock"})).json()["items"][0]["id"]

    async def add_forecast(security_id, ret):
        db_session.add(fc.SecurityForecast(security_id=security_id, as_of_date=EXPECTED, model_version="fake-kronos+sc8", horizon="30d", origin="live", computed_at=NOW, input_marker="x",
                                           bars_used=300, sample_count=8, predicted_return=D(str(ret)), p10=D("0.0"), p90=D("0.2"), direction="bullish", direction_agreement=D("0.9"), detail={}))

    await add_forecast(uuid.UUID(sid0), 0.07)
    await db_session.commit()
    r = (await client.get(f"/api/v4/catalogue/securities/{sid0}/signals")).json()
    f = r["forecast"]
    assert f["counts_toward_checks"] is False and f["calibrated_confidence"] is None and "leaned strongly upward" in f["bias_warning"]
    assert r["families"]["forecast"]["vote"] == 0 and r["families"]["net_vote"] == r["families"]["trend"]["vote"] + r["families"]["risk"]["vote"]
    assert f["relative_rank"] is None and f["peers_on_date"] == 1                      # one forecast: no relative standing is claimed
    for i in range(11):                                                                # 12 forecasts in all; S0's 0.07 is above 4 and ties with 1 other
        extra = await make_security(db_session, f"R{i}", walk(100, 500 + i))
        await add_forecast(extra.id, 0.03 + 0.01 * i)
    await db_session.commit()
    f2 = (await client.get(f"/api/v4/catalogue/securities/{sid0}/signals")).json()["forecast"]
    assert f2["peers_on_date"] == 12 and f2["relative_rank"] == round(100 * 5 / 12, 1)  # (4 below + half of 2 ties, itself and R4) / 12


async def test_a_new_trading_day_gets_its_own_forecast_and_the_old_one_is_kept(db_session):
    """The nightly claim, tested: once the history gains a day, the shortlist is forecast again for that day, and yesterday's forecast stays as it was."""
    from app.portfolio_intelligence.signals import forecast as fc
    from app.models.market import Instrument

    inst = Instrument(symbol="A", exchange="NSE", isin="INE000A00011", name="A", sector="X")
    db_session.add(inst)
    await db_session.commit()
    s = await make_security(db_session, "AAA", walk(300, 1), full_refetches=0)
    s.instrument_id = inst.id
    await db_session.commit()
    model = FakeKronos()
    assert (await fc.run_forecasts(db_session, NOW, model=model))["done"] == 1
    assert (await fc.run_forecasts(db_session, NOW + timedelta(hours=1), model=model))["done"] == 0        # same data: nothing to do

    # the next trading day's candle arrives (the nightly incremental fetch) and the sync record moves forward
    from app.models.securities import CandleSync, SecurityCandle
    nxt = EXPECTED + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    db_session.add(SecurityCandle(security_id=s.id, trade_date=nxt, open=D("100"), high=D("101"), low=D("99"), close=D("100.5"), volume=1_000_000))
    sync = (await db_session.execute(select(CandleSync).where(CandleSync.security_id == s.id))).scalar_one()
    sync.last_date, sync.row_count = nxt, sync.row_count + 1
    await db_session.commit()
    later = NOW + timedelta(days=1)
    assert (await fc.run_forecasts(db_session, later, model=model))["done"] == 1                          # a fresh forecast for the new day
    rows = (await db_session.execute(select(fc.SecurityForecast).order_by(fc.SecurityForecast.as_of_date))).scalars().all()
    assert [r.as_of_date for r in rows] == [EXPECTED, nxt] and rows[0].computed_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)   # the old one is untouched
