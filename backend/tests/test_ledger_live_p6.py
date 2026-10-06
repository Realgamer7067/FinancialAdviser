"""P6 live ledger: point-in-time scoring, insert-only outcomes, versioning on re-base, plan origins, live verdicts, the study store, the job step."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import AllocationPlan, CandleSync, LedgerOutcome, LedgerStudy, Security, SecurityForecast, SecuritySignal, SuggestionLog
from app.portfolio_intelligence.ledger import jobs as lj
from app.portfolio_intelligence.ledger import live as lv
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger import score as sc
from tests.test_ledger_p6 import market
from tests.test_signals_p2 import EXPECTED, NOW, make_security, walk, weekdays_ending

D = Decimal
KNOWN = date(2026, 9, 30)             # NOW is 17:30 IST on this date: the signal is known after this close


# --- pure helpers -----------------------------------------------------------------------------------------------------------------

def test_entry_is_the_first_close_strictly_after_the_day_it_was_known():
    ds = [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    loc = sc.locate(ds, date(2026, 9, 30), 2)
    assert loc == {"state": "ready", "i": 3, "j": 5}                                # entry 10-01 (NOT the 09-30 close it was computed on), exit 2 sessions later
    assert sc.locate(ds, date(2026, 9, 30), 3) == {"state": "waiting", "entry_idx": 3}   # the full horizon does not exist yet: nothing is scored
    assert sc.locate(ds, date(2026, 10, 5), 1) == {"state": "waiting"}                  # no close after it yet
    assert sc.known_date(datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)) == date(2026, 9, 30)
    assert sc.known_date(datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)) == date(2026, 10, 1)   # 01:30 IST the next day


def test_session_arithmetic_and_thinning_of_overlapping_dates():
    assert sc.add_sessions(date(2026, 10, 1), 1) == date(2026, 10, 2) and sc.add_sessions(date(2026, 10, 2), 1) == date(2026, 10, 5)
    daily = weekdays_ending(date(2026, 11, 30), 60)
    kept = lv.thin_dates(daily, 21)
    assert len(kept) == 3 and all(sc.add_sessions(a, 21) <= b for a, b in zip(kept, kept[1:]))


def test_the_live_registry_is_frozen():
    # live-v1 (price-return outcomes, hash 4ba78678...) was superseded by live-v2 (total-return outcomes) on 2026-10-01, and live-v2 (hash a4688b8e...)
    # by live-v3 (hash 3b602de5..., adds the checklist score as claim L8) and that by live-v4 (adds the value/quality/momentum composite as L9), all on 2026-10-02, each BEFORE any live outcome existed.
    assert R.live_registry_hash() == "70f0a60ec4e999ea37a0e85d1f3766254b6239c3657e0f9561e541f7ba6e4f05" and R.LIVE_VERSION == "live-v4" and R.LIVE_OUTCOME_BASIS == "total_return"
    ids = [c["id"] for c in R.LIVE_CLAIMS]
    assert "L7_plan_accounting" in ids and next(c for c in R.LIVE_CLAIMS if c["id"] == "L7_plan_accounting")["type"] == "accounting"
    assert lv.K_LIVE == 8 and lv.ALPHA_LIVE == pytest.approx(0.05 / 8)


# --- DB: scoring ------------------------------------------------------------------------------------------------------------------------

def px_series(start, n, last, step=0.002):
    return [start * (1 + step) ** i for i in range(n)]


async def stock(db, symbol, closes, last, sector="X", kind="stock"):
    return await make_security(db, symbol, closes, last=last, kind=kind, sector=sector)


async def sig_row(db, sec, **kw):
    base = dict(security_id=sec.id, as_of_date=KNOWN, method_version="signals-v1", origin="live", computed_at=NOW, history_len=300, input_marker="m", quality="ok", universe="stock",
                sma200_ratio=0.1, mom_12_1=0.2, vol_252=0.3)
    base.update(kw)
    row = SecuritySignal(**base)
    db.add(row)
    await db.commit()
    return row


async def test_a_signal_is_scored_from_the_next_close_with_both_benchmarks(db_session):
    last = date(2026, 11, 10)                                                    # plenty of candles after the signal date
    a = await stock(db_session, "AAA", px_series(100, 300, last, 0.002), last)
    b = await stock(db_session, "BBB", px_series(100, 300, last, 0.001), last)
    etf = await stock(db_session, "NIFTYBEES", px_series(100, 300, last, 0.0005), last, kind="etf")
    await sig_row(db_session, a, sma200_ratio=0.12)
    r = await sc.score_pending(db_session, datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    assert r["scored"] >= 4 and r["missing_exit"] == 0                          # four signal claims for this one row
    out = (await db_session.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return"))).scalar_one()
    ds = weekdays_ending(last, 300)
    i = ds.index(date(2026, 10, 1))
    assert (out.entry_date, out.exit_date, out.horizon_sessions, out.status, out.origin, out.version) == (ds[i], ds[i + 21], 21, "scored", "live", 1)
    exp = D(str(100 * 1.002 ** (i + 21))) / D(str(100 * 1.002 ** i)) - 1
    assert abs(out.fwd_return - exp) < D("1e-9") and out.feature == D("0.12") and out.input_marker == "m"
    uni = (D(str(1.002 ** 21)) + D(str(1.001 ** 21))) / 2 - 1                    # equal-weight over the two STOCKS only; the ETF is the secondary benchmark
    assert abs(out.universe_return - uni) < D("1e-9") and abs(out.etf_return - (D(str(1.0005 ** 21)) - 1)) < D("1e-9")
    assert out.fwd_vol is not None and out.fwd_vol >= 0


async def test_a_partial_horizon_is_never_scored_and_scoring_is_idempotent(db_session):
    last = date(2026, 10, 15)                                                    # only 10 sessions after the signal: a 21-session horizon is not complete
    a = await stock(db_session, "AAA", px_series(100, 300, last), last)
    await sig_row(db_session, a)
    now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    r = await sc.score_pending(db_session, now)
    assert r["scored"] == 0 and r["waiting"] >= 1 and (await db_session.execute(select(func.count()).select_from(LedgerOutcome))).scalar_one() == 0
    # the candles arrive; now it scores, once
    for d in weekdays_ending(date(2026, 11, 20), 40)[-30:]:
        if d > last:
            db_session.add(__import__("app.models.securities", fromlist=["SecurityCandle"]).SecurityCandle(security_id=a.id, trade_date=d, open=D(150), high=D(151), low=D(149), close=D(150), volume=1000))
    await db_session.commit()
    first = await sc.score_pending(db_session, datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc))
    again = await sc.score_pending(db_session, datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc))
    assert first["scored"] >= 4 and again["scored"] == 0 and again["already_scored"] >= 4
    assert (await db_session.execute(select(func.count()).select_from(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return"))).scalar_one() == 1


async def test_an_exit_that_never_arrives_is_recorded_as_missing_not_dropped(db_session):
    last = date(2026, 10, 15)
    a = await stock(db_session, "HALTED", px_series(100, 300, last), last)       # the stock stops trading
    await sig_row(db_session, a)
    r = await sc.score_pending(db_session, datetime(2026, 12, 30, 12, 0, tzinfo=timezone.utc))   # months past the exit date
    assert r["missing_exit"] >= 4 and r["scored"] == 0
    rows = (await db_session.execute(select(LedgerOutcome))).scalars().all()
    assert rows and all(x.status == "missing_exit" and x.fwd_return is None for x in rows)
    again = await sc.score_pending(db_session, datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc))
    assert again["missing_exit"] == 0 and again["already_scored"] >= 4                          # recorded once


async def test_a_rebased_history_writes_a_new_version_and_leaves_the_old_row_alone(db_session):
    last = date(2026, 11, 10)
    a = await stock(db_session, "AAA", px_series(100, 300, last), last)
    await sig_row(db_session, a)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    await sc.score_pending(db_session, now)
    old = (await db_session.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return"))).scalar_one()
    old_id, old_ret = old.id, old.fwd_return
    sync = await db_session.get(CandleSync, a.id)
    sync.full_refetches = 1                                                         # the source re-adjusted history
    await db_session.commit()
    r = await sc.score_pending(db_session, now + timedelta(days=1))
    assert r["rebased_rewritten"] >= 4
    rows = (await db_session.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return").order_by(LedgerOutcome.version))).scalars().all()
    assert [x.version for x in rows] == [1, 2] and rows[0].id == old_id and rows[0].fwd_return == old_ret and rows[1].full_refetches == 1
    latest = await lv._latest_scored(db_session, "L1_trend_return")
    assert len(latest) == 1 and latest[0].version == 2                              # statistics use the newest version only


async def test_forecasts_observations_and_owner_plans_are_scored_but_verification_what_if_and_watched_are_not(db_session):
    from tests.test_decisions import ISIN_REL  # noqa: F401
    from tests.test_signals_p2 import make_security as ms

    last = date(2026, 11, 20)
    a = await stock(db_session, "AAA", px_series(100, 330, last), last)
    from app.core.single_user import SINGLE_USER_ID as U
    from app.models.user import User

    db_session.add(User(id=U, email="u@l", full_name="U", hashed_password="x"))
    await db_session.commit()
    db_session.add(SecurityForecast(security_id=a.id, as_of_date=KNOWN, model_version="k", horizon="30d", origin="live", computed_at=NOW, input_marker="m", bars_used=300, sample_count=8,
                                    predicted_return=D("0.16"), p10=D(0), p90=D("0.3"), direction="bullish", direction_agreement=D("0.9"), detail={}))
    for ctx in ("held", "watched"):
        db_session.add(SuggestionLog(user_id=U, fingerprint=f"signal_change:trend_below:{a.id}:{ctx}", kind="trend_below", security_id=a.id, context=ctx, trigger_date=KNOWN, as_of_date=KNOWN,
                                     method_version="suggest-v1", origin="live", signal_input_marker="m", metrics={}, logged_at=NOW))
    leg = {"instrument_id": str(a.id), "planned_debit": "5000", "symbol": "AAA"}
    for origin in ("owner", "verification", "what_if"):
        db_session.add(AllocationPlan(user_id=U, inputs_hash=origin, policy_version="p", engine_version="e", new_money=D(5000), what_if_band=None, status="ready", origin=origin, params={}, prices={},
                                      result={"legs": [leg]}, created_at=NOW))
    await db_session.commit()
    await sc.score_pending(db_session, datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc))
    out = (await db_session.execute(select(LedgerOutcome))).scalars().all()
    by = {}
    for o in out:
        by.setdefault(o.claim_id, []).append(o)
    assert [o.horizon_sessions for o in by["L5_kronos_ic"]] == [30] and by["L5_kronos_ic"][0].feature == D("0.16")
    assert len(by["L6_trend_break_held"]) == 1 and by["L6_trend_break_held"][0].direction == -1                # held yes, watched no
    assert len(by["L7_plan_accounting"]) == 1 and by["L7_plan_accounting"][0].subject_key.endswith(str(a.id))   # only the owner plan


async def test_outcomes_are_insert_only_by_constraint(db_session):
    from sqlalchemy.exc import IntegrityError

    last = date(2026, 11, 10)
    a = await stock(db_session, "AAA", px_series(100, 300, last), last)
    await sig_row(db_session, a)
    await sc.score_pending(db_session, datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    row = (await db_session.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return"))).scalar_one()
    db_session.add(LedgerOutcome(claim_id=row.claim_id, subject_type="signal", subject_key=row.subject_key, security_id=row.security_id, as_of_date=row.as_of_date, known_at=NOW,
                                 horizon_sessions=21, version=1, status="scored", origin="live", scored_at=NOW))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --- live statistics ------------------------------------------------------------------------------------------------------------------------

async def plant(db, claim_id, n_dates, *, effect, names=40, gap=35, seed=0, horizon=21, noise=0.05, start=date(2026, 1, 5)):
    """Directly insert scored outcomes for `n_dates` as-of dates with a planted rank relationship between feature and forward return."""
    rng = np.random.default_rng(seed)
    secs = [await make_security(db, f"P{claim_id[:2]}{seed}{i}", walk(260, 50 + i)) for i in range(names)]
    for k in range(n_dates):
        d = start + timedelta(days=gap * k)
        f = rng.normal(0, 1, names)
        y = effect * f + rng.normal(0, 1, names) * noise
        for s, fi, yi in zip(secs, f, y):
            db.add(LedgerOutcome(claim_id=claim_id, subject_type="signal", subject_key=f"{s.id}:{d}", security_id=s.id, as_of_date=d, known_at=NOW, horizon_sessions=horizon, version=1, status="scored",
                                 entry_date=d, exit_date=d, fwd_return=D(str(round(yi, 5))), fwd_vol=D(str(round(abs(yi) + 0.2, 5))), universe_return=D(0), feature=D(str(round(fi, 5))),
                                 origin="live", scored_at=NOW))
    await db.commit()


async def test_live_ic_claim_climbs_the_ladder_with_dates_and_never_skips_the_requirements(db_session):
    claim = next(c for c in R.LIVE_CLAIMS if c["id"] == "L2_momentum_return")
    await plant(db_session, claim["id"], 8, effect=0.06)
    s = await lv.claim_status(db_session, claim)
    assert s["verdict"] == "too_early" and s["n_dates_used"] == 8                                           # under the 12-date minimum for any verdict
    await plant(db_session, claim["id"], 12, effect=0.06, seed=1, start=date(2027, 1, 4))
    s2 = await lv.claim_status(db_session, claim)
    assert s2["n_dates_used"] > 12 and s2["verdict"] in ("promising", "underpowered", "no_evidence")        # enough for a verdict, not for `earned`
    assert s2["verdict"] != "earned" and s2["dates_needed_for_earned"] == 24


async def test_a_strong_live_effect_with_enough_dates_and_net_of_cost_gain_is_earned_and_a_null_is_not(db_session):
    strong = next(c for c in R.LIVE_CLAIMS if c["id"] == "L2_momentum_return")
    await plant(db_session, strong["id"], 30, effect=0.08, seed=2, names=45)
    s = await lv.claim_status(db_session, strong)
    assert s["n_dates_used"] == 30 and s["mean"] > 0.7 and s["net_of_cost_lower_bound"] > 0 and s["verdict"] == "earned"
    assert "lets the owner review a weight" in s["verdict_meaning"]                                           # even `earned` only permits a review
    null = next(c for c in R.LIVE_CLAIMS if c["id"] == "L1_trend_return")
    await plant(db_session, null["id"], 30, effect=0.0, seed=3, names=45)
    n = await lv.claim_status(db_session, null)
    assert n["verdict"] in ("no_evidence", "underpowered") and n["verdict"] != "earned"


async def test_a_gain_that_does_not_survive_the_round_trip_cost_is_only_promising(db_session):
    c = next(c for c in R.LIVE_CLAIMS if c["id"] == "L2_momentum_return")
    await plant(db_session, c["id"], 30, effect=0.0035, seed=4, names=45, noise=0.0004)                    # a near-perfect rank relationship, but a tiny return spread
    s = await lv.claim_status(db_session, c)
    assert s["mean"] > 0.8 and s["net_of_cost_lower_bound"] < 0 and s["verdict"] == "promising"


async def test_the_risk_claim_uses_forward_volatility_and_the_event_claim_flips_its_sign(db_session):
    risk = next(c for c in R.LIVE_CLAIMS if c["id"] == "L4_vol_persistence")
    await plant(db_session, risk["id"], 14, effect=1.0, seed=5, names=40)
    s = await lv.claim_status(db_session, risk)
    assert s["n_dates_used"] == 14 and s["mean"] is not None
    ev = next(c for c in R.LIVE_CLAIMS if c["id"] == "L6_trend_break_held")
    secs = [await make_security(db_session, f"E{i}", walk(260, 70 + i)) for i in range(14)]
    for k, sec in enumerate(secs):
        d = date(2026, 1, 5) + timedelta(days=45 * k)
        db_session.add(LedgerOutcome(claim_id=ev["id"], subject_type="suggestion", subject_key=f"{sec.id}:{d}", security_id=sec.id, as_of_date=d, known_at=NOW, horizon_sessions=21, version=1,
                                     status="scored", entry_date=d, exit_date=d, fwd_return=D("-0.03"), universe_return=D("0.01"), direction=-1, origin="live", scored_at=NOW))
    await db_session.commit()
    e = await lv.claim_status(db_session, ev)
    assert e["mean"] == pytest.approx(0.04) and e["n_dates_used"] == 14                                    # fell 4 points more than the universe, so the "falls" claim holds (positive)


async def test_plan_accounting_is_labelled_and_has_no_verdict(db_session):
    last = date(2026, 11, 20)
    a = await stock(db_session, "AAA", px_series(100, 330, last), last)
    db_session.add(LedgerOutcome(claim_id="L7_plan_accounting", subject_type="plan_leg", subject_key="p:1", security_id=a.id, as_of_date=KNOWN, known_at=NOW, horizon_sessions=21, version=1,
                                 status="scored", fwd_return=D("0.02"), etf_return=D("0.01"), feature=D("5000"), origin="live", scored_at=NOW))
    await db_session.commit()
    s = await lv.claim_status(db_session, next(c for c in R.LIVE_CLAIMS if c["type"] == "accounting"))
    assert s["verdict"] is None and s["label"].startswith("ACCOUNTING") and s["plan_weighted_return"] == pytest.approx(0.02) and s["market_etf_average_return_same_dates"] == pytest.approx(0.01)


# --- the study store, API and job ---------------------------------------------------------------------------------------------------------------

async def test_the_study_is_stored_once_per_version_and_data_and_cannot_be_rerolled(db_session, monkeypatch):
    close, vol = market(seed=1, kappa=0.0012)

    async def fake_panel(db):
        return close, vol, close, {"securities": close.shape[1], "sessions": len(close), "first": "2021-01-04", "last": "2024-06-30", "data_marker": "150:900:x:0"}

    monkeypatch.setattr(lj.panel, "load_panel", fake_panel)
    first = await lj.run_and_store_study(db_session, NOW)
    second = await lj.run_and_store_study(db_session, NOW + timedelta(days=1))
    assert first["created"] is True and second["created"] is False and second["study_id"] == first["study_id"]
    row = (await db_session.execute(select(LedgerStudy))).scalar_one()
    assert row.study_version == "study-v2" and row.registry_hash == R.registry_hash_v2() and row.result["outcome_basis"] == "total_return" and row.result["claims"][1]["verdict"] == "backtest_suggestive"


async def test_the_api_serves_the_registry_study_and_live_status(client, db_session, monkeypatch):
    reg = (await client.get("/api/v4/ledger/registry")).json()
    assert reg["registry_hash"] == R.registry_hash() and reg["registry_hash_v2"] == R.registry_hash_v2() and reg["live_registry_hash"] == R.live_registry_hash() and len(reg["biases"]) >= 5 and "frozen and hashed" in reg["rule"]
    assert (await client.get("/api/v4/ledger/study")).json()["status"] == "none"
    from tests.test_living import setup_user

    await setup_user(db_session)
    assert (await client.post("/api/v4/ledger/study/run")).json() == {"queued": True, "already_queued": False}
    close, vol = market(seed=1, kappa=0.0012)

    async def fake_panel(db):
        return close, vol, close, {"securities": 150, "sessions": 900, "first": "a", "last": "b", "data_marker": "m1"}

    monkeypatch.setattr(lj.panel, "load_panel", fake_panel)
    await lj.run_and_store_study(db_session, NOW)
    st = (await client.get("/api/v4/ledger/study")).json()
    assert st["status"] == "ready" and st["versions_tried"] == 1 and st["study_version"] == "study-v2" and st["frozen_hash_matches_code"] is True and st["evidence"] == "backtest" and len(st["claims"]) == 4
    assert all(c["verdict"] != "earned" for c in st["claims"])                                                # a backtest can never earn
    live = (await client.get("/api/v4/ledger/live")).json()
    assert live["k"] == 8 and len(live["claims"]) == 9 and "changes nothing automatically" in live["rule"] and live["outcomes_scored"] == 0
    assert all(c["scored"] == 0 and c["verdict"] in ("no_data", None) for c in live["claims"])


async def test_plans_record_their_origin(client, db_session):
    from tests.test_allocation_p3 import seed_market_with_user

    await seed_market_with_user(db_session)
    plain = (await client.post("/api/v4/allocation/plan", json={"new_money": "30000"})).json()
    what_if = (await client.post("/api/v4/allocation/plan", json={"new_money": "30000", "what_if_band": "moderate"})).json()
    origins = {r.id: r.origin for r in (await db_session.execute(select(AllocationPlan))).scalars()}
    assert origins[uuid.UUID(plain["plan_id"])] == "owner" and origins[uuid.UUID(what_if["plan_id"])] == "what_if"


async def test_the_signals_job_runs_the_scoring_step_and_survives_its_failure(db_session, test_engine, monkeypatch):
    from app.portfolio_intelligence import jobs as jobs_mod
    from app.portfolio_intelligence.signals import jobs as sj
    from app.portfolio_intelligence.signals import run as sr
    from tests.test_living import setup_user

    await setup_user(db_session)
    await make_security(db_session, "AAA", walk(300, 1))
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, sj, lj):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(sj, "utcnow", lambda: NOW)
    monkeypatch.setattr(sr, "utcnow", lambda: NOW)

    async def run_job():
        job = PortfolioJob(user_id=SINGLE_USER_ID, kind="signals_compute", request_key=str(uuid.uuid4()), status="running", attempts=1, worker_token="tok", created_at=NOW)
        db_session.add(job)
        await db_session.commit()
        await jobs_mod.process_portfolio_job(job.id, "tok")
        await db_session.refresh(job)
        return job

    ok = await run_job()
    assert ok.status == "done" and "subjects" in ok.result["ledger"] and ok.result["ledger"]["scored"] == 0

    async def boom(db, now):
        raise RuntimeError("no")

    monkeypatch.setattr(lj, "score_pending", boom)
    bad = await run_job()
    assert bad.status == "done" and bad.result["ledger"] == {"error": "RuntimeError"}


async def test_live_outcomes_include_dividends_paid_between_entry_and_exit(db_session):
    from app.models.securities import CorporateAction

    last = date(2026, 11, 10)
    a = await stock(db_session, "AAA", [100.0] * 300, last)
    b = await stock(db_session, "BBB", [100.0] * 300, last)
    ds = weekdays_ending(last, 300)
    ex = ds[ds.index(date(2026, 10, 1)) + 5]                                      # a Rs 2 dividend a week into the holding period
    db_session.add(CorporateAction(symbol="AAA", ex_date=ex, subject="Dividend - Rs 2 Per Share", kind="dividend", amount=D(2), needs_review=False, source="nse", fetched_at=NOW))
    db_session.add(CorporateAction(symbol="AAA", ex_date=ex + timedelta(days=1), subject="Dividend - Rs Per Share", kind="dividend", needs_review=True, source="nse", fetched_at=NOW))
    await db_session.commit()
    await sig_row(db_session, a)
    await sc.score_pending(db_session, datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    out = (await db_session.execute(select(LedgerOutcome).where(LedgerOutcome.claim_id == "L1_trend_return"))).scalar_one()
    assert out.fwd_price_return == 0 and abs(out.fwd_return - D("0.02")) < D("1e-9")           # total return carries the dividend, price return does not
    assert out.dividend_flags == "applied=1;skipped=needs_review:1"                                 # and the unparseable one is reported, not guessed
    assert abs(out.universe_return - D("0.01")) < D("1e-9")                                         # equal-weight over AAA (+2%) and BBB (0%), both on total return


async def test_the_checklist_score_is_a_live_claim_scored_against_what_followed(db_session):
    """L8: a score stored on day D is entered at the next close after it was known and scored 21 sessions later, like any signal."""
    from app.models.securities import SecurityScore
    from app.portfolio_intelligence.scoring.checklist import CHECKLIST_VERSION
    from app.portfolio_intelligence.ledger import score as sc

    claim = next(c for c in R.LIVE_CLAIMS if c["id"] == "L8_checklist_return")
    assert claim["source"] == "score" and claim["type"] == "ic" and claim["outcome"] == "return" and claim["horizon"] == 21
    # scores are subjects only when they carry a number and belong to the registered method version
    from tests.test_signals_p2 import NOW, make_security, walk

    s = await make_security(db_session, "SCR", walk(300, 3))
    db_session.add_all([
        SecurityScore(security_id=s.id, as_of_date=NOW.date(), method_version=CHECKLIST_VERSION, computed_at=NOW, score=71.5, coverage=1, status="eligible", detail={}),
        SecurityScore(security_id=s.id, as_of_date=NOW.date() - timedelta(days=1), method_version="checklist-other", computed_at=NOW, score=10, coverage=1, status="eligible", detail={}),
        SecurityScore(security_id=s.id, as_of_date=NOW.date() - timedelta(days=2), method_version=CHECKLIST_VERSION, computed_at=NOW, score=None, coverage=0.3, status="not_scored", detail={}),
    ])
    await db_session.commit()
    subs = [x for x in await sc._subjects(db_session) if x["type"] == "score"]
    assert len(subs) == 1 and subs[0]["feature"] == 71.5 and subs[0]["claim"]["id"] == "L8_checklist_return"


async def test_the_value_quality_momentum_composite_is_a_live_claim_scored_like_the_others(db_session):
    from app.models.securities import SecurityScore
    from app.portfolio_intelligence.ledger import score as sc
    from app.portfolio_intelligence.scoring.ranking import RANK_VERSION
    from tests.test_signals_p2 import NOW, make_security, walk

    claim = next(c for c in R.LIVE_CLAIMS if c["id"] == "L9_rank_return")
    assert claim["source"] == "rank" and claim["type"] == "ic" and claim["outcome"] == "return" and claim["horizon"] == 21
    s = await make_security(db_session, "RNK", walk(300, 9))
    db_session.add_all([SecurityScore(security_id=s.id, as_of_date=NOW.date(), method_version=RANK_VERSION, computed_at=NOW, score=66.5, coverage=1, status="eligible", detail={}),
                        SecurityScore(security_id=s.id, as_of_date=NOW.date() - timedelta(days=1), method_version=RANK_VERSION, computed_at=NOW, score=None, coverage=0.3, status="not_scored", detail={})])
    await db_session.commit()
    subs = [x for x in await sc._subjects(db_session) if x["type"] == "rank"]
    assert len(subs) == 1 and subs[0]["feature"] == 66.5 and subs[0]["claim"]["id"] == "L9_rank_return"
