"""Postgres-only: concurrent claims on one holding (advisory-lock serialization).
Same PIE_TEST_PG_URL rules as test_v4_import_concurrency_pg.py."""

import asyncio
import os
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.db import Base
from app.core.single_user import SINGLE_USER_ID
from app.main import app
from app.models.user import User

PG_URL = os.environ.get("PIE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL or not make_url(PG_URL).database.startswith("pie_test"),
    reason="set PIE_TEST_PG_URL to a throwaway pie_test* Postgres database",
)


async def test_concurrent_claims_never_exceed_the_holding():
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
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            a = (await c.post("/api/v4/accounts", json={"label": "A"})).json()
            await c.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "idempotency_key": "k", "rows": [
                {"asset_type": "deposit", "description": "FD", "value": "100000", "valuation_date": date.today().isoformat()}]})
            goals = []
            for i in range(6):
                g = await c.post("/api/v4/goals", json={
                    "description": f"G{i}", "target_amount": "1000", "target_basis": "future_money",
                    "target_date": (date.today() + timedelta(days=900)).isoformat(), "priority": i + 1})
                goals.append(g.json())
            pid = (await c.get("/api/v4/state/current")).json()["state"]["positions"][0]["position_id"]
            results = await asyncio.gather(*[
                c.post(f"/api/v4/goals/{g['chain_id']}/allocations", json={"position_id": pid, "amount": "40000", "expected_goal_version": 1}) for g in goals])
            codes = sorted(r.status_code for r in results)
            assert codes.count(201) == 2 and codes.count(422) == 4, codes  # 2 x 40000 fit in 100000; the rest must not
            summary = (await c.get("/api/v4/allocations/summary")).json()
            assert summary[0]["claimed"] == "80000" and summary[0]["unclaimed"] == "20000"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
