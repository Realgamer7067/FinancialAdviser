"""P4: change detection with hysteresis, quality gating, wording, read-only GET, inbox lifecycle, the review-doesn't-resolve regression."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.living import InboxIssue
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import CorporateAction, Security, SuggestionLog
from app.models.watchlist import BrokerInstrument, Watchlist, WatchlistItem
from app.portfolio_intelligence.signals import run as sr
from app.portfolio_intelligence.suggestions import build as sb
from app.portfolio_intelligence.suggestions import detect as dt
from app.portfolio_intelligence.suggestions import persist as sp
from tests.test_decisions import ISIN_REL, ISIN_TCS, complete_setup, run_reviews  # noqa: F401 (fixture)
from tests.test_signals_p2 import EXPECTED, NOW, make_security, weekdays_ending

D = Decimal


def days(n):
    return weekdays_ending(EXPECTED, n)


def rising(n=520, seed=1, drift=0.0006, noise=0.002):
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(drift, noise, n))))


# --- state machines ---------------------------------------------------------------------------------------------------------------

def test_a_steady_uptrend_is_above_and_not_a_change():
    c = rising()
    r = dt.analyze(days(len(c)), c)
    assert r["status"] == "ok" and r["trend"]["state"] == "above" and r["trend"]["changed"] is False and r["trend"]["changes_1y"] == 0
    assert r["drawdown"]["on"] is False and r["volatility"]["on"] is False


def test_hysteresis_noise_around_the_average_is_not_a_state_change_but_the_plain_rule_cries_wolf():
    c = rising(300)
    sma = float(np.mean(c[-200:]))
    wobble = [sma * (1 + 0.02 * np.sin(i)) for i in range(220)]                  # +/-2% around the average: inside the 3% margin
    c = c + wobble
    r = dt.analyze(days(len(c)), c)
    assert r["trend"]["state"] == "above" and r["trend"]["changes_1y"] == 0 and r["trend"]["changed"] is False
    assert r["trend"]["raw_crossings_1y"] >= 20                                    # the plain rule would have fired dozens of times


def test_a_break_below_the_average_needs_the_margin_and_the_dwell():
    c = rising(520)
    brief = c[:-2] + [c[-2] * 0.85, c[-1] * 0.85]                                  # two closes below the margin: not enough
    assert dt.analyze(days(520), brief)["trend"]["state"] == "above"
    held_down = c[:-6] + [x * 0.85 for x in c[-6:]]                                 # six closes: confirmed on the 3rd
    r = dt.analyze(days(520), held_down)["trend"]
    assert r["state"] == "below" and r["changed"] is True and r["previous"] == "above" and r["sessions_since"] == 3 and r["changes_1y"] == 1
    mild = c[:-6] + [x * 0.97 for x in c[-6:]]                                      # ~9% above the average -> only ~6%: inside the margin, still above
    assert dt.analyze(days(520), mild)["trend"]["state"] == "above"


def test_recovery_needs_the_margin_too():
    c = rising(520)
    down = c[:-40] + [x * 0.80 for x in c[-40:]]
    assert dt.analyze(days(520), down)["trend"]["state"] == "below"
    sma_like = float(np.mean(down[-200:]))
    back_a_little = down[:-5] + [sma_like * 1.01] * 5                               # back above the average but inside the margin
    assert dt.analyze(days(520), back_a_little)["trend"]["state"] == "below"
    back_clearly = down[:-5] + [sma_like * 1.08] * 5
    r = dt.analyze(days(520), back_clearly)["trend"]
    assert r["state"] == "above" and r["previous"] == "below" and r["changed"] is True


def test_drawdown_latches_on_at_minus_20_and_clears_only_above_minus_15():
    c = [100.0] * 440
    c += list(np.linspace(100, 79, 10))                 # -21% from the 100 high
    c += list(np.linspace(79, 83, 5))                   # -17%: better, but still latched on
    r1 = dt.analyze(days(len(c)), c)["drawdown"]
    assert r1["on"] is True and r1["entries_1y"] == 1 and r1["since"] is not None
    c2 = c + [86.0] * 5                                 # -14%: clears
    assert dt.analyze(days(len(c2)), c2)["drawdown"]["on"] is False
    c3 = c2 + list(np.linspace(86, 78, 8))              # falls again: a second entry
    assert dt.analyze(days(len(c3)), c3)["drawdown"]["entries_1y"] == 2


def test_deep_drawdown_has_its_own_band():
    c = [100.0] * 440 + list(np.linspace(100, 68, 12)) + [74.0] * 3     # -32%, then -26%: still deep (clears above -25%)
    r = dt.analyze(days(len(c)), c)
    assert r["deep_drawdown"]["on"] is True and r["drawdown"]["on"] is True
    c2 = c + [76.0] * 3                                                  # -24%: deep clears, ordinary drawdown stays on (above -15% not reached)
    r2 = dt.analyze(days(len(c2)), c2)
    assert r2["deep_drawdown"]["on"] is False and r2["drawdown"]["on"] is True


def test_volatility_latches_when_the_last_60_days_are_much_wilder_than_the_year():
    rng = np.random.default_rng(7)
    calm = rng.normal(0.0003, 0.005, 460)
    wild = rng.normal(0.0, 0.025, 60)
    c = list(100 * np.exp(np.cumsum(np.concatenate([calm, wild]))))
    r = dt.analyze(days(len(c)), c)["volatility"]
    assert r["on"] is True and r["value"] >= 1.5
    assert dt.analyze(days(520), rising(520, noise=0.01))["volatility"]["on"] is False


def test_too_little_or_bad_history_gives_no_detection_not_a_guess():
    assert dt.analyze(days(300), rising(300))["status"] == "insufficient_data"
    c = rising(520)
    c[100] = 0.0
    assert dt.analyze(days(520), c)["status"] == "insufficient_data"


# --- wording ------------------------------------------------------------------------------------------------------------------------

def sigrow(**k):
    base = dict(liquidity_value=5e7, circuit_days_20=0, as_of_date=EXPECTED, quality="ok", detail={}, input_marker="x")
    base.update(k)
    return SimpleNamespace(**base)


def all_kinds_analysis():
    return {"status": "ok", "trend": {"state": "below", "previous": "above", "since": date(2026, 9, 25), "changed": True, "sessions_since": 3, "changes_1y": 2, "raw_crossings_1y": 9, "ratio_to_average": -0.09},
            "drawdown": {"on": True, "since": date(2026, 8, 1), "sessions_since": 40, "entries_1y": 1, "value": -0.34}, "deep_drawdown": {"on": True, "since": date(2026, 9, 1), "sessions_since": 20, "entries_1y": 1, "value": -0.34},
            "volatility": {"on": True, "since": date(2026, 9, 10), "sessions_since": 14, "entries_1y": 1, "value": 1.8}}


def test_no_text_the_user_can_see_gives_advice_or_a_forecast():
    texts = []
    for ctx in ("held", "watched", "both"):
        for inst in (None, str(uuid.uuid4())):
            for a in (all_kinds_analysis(), {**all_kinds_analysis(), "trend": {**all_kinds_analysis()["trend"], "state": "above", "previous": "below"}}):
                for o in sb.observations("SYM", ctx, a, sigrow(liquidity_value=1e6, circuit_days_20=4), inst):
                    texts += [o["title"], o["detail"]] + [x["text"] for x in o["options"]]
    assert texts and not [t for t in texts if any(b in t.lower() for b in sb.NO_ADVICE)], [t for t in texts if any(b in t.lower() for b in sb.NO_ADVICE)]


def test_every_observation_is_information_severity_and_options_start_with_keeping_things_as_they_are():
    obs = sb.observations("SYM", "held", all_kinds_analysis(), sigrow(), None)
    kinds = {o["kind"] for o in obs}
    assert {"trend_below", "deep_drawdown", "volatility_elevated"} <= kinds and "drawdown" not in kinds          # deep replaces the ordinary band
    assert all(o["severity"] == "information" and o["options"][0]["id"] == "keep" for o in obs)
    held_ids = {x["id"] for x in obs[0]["options"]}
    assert held_ids == {"keep", "new_money_elsewhere", "preview_reduction"}
    w = sb.observations("SYM", "watched", all_kinds_analysis(), sigrow(), str(uuid.uuid4()))
    assert {x["id"] for x in w[0]["options"]} == {"keep", "compare_adding"} and all("preview_reduction" not in {x["id"] for x in o["options"]} for o in w)


def test_a_change_reads_symmetrically_and_carries_the_base_rate():
    up = {**all_kinds_analysis(), "trend": {**all_kinds_analysis()["trend"], "state": "above", "previous": "below"}, "drawdown": {"on": False}, "deep_drawdown": {"on": False}, "volatility": {"on": False}}
    dn = {**up, "trend": {**up["trend"], "state": "below", "previous": "above"}}
    a, b = sb.observations("SYM", "watched", up, sigrow(), None)[0], sb.observations("SYM", "watched", dn, sigrow(), None)[0]
    assert "changed from below to above" in a["title"] and "changed from above to below" in b["title"]
    assert "crossed its 200-day average 9 time(s) in the last year" in a["detail"] and "changed side 2 time(s)" in a["detail"]
    assert "has not measured whether acting on it helps" in a["detail"]


def test_attention_is_look_only_for_a_fresh_break_or_a_deep_fall_on_a_holding():
    held = {o["kind"]: o["attention"] for o in sb.observations("S", "held", all_kinds_analysis(), sigrow(), None)}
    assert held["trend_below"] == "look" and held["deep_drawdown"] == "look" and held["volatility_elevated"] == "context"
    watched = {o["attention"] for o in sb.observations("S", "watched", all_kinds_analysis(), sigrow(), None)}
    assert watched == {"context"}                                                                                  # watching never raises the loudest level
    stale_break = {**all_kinds_analysis(), "trend": {**all_kinds_analysis()["trend"], "sessions_since": 80}}
    assert {o["kind"]: o["attention"] for o in sb.observations("S", "held", stale_break, sigrow(), None)}["trend_below"] == "context"


def test_thin_trading_and_circuit_locks_are_noted():
    thin = [o for o in sb.observations("S", "held", {"status": "ok", "trend": {"state": None, "changed": False, "sessions_since": None, "since": None, "changes_1y": 0, "raw_crossings_1y": 0, "ratio_to_average": 0},
                                                      "drawdown": {"on": False}, "deep_drawdown": {"on": False}, "volatility": {"on": False}}, sigrow(liquidity_value=1e5), None)]
    assert [o["kind"] for o in thin] == ["thin_liquidity"]


# --- DB: building -----------------------------------------------------------------------------------------------------------------------

def crash(n=520, tail=6, drop=0.85):
    c = rising(n)
    return c[:-tail] + [x * drop for x in c[-tail:]]


async def world(client, db):
    """Holdings RELIANCE and TCS, a complete profile, catalogue securities with ISINs and price history, a watched stock."""
    await complete_setup(client, db)
    rel = await make_security(db, "RELIANCE", crash(), sector="Oil Gas & Consumable Fuels")
    rel.isin = ISIN_REL
    tcs = await make_security(db, "TCS", rising(520, seed=2), sector="Information Technology")
    tcs.isin = ISIN_TCS
    watched = await make_security(db, "WATCHME", rising(520, seed=3))
    bi = BrokerInstrument(provider="angel_one", exchange="NSE", token="77", trading_symbol="WATCHME-EQ", symbol="WATCHME", name="W", series="EQ", seen_at=NOW, security_id=watched.id)
    wl = Watchlist(user_id=SINGLE_USER_ID, name="L", created_at=NOW)
    db.add_all([bi, wl])
    await db.flush()
    db.add(WatchlistItem(watchlist_id=wl.id, broker_instrument_id=bi.id, added_at=NOW))
    await db.commit()
    await sr.run_signals(db, NOW)
    return rel, tcs, watched


async def test_held_and_watched_securities_get_observations_with_the_right_context(client, db_session):
    await world(client, db_session)
    out = await sb.build_suggestions(db_session, NOW)
    held = {i["symbol"]: i for i in out["held"]}
    assert set(held) == {"RELIANCE", "TCS"} and [i["symbol"] for i in out["watched"]] == ["WATCHME"]
    rel = held["RELIANCE"]
    assert rel["context"] == "held" and rel["quality"] == "ok" and rel["position_ids"]
    brk = next(o for o in rel["observations"] if o["kind"] == "trend_below")
    assert brk["attention"] == "look" and brk["recent_change"] is True and brk["severity"] == "information"
    assert held["TCS"]["observations"] == [] or all(o["attention"] == "context" for o in held["TCS"]["observations"])
    assert out["held"][0]["symbol"] == "RELIANCE"                                                                 # the one worth a look sorts first
    assert out["policy"]["measured_flip_rates"]["stocks"] == 587 and out["policy"]["status"] == "unreviewed placeholders"


async def test_get_computes_and_writes_nothing(client, db_session):
    await world(client, db_session)
    async def counts():
        return [(await db_session.execute(select(func.count()).select_from(m))).scalar_one() for m in (InboxIssue, SuggestionLog)]
    before = await counts()
    r = await client.get("/api/v4/suggestions")
    assert r.status_code == 200 and r.json()["held"]
    assert await counts() == before
    assert (await client.get("/api/v4/suggestions/policy")).json()["trend"]["margin"] == 0.03


async def test_unreliable_stale_and_short_histories_claim_no_change(client, db_session):
    await complete_setup(client, db_session)
    dem = await make_security(db_session, "RELIANCE", crash())
    dem.isin = ISIN_REL
    ex = days(520)[-80]
    db_session.add(CorporateAction(symbol="RELIANCE", ex_date=ex, subject="Demerger", kind="demerger", needs_review=True, source="nse", fetched_at=NOW))
    short = await make_security(db_session, "TCS", rising(200, seed=2))
    short.isin = ISIN_TCS
    await db_session.commit()
    await sr.run_signals(db_session, NOW)
    out = await sb.build_suggestions(db_session, NOW)
    by = {i["symbol"]: i for i in out["held"]}
    assert by["RELIANCE"]["quality"] == "unreliable_window" and by["RELIANCE"]["observations"] == [] and "not reliable enough to say what changed" in by["RELIANCE"]["note"]
    assert "demerger" in by["RELIANCE"]["note"]                                                                    # a demerger must not read as a crash
    assert by["TCS"]["quality"] == "insufficient_data" and by["TCS"]["observations"] == []


async def test_funds_have_no_price_signals_and_are_listed_as_such(client, db_session):
    from tests.test_decisions import imp

    await complete_setup(client, db_session)
    db_session.add(Security(source_key="amfi:555", kind="mutual_fund", scheme_code="555", isin="INF000X00019", name="Some Index Fund", plan="direct", option="growth", source="amfi_navall", is_active=True, seen_at=NOW))
    await db_session.commit()
    acct = (await client.post("/api/v4/accounts", json={"label": "MF"})).json()
    await imp(client, acct, [{"asset_type": "mutual_fund", "isin": "INF000X00019", "units": "10", "value": "5000", "valuation_date": date.today().isoformat()}])
    out = await sb.build_suggestions(db_session, NOW)
    assert any("Some Index Fund" in f or f for f in out["funds_without_price_signals"]) and len(out["funds_without_price_signals"]) == 1


async def test_portfolio_items_cover_no_holdings_unknown_profile_and_drift(client, db_session):
    from tests.test_signals_p2 import make_security as _m

    empty = await sb.build_suggestions(db_session, NOW)
    assert [p["kind"] for p in empty["portfolio"]] == ["no_holdings"]
    # holdings but no tolerance answers
    from app.models.user import User
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db_session.commit()
    from tests.test_decisions import acct as mk_acct, eq, imp, seed  # noqa: F401
    a = await mk_acct(client, "Broker")
    await imp(client, a, [eq(ISIN_REL, "15000")])
    unknown = await sb.build_suggestions(db_session, NOW)
    assert [p["kind"] for p in unknown["portfolio"]] == ["needs_risk_answers"] and unknown["portfolio"][0]["href"] == "/finances"


async def test_a_filled_profile_reports_mix_drift_without_ever_suggesting_a_sale(client, db_session):
    await complete_setup(client, db_session)
    out = await sb.build_suggestions(db_session, NOW)
    kinds = {p["kind"] for p in out["portfolio"]}
    assert kinds <= {"mix_drift", "mix_within_band", "unclassified_share"} and kinds
    drift = [p for p in out["portfolio"] if p["kind"] == "mix_drift"]
    assert drift, "30,000 of stock and a 40,000 FD against a moderate target is outside the band"
    assert all("No sale is suggested" in p["detail"] and p["options"][1]["href"] == "/allocate" for p in drift)
    text = " ".join(p["title"] + p["detail"] + " ".join(o["text"] for o in p.get("options", [])) for p in out["portfolio"]).lower()
    assert not any(b in text for b in sb.NO_ADVICE)


# --- DB: persistence ----------------------------------------------------------------------------------------------------------------------------

async def signal_issues(db):
    return (await db.execute(select(InboxIssue).where(InboxIssue.kind == "signal_change").order_by(InboxIssue.fingerprint))).scalars().all()


async def test_persist_raises_information_issues_updates_them_and_logs_each_trigger_once(client, db_session):
    rel, *_ = await world(client, db_session)
    built = await sb.build_suggestions(db_session, NOW)
    first = await sp.persist_suggestions(db_session, built, NOW)
    assert first["raised"] >= 1 and first["logged"] >= 1 and first["updated"] == 0
    issues = await signal_issues(db_session)
    assert issues and all(i.severity == "information" and i.status == "open" for i in issues)
    again = await sp.persist_suggestions(db_session, built, NOW + timedelta(days=1))
    assert again["raised"] == 0 and again["updated"] >= 1 and again["logged"] == 0                                # one issue per fingerprint, one log row per trigger
    log = (await db_session.execute(select(SuggestionLog))).scalars().all()
    row = next(r for r in log if r.kind == "trend_below")
    assert (row.origin, row.context, row.method_version, row.security_id) == ("live", "held", "suggest-v1", rel.id)
    assert row.signal_input_marker and row.metrics["policy_version"] == dt.POLICY_VERSION and row.logged_at.date() >= row.trigger_date


async def test_a_cleared_condition_resolves_the_issue_and_a_dismissal_is_remembered(client, db_session):
    rel, *_ = await world(client, db_session)
    built = await sb.build_suggestions(db_session, NOW)
    await sp.persist_suggestions(db_session, built, NOW)
    fp = sp.fingerprint("trend_below", str(rel.id))
    issue = (await db_session.execute(select(InboxIssue).where(InboxIssue.fingerprint == fp))).scalar_one()
    issue.status, issue.dismissed_reason = "dismissed", "I know about it"
    await db_session.commit()
    await sp.persist_suggestions(db_session, built, NOW + timedelta(days=1))
    db_session.expire_all()
    assert (await db_session.execute(select(InboxIssue.status).where(InboxIssue.fingerprint == fp))).scalar_one() == "dismissed"     # never re-opened by the nightly pass
    # every condition clears: the open issues resolve, the owner's dismissal is kept exactly as it was
    open_before = [i.fingerprint for i in await signal_issues(db_session) if i.status == "open"]
    wiped = dict(built, held=[{**i, "observations": []} for i in built["held"]], watched=[{**i, "observations": []} for i in built["watched"]])
    cleared = await sp.persist_suggestions(db_session, wiped, NOW + timedelta(days=2))
    db_session.expire_all()
    status = {i.fingerprint: i.status for i in await signal_issues(db_session)}
    assert cleared["cleared"] == len(open_before) and status[fp] == "dismissed"
    assert all(v == "resolved" for k, v in status.items() if k in open_before)
    # the condition returns: a resolved issue reopens once (reopen_count 1); a dismissed one stays dismissed
    await sp.persist_suggestions(db_session, built, NOW + timedelta(days=3))
    db_session.expire_all()
    after = {i.fingerprint: (i.status, i.reopen_count) for i in await signal_issues(db_session)}
    assert after[fp][0] == "dismissed" and all(after[k] == ("open", 1) for k in open_before)


async def test_a_review_never_resolves_a_signal_issue(client, db_session, run_reviews):
    await world(client, db_session)
    await sp.persist_suggestions(db_session, await sb.build_suggestions(db_session, NOW), NOW)
    before = [(i.fingerprint, i.status, i.reopen_count) for i in await signal_issues(db_session)]
    assert before and all(s == "open" for _, s, _ in before)
    assert (await client.post("/api/v4/reviews")).status_code in (200, 202)
    await run_reviews()
    db_session.expire_all()
    after = [(i.fingerprint, i.status, i.reopen_count) for i in await signal_issues(db_session)]
    assert after == before                                                                                           # still open, and never reopened (no flapping)


async def test_the_signals_job_runs_the_suggestion_step_and_survives_its_failure(client, db_session, test_engine, monkeypatch):
    from app.portfolio_intelligence import jobs as jobs_mod
    from app.portfolio_intelligence.signals import jobs as sj

    await complete_setup(client, db_session)
    rel = await make_security(db_session, "RELIANCE", crash())
    rel.isin = ISIN_REL
    await db_session.commit()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    for mod in (jobs_mod, sj):
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
    assert ok.status == "done" and ok.result["suggestions"]["raised"] >= 1 and ok.result["suggestions"]["held"] == 1

    async def boom(db, now):
        raise RuntimeError("no")

    monkeypatch.setattr("app.portfolio_intelligence.suggestions.build.build_suggestions", boom)
    bad = await run_job()
    assert bad.status == "done" and bad.result["suggestions"] == {"error": "RuntimeError"}                          # reported, never failing the signals themselves


async def test_watchlist_items_expose_the_security_id_for_joining(client, db_session):
    await world(client, db_session)
    lists = (await client.get("/api/v4/watchlists")).json()["lists"]
    assert lists[0]["items"][0]["security_id"] and lists[0]["items"][0]["symbol"] == "WATCHME"


def test_a_long_standing_state_is_not_described_as_continuously_beyond_the_margin():
    old = {**all_kinds_analysis(), "trend": {**all_kinds_analysis()["trend"], "changed": False, "sessions_since": 300, "since": date(2025, 6, 2), "state": "below", "previous": None},
           "drawdown": {"on": False}, "deep_drawdown": {"on": False}, "volatility": {"on": False}}
    o = sb.observations("TCS", "watched", old, sigrow(), None)[0]
    assert "on the lower side of its 200-day average since 2025-06-02" in o["title"] and "more than 3% below its 200-day average since" not in o["title"]
    assert "stays on this side until it moves the same distance the other way" in o["detail"]
