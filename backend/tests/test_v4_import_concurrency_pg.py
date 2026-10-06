"""Postgres-only: concurrent confirms with the same idempotency key.

SQLite cannot prove this (no real concurrent INSERT / unique enforcement at
flush time). Set PIE_TEST_PG_URL to an asyncpg URL of a THROWAWAY database
whose name starts with 'pie_test' -- the test drops and recreates all tables.
Example: postgresql+asyncpg://postgres:tmp@127.0.0.1:55432/pie_test
"""

import asyncio
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
from app.models.accounts import PositionObservation, SourceImport
from app.models.user import User

PG_URL = os.environ.get("PIE_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)


async def test_concurrent_same_key_same_payload_creates_one_import():
    engine = create_async_engine(PG_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)  # matches app.core.db.AsyncSessionLocal
    async with factory() as s:
        s.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
        await s.commit()

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[db_module.get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            acct = (await c.post("/api/v4/accounts", json={"label": "A"})).json()
            body = {
                "account_id": acct["id"],
                "idempotency_key": "race-1",
                "rows": [
                    {"asset_type": "gold", "description": f"coin {i}", "value": "100", "valuation_date": "2026-09-01"}
                    for i in range(50)
                ],
            }
            results = await asyncio.gather(*[c.post("/api/v4/imports/manual/confirm", json=body) for _ in range(6)])
        assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
        assert len({r.json()["id"] for r in results}) == 1
        assert sorted(r.json()["replayed"] for r in results).count(False) == 1
        async with factory() as s:
            assert (await s.execute(select(func.count()).select_from(SourceImport))).scalar_one() == 1
            assert (await s.execute(select(func.count()).select_from(PositionObservation))).scalar_one() == 50
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
