"""Postgres-only: review publication interleavings (Phase 07 gate A12/A20).
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import asyncio
import os
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.config import settings
from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.main import app
from app.models.decisions import CurrentDecision, DecisionOutcome
from app.models.portfolio_jobs import PortfolioJob
from app.models.user import User
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence.decisions import runner
from app.utils.time import utcnow

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)
TODAY = date.today().isoformat()


async def _env():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
        await s.commit()

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_module.get_db] = override
    return engine, factory


async def _job(factory, token):
    async with factory() as s:
        j = PortfolioJob(user_id=SINGLE_USER_ID, kind="review", account_id=None, request_key=f"r-{uuid.uuid4()}", status="running",
                         attempts=1, worker_token=token, created_at=utcnow(), started_at=utcnow())
        s.add(j)
        await s.commit()
        return j.id


async def _import(c, acct, rows):
    r = await c.post("/api/v4/imports/manual/confirm", json={"account_id": acct["id"], "idempotency_key": str(uuid.uuid4()),
                                                             "rows": rows, "acknowledge_conflicts": True})
    assert r.status_code == 200, r.text


def _dep(v, name="FD"):
    return {"asset_type": "deposit", "description": name, "value": v, "valuation_date": TODAY}


async def test_lease_reclaim_plus_state_change_leaves_one_compatible_current(monkeypatch):
    monkeypatch.setattr(settings, "inline_reviews", False)
    engine, factory = await _env()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            a = (await c.post("/api/v4/accounts", json={"label": "A"})).json()
            await _import(c, a, [_dep("1000")])
            job = await _job(factory, "t1")
            async with factory() as s1:
                stale_attempt = await runner.compute_review(s1, SINGLE_USER_ID)  # attempt 1 computes on state v1

            # lease expires; a second attempt owns the job, and meanwhile the holdings change
            async with factory() as s:
                j = await s.get(PortfolioJob, job)
                j.worker_token = "t2"
                await s.commit()
            await _import(c, a, [_dep("1000"), _dep("500", "FD2")])
            async with factory() as s2:
                fresh = await runner.compute_review(s2, SINGLE_USER_ID)
                out = await runner.publish_review(s2, job, "t2", fresh)
            assert out.superseded_at is None
            # the stale attempt wakes up and tries to publish
            async with factory() as s3:
                with pytest.raises(StalePublicationError):
                    await runner.publish_review(s3, job, "t1", stale_attempt)
            async with factory() as s:
                assert (await s.execute(select(func.count()).select_from(DecisionOutcome))).scalar_one() == 1
                ptr = (await s.execute(select(CurrentDecision))).scalar_one()
                assert ptr.outcome_id == out.id and (await s.get(DecisionOutcome, ptr.outcome_id)).state_version == 2
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_concurrent_old_and_new_publications_always_end_on_the_newest_state(monkeypatch):
    monkeypatch.setattr(settings, "inline_reviews", False)
    engine, factory = await _env()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            a = (await c.post("/api/v4/accounts", json={"label": "A"})).json()
            await _import(c, a, [_dep("1000")])
            async with factory() as s:
                old = await runner.compute_review(s, SINGLE_USER_ID)
            await _import(c, a, [_dep("1000"), _dep("500", "FD2")])
            async with factory() as s:
                new = await runner.compute_review(s, SINGLE_USER_ID)
            for round_ in range(5):
                async with factory() as s:  # reset pointer/outcomes between rounds
                    for t in (CurrentDecision, DecisionOutcome):
                        for row in (await s.execute(select(t))).scalars():
                            await s.delete(row)
                    await s.commit()
                jobs = [(await _job(factory, f"o{i}"), f"o{i}", old) for i in range(3)] + [(await _job(factory, f"n{i}"), f"n{i}", new) for i in range(3)]

                async def pub(jid, tok, comp):
                    async with factory() as s:
                        return await runner.publish_review(s, jid, tok, comp)

                order = jobs if round_ % 2 else list(reversed(jobs))
                await asyncio.gather(*[pub(*j) for j in order])
                async with factory() as s:
                    ptrs = (await s.execute(select(CurrentDecision))).scalars().all()
                    assert len(ptrs) == 1
                    cur = await s.get(DecisionOutcome, ptrs[0].outcome_id)
                    assert cur.state_version == 2 and cur.superseded_at is None
                    outs = (await s.execute(select(DecisionOutcome))).scalars().all()
                    assert len(outs) == 6
                    assert {o.state_version for o in outs if o.superseded_at is None} == {2}  # old-state ones are history only
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
