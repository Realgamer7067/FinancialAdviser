"""Postgres-only: the daily scheduler marker is race-safe across processes.
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import asyncio
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.models.living import SchedulerRun
from app.models.portfolio_jobs import PortfolioJob
from app.models.user import User
from app.portfolio_intelligence import scheduler
from app.utils.time import utcnow

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)
WED_CLOSE = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


async def test_concurrent_ticks_run_the_close_exactly_once(monkeypatch):
    monkeypatch.setattr(scheduler, "load_session", lambda now=None: object())
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.flush()
            s.add(SourceAccount(user_id=SINGLE_USER_ID, source_type="angel_one", label="Angel", included=True, status="active",
                                version=1, created_at=utcnow()))
            await s.commit()

        async def go():
            async with factory() as s:
                return await scheduler.tick(s, WED_CLOSE)

        results = await asyncio.gather(*[go() for _ in range(6)])
        assert sum(1 for r in results if r["ran"]) == 1, results
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(SchedulerRun))).scalar_one() == 1
            syncs = (await s.execute(select(func.count()).select_from(PortfolioJob).where(PortfolioJob.kind == "account_sync"))).scalar_one()
            assert syncs == 1  # the losers' queued syncs were rolled back with their transactions
    finally:
        await engine.dispose()
