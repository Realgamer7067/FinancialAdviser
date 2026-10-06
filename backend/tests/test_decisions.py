"""Phase 07: review outcomes, fenced publication, current-decision pointer."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.single_user import SINGLE_USER_ID
from app.models.decisions import CurrentDecision, DecisionOutcome
from app.models.market import Instrument
from app.models.portfolio_jobs import PortfolioJob
from app.models.user import User
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence import jobs as jobs_mod
from app.portfolio_intelligence.decisions import runner
from app.portfolio_intelligence.decisions.review import compose, detect_issues, reduction_amount
from app.utils.time import utcnow

D = Decimal
TODAY = date.today().isoformat()
ISIN_REL, ISIN_TCS = "INE002A01018", "INE467B01029"
PROFILE = {"monthly_income": "100000", "monthly_essential_expenses": "30000", "emergency_reserve_amount": "300000",
           "emergency_reserve_months_target": "6", "monthly_investable_surplus": "20000", "near_term_obligations": [],
           "tolerance_answers": {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "20_30"}}
LIMITS = {"max_single_issuer_weight": D("0.25"), "max_sector_weight": D("0.40"), "min_fresh_value_share": D("0.80")}


def dim(status="complete", missing=None):
    return {"status": status, "missing": missing or []}


READY = {k: dim() for k in ("account_coverage_status", "holdings_status", "valuation_status", "identity_status", "suitability_status")}


# --- pure ------------------------------------------------------------------------------------------

def test_reduction_amount_rounds_up_and_caps():
    # group 60000 of 100000 with a 25% limit: need 35000
    assert reduction_amount(D(60000), D(100000), D("0.25"), D(60000)) == D(35000)
    assert reduction_amount(D(60000), D(100000), D("0.25"), D(20000)) == D(20000)  # cannot sell more than the position
    assert reduction_amount(D(20000), D(100000), D("0.25"), D(20000)) is None  # nothing to fix
    assert reduction_amount(D(60001), D(100000), D("0.25"), D(60001)) == D(35100)  # rounded up to a whole 100


def risk(weight="0.1", fresh="1.0000", sectors=None):
    return {"coverage": {"fresh_value_share": fresh},
            "issuer_concentration": {"status": "ready", "largest_issuer": "RELIANCE", "largest_issuer_weight": weight},
            "sector": {"buckets": sectors or [{"bucket": "Information Technology", "weight": "0.2"}]}}


CONS_OK = {"ceilings": [{"source": "capacity", "binding": []}]}


def issues(**kw):
    a = dict(readiness=READY, risk=risk(), constraints=CONS_OK, projections=[], limits=LIMITS, claims_needing_review=0)
    a.update(kw)
    return detect_issues(**a)


def test_status_precedence_and_wording_rules():
    assert compose(issues(), READY, alternatives=[])[:2] == ("HOLD", "No action required today")
    partial_cov = {**READY, "account_coverage_status": dim("partial", ["account completeness not confirmed"])}
    s, h, e = compose(issues(readiness=partial_cov), partial_cov, alternatives=[])
    assert s == "HOLD" and h == "No issue found in the assessed holdings"  # never "no action required" with gaps
    assert "account completeness not confirmed" in e["not_assessed_or_incomplete"]
    prof = {**READY, "suitability_status": dim("partial", ["monthly_income", "goals"])}
    s, h, _ = compose(issues(readiness=prof), prof, alternatives=[])
    assert s == "NEEDS_INPUT" and "financial picture" in h.lower()
    rev = issues(risk=risk(weight="0.6"))
    s, h, _ = compose(rev, READY, alternatives=[])
    assert s == "REVIEW" and "RELIANCE" in h
    # needs_input outranks review: you cannot be reviewed on data you have not given
    both = issues(readiness=prof, risk=risk(weight="0.6"))
    assert compose(both, prof, alternatives=[])[0] == "NEEDS_INPUT"


def test_each_detector():
    kinds = lambda **kw: {i["kind"] for i in issues(**kw)}
    assert "holdings_unusable" in kinds(readiness={**READY, "holdings_status": dim("unusable", ["none"])})
    assert "stale_values" in kinds(risk=risk(fresh="0.5"))
    assert "sector_concentration" in kinds(risk=risk(sectors=[{"bucket": "Financial Services", "weight": "0.5"}]))
    assert "claims_need_review" in kinds(claims_needing_review=2)
    assert "goal_needs_revision" in kinds(projections=[{"description": "House", "goal_chain_id": "g", "assessment": "target_needs_revision"}])
    assert "reserve_shortfall" in kinds(constraints={"ceilings": [{"source": "capacity", "binding": [{"rule": "reserve_shortfall", "detail": "x"}]}]})
    assert "sync_problem" in kinds(readiness={**READY, "holdings_status": dim("partial", ["Angel: last sync had a problem"])})
    assert "unmatched_holdings" in kinds(readiness={**READY, "identity_status": dim("partial", ["1 holding(s) not matched"])})


# --- helpers for DB-backed tests -----------------------------------------------------------------------

@pytest.fixture
def run_reviews(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.AsyncSessionLocal", factory)
    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    return runner.run_queued_reviews


async def seed(db):
    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    db.add_all([Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=ISIN_REL, sector="Oil Gas & Consumable Fuels"),
                Instrument(symbol="TCS", name="TCS", exchange="NSE", isin=ISIN_TCS, sector="Information Technology")])
    await db.commit()


async def acct(client, label):
    return (await client.post("/api/v4/accounts", json={"label": label})).json()


def eq(isin, value):
    return {"asset_type": "listed_equity", "isin": isin, "units": "10", "value": value, "valuation_date": TODAY}


def dep(value, name="FD"):
    return {"asset_type": "deposit", "description": name, "value": value, "valuation_date": TODAY}


async def imp(client, a, rows):
    r = await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": str(uuid.uuid4()),
                                                                  "rows": rows, "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text


async def current(client):
    return (await client.get("/api/v4/actions/current")).json()


async def fund_goal(client):
    """A goal that is already funded by money set aside on the FD, so it raises no issue of its own."""
    g = (await client.post("/api/v4/goals", json={"description": "Car", "target_amount": "30000", "target_basis": "future_money",
                                                   "target_date": (date.today() + timedelta(days=900)).isoformat(), "priority": 1})).json()
    pos = (await client.get("/api/v4/state/current")).json()["state"]["positions"]
    fd = next(p for p in pos if p["asset_type"] == "deposit")
    r = await client.post(f"/api/v4/goals/{g['chain_id']}/allocations",
                          json={"position_id": fd["position_id"], "amount": "35000", "expected_goal_version": 1})
    assert r.status_code == 201, r.text


async def complete_setup(client, db, *, broker_rows=None):
    await seed(db)
    a, b = await acct(client, "Broker"), await acct(client, "Bank")
    await imp(client, a, broker_rows or [eq(ISIN_REL, "15000"), eq(ISIN_TCS, "15000")])
    await imp(client, b, [dep("40000"), {"asset_type": "cash", "description": "Savings", "value": "30000", "valuation_date": TODAY}])
    assert (await client.put("/api/v4/profile", json={"expected_version": 0, "facts": PROFILE})).status_code == 200
    await fund_goal(client)
    await client.put("/api/v4/account-coverage", json={"expected_version": 0, "status": "complete"})
    return a, b


# --- flows ---------------------------------------------------------------------------------------------

async def test_no_snapshot_means_no_decision_and_no_review_possible(client, db_session):
    await seed(db_session)
    assert (await current(client))["status"] == "none"
    assert (await client.post("/api/v4/reviews")).status_code == 409


async def test_new_state_queues_a_review_and_publishes_needs_input_then_hold(client, db_session, run_reviews):
    await seed(db_session)
    a = await acct(client, "Broker")
    await imp(client, a, [eq(ISIN_REL, "15000"), eq(ISIN_TCS, "15000")])
    queued = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "review"))).scalars().all()
    assert len(queued) == 1 and queued[0].status == "queued"  # one live review job, not one per change
    assert await run_reviews() == 1
    c = await current(client)
    assert c["status"] == "current" and c["outcome"]["status"] == "NEEDS_INPUT"
    assert "financial picture" in c["outcome"]["headline"].lower()
    res = c["outcome"]["result"]
    assert res["audit"]["uses_llm"] is False and res["evidence"]["risk_analysis_id"] and res["valid"]["review_by"]
    assert (await client.get(f"/api/v4/analysis/{res['evidence']['risk_analysis_id']}")).status_code == 200  # evidence opens

    await client.put("/api/v4/profile", json={"expected_version": 0, "facts": PROFILE})
    assert (await current(client))["status"] == "pending_review"  # snapshot changed: old outcome is not current
    await client.post("/api/v4/goals", json={"description": "Car", "target_amount": "100000", "target_basis": "future_money",
                                             "target_date": (date.today() + timedelta(days=900)).isoformat(), "priority": 1})
    assert await run_reviews() == 1
    c2 = await current(client)
    assert c2["status"] == "current" and c2["outcome"]["outcome_id"] != c["outcome"]["outcome_id"]
    # coverage not confirmed + equity concentrated? 15k+15k of 30k: one issuer is 50% -> REVIEW with a preview
    assert c2["outcome"]["status"] == "REVIEW"
    tl = (await client.get("/api/v4/timeline")).json()
    assert [t["is_current"] for t in tl].count(True) == 1 and tl[0]["is_current"] is True and len(tl) == 2


async def test_clean_complete_portfolio_is_hold_with_exact_wording(client, db_session, run_reviews):
    await complete_setup(client, db_session)
    await run_reviews()
    o = (await current(client))["outcome"]
    assert o["status"] == "HOLD" and o["headline"] == "No action required today"
    assert o["result"]["explanation"]["why_hold"] and o["result"]["alternatives"] == []


async def test_unconfirmed_coverage_downgrades_the_wording(client, db_session, run_reviews):
    await seed(db_session)
    a, b = await acct(client, "Broker"), await acct(client, "Bank")
    await imp(client, a, [eq(ISIN_REL, "15000"), eq(ISIN_TCS, "15000")])
    await imp(client, b, [dep("40000"), {"asset_type": "cash", "description": "Savings", "value": "30000", "valuation_date": TODAY}])
    await client.put("/api/v4/profile", json={"expected_version": 0, "facts": PROFILE})
    await fund_goal(client)
    await run_reviews()
    o = (await current(client))["outcome"]
    assert o["status"] == "HOLD" and o["headline"] == "No issue found in the assessed holdings"
    assert any("not confirmed" in m for m in o["result"]["explanation"]["not_assessed_or_incomplete"])


async def test_issuer_concentration_review_carries_a_preview_vs_hold(client, db_session, run_reviews):
    await complete_setup(client, db_session, broker_rows=[eq(ISIN_REL, "60000"), eq(ISIN_TCS, "5000")])
    await run_reviews()
    o = (await current(client))["outcome"]
    assert o["status"] == "REVIEW" and "RELIANCE" in o["headline"]
    ic = next(i for i in o["result"]["issues"] if i["kind"] == "issuer_concentration")
    assert Decimal(ic["weight"]) > Decimal("0.25")
    alt = o["result"]["alternatives"][0]
    assert alt["status"] == "review_required"  # a sale is review-only: tax unknown
    ev = (await client.get(f"/api/v4/analysis/{o['result']['evidence']['evaluation_analysis_id']}")).json()
    assert ev["default"] == "HOLD" and ev["published"] is False and ev["alternatives"][0]["accounting"]["conserved"] is True
    assert (await client.get(f"/api/v4/actions/{o['outcome_id']}")).json()["outcome_id"] == o["outcome_id"]
    assert (await client.get(f"/api/v4/actions/{uuid.uuid4()}")).status_code == 404


async def test_request_review_is_idempotent_and_reports_already_current(client, db_session, run_reviews):
    await complete_setup(client, db_session)
    await run_reviews()
    r = (await client.post("/api/v4/reviews")).json()
    assert r["already_current"] is True and r["current"]["status"] == "current"
    f1 = (await client.post("/api/v4/reviews", json={"force": True})).json()
    f2 = (await client.post("/api/v4/reviews", json={"force": True})).json()
    assert f1["already_current"] is False and f1["job_id"] == f2["job_id"]  # one live job only


# --- fenced publication -----------------------------------------------------------------------------------

async def running_review_job(db, token="t1"):
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="review", account_id=None, request_key=f"r-{uuid.uuid4()}", status="running",
                       attempts=1, worker_token=token, created_at=utcnow(), started_at=utcnow())
    db.add(job)
    await db.commit()
    return job


async def counts(db):
    n_out = (await db.execute(select(func.count()).select_from(DecisionOutcome))).scalar_one()
    ptr = (await db.execute(select(CurrentDecision))).scalar_one_or_none()
    return n_out, ptr


async def test_stale_token_cannot_publish(client, db_session, test_engine):
    await complete_setup(client, db_session)
    job = await running_review_job(db_session, "t1")
    computed = await runner.compute_review(db_session, SINGLE_USER_ID)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as other:  # a newer attempt reclaimed the job
        j = await other.get(PortfolioJob, job.id)
        j.worker_token = "t2"
        await other.commit()
    with pytest.raises(StalePublicationError):
        await runner.publish_review(db_session, job.id, "t1", computed)
    assert await counts(db_session) == (0, None)


async def test_inputs_changed_during_review_keeps_history_but_not_current(client, db_session):
    a, b = await complete_setup(client, db_session)
    job = await running_review_job(db_session, "t1")
    computed = await runner.compute_review(db_session, SINGLE_USER_ID)
    queued_before = len((await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "review", PortfolioJob.status == "queued"))).scalars().all())
    await imp(client, a, [eq(ISIN_REL, "15000"), eq(ISIN_TCS, "15000"), dep("5000", "New FD")])  # holdings change while the review ran
    out = await runner.publish_review(db_session, job.id, "t1", computed)
    assert out.superseded_at is not None and "newer portfolio snapshot" in out.superseded_reason
    n, ptr = await counts(db_session)
    assert n == 1 and ptr is None  # history kept, nothing became current
    assert (await current(client))["status"] == "none"
    successor = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "review", PortfolioJob.status == "queued"))).scalars().all()
    assert len(successor) == queued_before + 1  # a fresh review was queued by the superseded attempt


async def test_an_older_review_finishing_later_never_replaces_a_newer_current(client, db_session):
    a, b = await complete_setup(client, db_session)
    old_job = await running_review_job(db_session, "old")
    old = await runner.compute_review(db_session, SINGLE_USER_ID)
    await imp(client, a, [eq(ISIN_REL, "15000"), eq(ISIN_TCS, "15000"), dep("5000", "New FD")])
    new_job = await running_review_job(db_session, "new")
    new = await runner.compute_review(db_session, SINGLE_USER_ID)
    n_out = await runner.publish_review(db_session, new_job.id, "new", new)
    assert n_out.superseded_at is None
    _, ptr = await counts(db_session)
    assert ptr.outcome_id == n_out.id
    late = await runner.publish_review(db_session, old_job.id, "old", old)  # finished later, but computed on an older snapshot
    assert late.superseded_at is not None
    _, ptr2 = await counts(db_session)
    assert ptr2.outcome_id == n_out.id  # the pointer did not move


async def test_review_job_failure_is_recorded_not_published(client, db_session, run_reviews, monkeypatch):
    await seed(db_session)
    a = await acct(client, "Broker")
    await imp(client, a, [eq(ISIN_REL, "15000")])

    async def boom(db, user_id):
        raise RuntimeError("kaboom with secret-ish payload")
    monkeypatch.setattr(runner, "compute_review", boom)
    await run_reviews()
    job = (await db_session.execute(select(PortfolioJob).where(PortfolioJob.kind == "review"))).scalars().first()
    await db_session.refresh(job)
    assert job.status == "failed" and job.error_code == "INTERNAL" and "kaboom" not in (job.error or "")
    assert await counts(db_session) == (0, None)


def test_empty_connected_portfolio_is_a_starting_point_not_a_valuation_problem():
    from app.portfolio_intelligence.decisions.review import detect_issues

    def dim(status, missing=()):
        return {"status": status, "missing": list(missing)}
    readiness = {"account_coverage_status": dim("partial", ["account completeness not confirmed"]), "holdings_status": dim("complete"),
                 "valuation_status": dim("unusable", ["no positions"]), "identity_status": dim("complete"), "suitability_status": dim("partial", ["goals"])}
    kinds = {i["kind"] for i in detect_issues(readiness=readiness, risk=None, constraints=CONS_OK, projections=[], limits=LIMITS, claims_needing_review=0)}
    assert "portfolio_empty" in kinds and "valuation_unusable" not in kinds
    readiness["valuation_status"] = dim("unusable", ["no position has a value"])
    kinds = {i["kind"] for i in detect_issues(readiness=readiness, risk=None, constraints=CONS_OK, projections=[], limits=LIMITS, claims_needing_review=0)}
    assert "valuation_unusable" in kinds and "portfolio_empty" not in kinds
