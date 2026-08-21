"""Shared fixtures for integration tests (Phase 5). Uses an in-memory SQLite
DB instead of Postgres -- no Postgres-specific column types are used anywhere
in app/models/ (verified: no postgresql.*/JSONB/ARRAY imports), so the same
schema works unchanged. Keeps CI dependency-free (no docker/service container
needed to run these)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.config import settings
from app.core.db import Base
from app.main import app


@pytest.fixture(autouse=True)
def _force_hermetic_settings(monkeypatch):
    # Tests must never depend on this machine's real .env -- a deployment's
    # `.env` can legitimately set DEMO_MODE=false and a real QWEN_API_KEY
    # (this repo's does), which would make "unmocked" providers in tests fire
    # real Yahoo Finance / LLM network calls instead of the safe demo/no-op
    # fallback paths the tests are actually designed to exercise.
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "qwen_api_key", "")


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    # `get_db` is the same function object everywhere it's imported (Python
    # module caching), so overriding it here covers every router's
    # `Depends(get_db)` regardless of which module imported it.
    app.dependency_overrides[db_module.get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
