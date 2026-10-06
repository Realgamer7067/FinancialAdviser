"""Postgres-only: deleting a watchlist with items and alerts (FK order is enforced here, not on SQLite).
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.main import app
from app.models.user import User
from app.models.watchlist import BrokerInstrument, WatchAlert, Watchlist, WatchlistItem
from app.portfolio_intelligence.market import master as master_mod
from tests.test_watchlist import MASTER

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)


async def test_deleting_a_populated_watchlist_and_item_on_postgres():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
        await s.commit()
        await master_mod.upsert_master(s, master_mod.parse_master(MASTER))

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_module.get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            async with factory() as s:
                ids = [b.id for b in (await s.execute(select(BrokerInstrument).limit(2))).scalars()]
            wl = (await c.post("/api/v4/watchlists", json={"name": "L"})).json()
            items = [(await c.post(f"/api/v4/watchlists/{wl['id']}/items", json={"broker_instrument_id": str(i)})).json() for i in ids]
            for it in items:
                assert (await c.post(f"/api/v4/watchlists/items/{it['item_id']}/alerts", json={"kind": "price_above", "threshold": "100"})).status_code == 201
            assert (await c.delete(f"/api/v4/watchlists/items/{items[0]['item_id']}")).status_code == 204  # single item with an alert
            assert (await c.delete(f"/api/v4/watchlists/{wl['id']}")).status_code == 204                  # list with item + alert
        async with factory() as s:
            for model in (Watchlist, WatchlistItem, WatchAlert):
                assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
