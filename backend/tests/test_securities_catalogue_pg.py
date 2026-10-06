"""Postgres-only: the catalogue sync + a >32-bit volume + the job-claim/fence path for a catalogue_refresh job.
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.models.portfolio_jobs import PortfolioJob
from app.models.securities import Security
from app.models.user import User
from app.models.watchlist import BrokerInstrument, MarketQuote
from app.portfolio_intelligence.catalogue import sync as sync_mod
from app.portfolio_intelligence.catalogue.jobs import enqueue_refresh
from app.portfolio_intelligence.jobs import claim_next_portfolio_job
from tests.test_securities_catalogue import NOW, TEXTS

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)


async def test_sync_volume_and_job_claim_on_postgres():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            s.add(BrokerInstrument(provider="angel_one", exchange="NSE", token="2885", trading_symbol="RELIANCE-EQ", symbol="RELIANCE", name="R", series="EQ", seen_at=NOW))
            await s.commit()
            await sync_mod.sync_catalogue(s, TEXTS, NOW)
            await sync_mod.sync_catalogue(s, TEXTS, NOW)  # idempotent on the unique source_key
            assert (await s.execute(select(func.count()).select_from(Security))).scalar_one() == 9 + 6 + 14
            bi = (await s.execute(select(BrokerInstrument))).scalar_one()
            assert bi.security_id is not None
            s.add(MarketQuote(broker_instrument_id=bi.id, ltp=Decimal("1"), volume=9_000_000_000, retrieved_at=NOW, mode="FULL"))
            await s.commit()  # would raise "integer out of range" on a 32-bit column
        async with factory() as s:
            first = await enqueue_refresh(s, "t", NOW)
            assert first is not None and await enqueue_refresh(s, "t2", NOW) is None
        # SKIP LOCKED claim: two sessions cannot both get the one queued job
        async with factory() as a, factory() as b:
            ja = await claim_next_portfolio_job(a, kinds=("catalogue_refresh",))
            jb = await claim_next_portfolio_job(b, kinds=("catalogue_refresh",))
            assert ja is not None and ja.worker_token and jb is None
    finally:
        await engine.dispose()


async def test_candles_rebase_and_market_job_claims_on_postgres():
    from datetime import date, timedelta

    from app.models.securities import CandleSync, SecurityCandle
    from app.portfolio_intelligence.market import candles as cm
    from app.portfolio_intelligence.market import jobs as mj
    from tests.test_market_p1 import parsed

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            s.add(BrokerInstrument(provider="angel_one", exchange="NSE", token="2885", trading_symbol="RELIANCE-EQ", symbol="RELIANCE", name="R", series="EQ", seen_at=NOW))
            await s.commit()
            await sync_mod.sync_catalogue(s, TEXTS, NOW)
            sec = (await s.execute(select(Security).where(Security.symbol == "RELIANCE"))).scalar_one()
            start = date(2026, 9, 1)
            await cm.apply_fetch(s, sec.id, parsed(start, [200, 202, 204, 206]), today=date(2026, 9, 4), now=NOW)
            await s.commit()

            async def refetch():
                return parsed(start, [100, 101, 102, 103, 104])

            r = await cm.apply_fetch(s, sec.id, parsed(start + timedelta(days=2), [102, 103, 104]), today=date(2026, 9, 5), now=NOW, refetch_full=refetch)
            await s.commit()
            assert r["rebased"] is True
            assert (await s.execute(select(func.count()).select_from(SecurityCandle))).scalar_one() == 5
            assert (await s.get(CandleSync, sec.id)).full_refetches == 1
            # the new job kinds are claimable, one worker at a time
            assert await mj.enqueue_snapshot(s, "t", NOW) is not None and await mj.enqueue_snapshot(s, "t2", NOW) is None
            assert await mj.enqueue_backfill(s, "t", security_ids=[str(sec.id)], now=NOW) is not None
            assert await mj.enqueue_backfill(s, "t", security_ids=[str(sec.id)], now=NOW) is None   # same params: blocked
    finally:
        await engine.dispose()


async def test_concurrent_identical_allocation_requests_make_one_record_on_postgres():
    import asyncio
    from decimal import Decimal

    from app.models.securities import AllocationPlan
    from app.portfolio_intelligence.allocation.service import generate_plan
    from tests.test_allocation_p3 import seed_market

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.commit()
            await seed_market(s)

        async def one():
            async with factory() as db:
                row, created = await generate_plan(db, new_money=Decimal("50000"), now=NOW)
                return row.id, created

        results = await asyncio.gather(*(one() for _ in range(4)))
        assert len({rid for rid, _ in results}) == 1 and sum(1 for _, c in results if c) == 1       # one record, one creator
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(AllocationPlan))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_concurrent_suggestion_persistence_makes_one_issue_and_one_log_row_per_trigger_on_postgres():
    import asyncio

    from app.models.living import InboxIssue
    from app.models.securities import SuggestionLog
    from app.portfolio_intelligence.suggestions import persist as sp
    from tests.test_signals_p2 import EXPECTED, make_security
    from tests.test_suggestions_p4 import crash

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.commit()
            sec = await make_security(s, "AAA", crash())
            sid = str(sec.id)
        item = {"security_id": sid, "context": "held", "signal_as_of": EXPECTED.isoformat(), "signal_input_marker": "m",
                "observations": [{"kind": "trend_below", "title": "AAA: below", "detail": "d", "measure": 0.09, "since": EXPECTED.isoformat(), "sessions_since": 3, "attention": "look"}]}
        built = {"held": [item], "watched": []}

        async def one():
            async with factory() as db:
                try:
                    return await sp.persist_suggestions(db, built, NOW)
                except Exception as exc:  # a unique-key race may surface as an error for the loser; the invariant below is what matters
                    return {"error": type(exc).__name__}

        await asyncio.gather(*(one() for _ in range(4)))
        await one()
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(InboxIssue).where(InboxIssue.kind == "signal_change"))).scalar_one() == 1
            assert (await s.execute(select(func.count()).select_from(SuggestionLog))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_ledger_scoring_versioning_and_study_store_on_postgres():
    from datetime import date, datetime, timezone

    from app.models.securities import CandleSync, LedgerOutcome, LedgerStudy, SecuritySignal
    from app.portfolio_intelligence.ledger import jobs as lj
    from app.portfolio_intelligence.ledger import score as sc
    from tests.test_ledger_live_p6 import KNOWN, px_series, stock
    from tests.test_ledger_p6 import market

    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
            await s.commit()
            last = date(2026, 11, 10)
            a = await stock(s, "AAA", px_series(100, 300, last, 0.002), last)
            await stock(s, "BBB", px_series(100, 300, last, 0.001), last)
            s.add(SecuritySignal(security_id=a.id, as_of_date=KNOWN, method_version="signals-v1", origin="live", computed_at=NOW, history_len=300, input_marker="m", quality="ok",
                                 universe="stock", sma200_ratio=0.1, mom_12_1=0.2, vol_252=0.3))
            await s.commit()
            now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
            r1 = await sc.score_pending(s, now)
            r2 = await sc.score_pending(s, now)
            assert r1["scored"] == 4 and r2["scored"] == 0 and r2["already_scored"] == 4
            sync = await s.get(CandleSync, a.id)
            sync.full_refetches = 1
            await s.commit()
            r3 = await sc.score_pending(s, now)
            assert r3["rebased_rewritten"] == 4
            assert (await s.execute(select(func.count()).select_from(LedgerOutcome))).scalar_one() == 8       # old rows untouched, new versions beside them
            close, vol = market(seed=1, kappa=0.0012)

            async def fake_panel(db):
                return close, vol, close, {"securities": 150, "sessions": 900, "first": "a", "last": "b", "data_marker": "pg1"}

            lj.panel.load_panel, orig = fake_panel, lj.panel.load_panel
            try:
                one = await lj.run_and_store_study(s, now)
                two = await lj.run_and_store_study(s, now)
            finally:
                lj.panel.load_panel = orig
            assert one["created"] is True and two["created"] is False
            assert (await s.execute(select(func.count()).select_from(LedgerStudy))).scalar_one() == 1
    finally:
        await engine.dispose()
