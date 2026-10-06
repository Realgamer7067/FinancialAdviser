"""Postgres-only: concurrent claims of one queued job (SKIP LOCKED + lease).
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount
from app.models.portfolio_jobs import PortfolioJob
from app.models.user import User
from app.portfolio_intelligence.jobs import claim_next_portfolio_job
from app.utils.time import utcnow

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)


async def test_only_one_of_many_concurrent_claims_wins():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.flush()  # FK order is not inferred from the ORM here
            a = SourceAccount(user_id=SINGLE_USER_ID, source_type="angel_one", label="A", included=True,
                              status="active", version=1, created_at=utcnow())
            s.add(a)
            await s.flush()
            s.add(PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=a.id, request_key="k",
                               status="queued", attempts=0, created_at=utcnow()))
            await s.commit()

        async def claim():
            async with factory() as s:
                return await claim_next_portfolio_job(s)

        results = await asyncio.gather(*[claim() for _ in range(8)])
        winners = [r for r in results if r is not None]
        assert len(winners) == 1 and winners[0].attempts == 1
    finally:
        await engine.dispose()


async def test_reclaimed_attempt_cannot_publish_on_postgres():
    from app.models.accounts import SourceImport
    from app.portfolio_intelligence.sources.angel.holdings import ParsedHoldings
    from app.portfolio_intelligence.sources.angel.sync import publish_sync_result
    from app.pipelines.publication import StalePublicationError
    from sqlalchemy import func, select

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.flush()
            a = SourceAccount(user_id=SINGLE_USER_ID, source_type="angel_one", label="A", included=True,
                              status="active", version=1, created_at=utcnow())
            s.add(a)
            await s.flush()
            j = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=a.id, request_key="k",
                             status="running", attempts=1, worker_token="t1", created_at=utcnow())
            s.add(j)
            await s.commit()
            job_id, acct_id = j.id, a.id
        async with factory() as old, factory() as new:
            await old.get(PortfolioJob, job_id)  # old attempt's in-memory view: t1
            row = await new.get(PortfolioJob, job_id)
            row.worker_token = "t2"  # lease expired; another attempt reclaimed it
            await new.commit()
            with pytest.raises(StalePublicationError):
                await publish_sync_result(old, job_id, "t1", acct_id, ParsedHoldings(), {})
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(SourceImport))).scalar_one() == 0
    finally:
        await engine.dispose()


async def test_concurrent_twin_refresh_creates_one_state_and_one_valuation():
    from datetime import date
    from sqlalchemy import func, select
    from app.models.accounts import PositionObservation, SourceImport
    from app.models.twin import PortfolioState, ValuationSnapshot
    from app.portfolio_intelligence.state.build import refresh_state

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.flush()
            a = SourceAccount(user_id=SINGLE_USER_ID, source_type="manual", label="A", included=True,
                              status="active", version=1, created_at=utcnow())
            s.add(a)
            await s.flush()
            i = SourceImport(account_id=a.id, idempotency_key="k", content_hash="h", schema_version="v",
                             status="complete", row_count=1, created_at=utcnow())
            s.add(i)
            await s.flush()
            from decimal import Decimal
            s.add(PositionObservation(import_id=i.id, row_ordinal=1, asset_type="deposit", raw_identifier="FD",
                                      resolution="not_applicable", value=Decimal("1000"), valuation_date=date.today()))
            await s.commit()

        async def go():
            async with factory() as s:
                return await refresh_state(s, SINGLE_USER_ID)

        results = await asyncio.gather(*[go() for _ in range(6)])
        assert len({r.state.id for r in results}) == 1
        assert len({r.valuation.id for r in results}) == 1
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(PortfolioState))).scalar_one() == 1
            assert (await s.execute(select(func.count()).select_from(ValuationSnapshot))).scalar_one() == 1
    finally:
        await engine.dispose()
