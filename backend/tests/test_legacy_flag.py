"""The old Nifty pipeline is off by default: neither the API nor the worker starts it."""

import asyncio

import pytest

import app.worker as worker_module
from app.core.config import settings
from app.core.single_user import SINGLE_USER_ID
from app.models.system import RecommendationJob
from app.models.user import User
from app.utils.time import utcnow


async def test_default_setting_is_off_and_api_refuses(client, db_session, monkeypatch):
    assert type(settings).model_fields["legacy_pipeline_enabled"].default is False
    monkeypatch.setattr(settings, "legacy_pipeline_enabled", False)
    r = await client.post("/api/recommendations/jobs")
    assert r.status_code == 409 and "turned off" in r.json()["detail"]
    monkeypatch.setattr(settings, "legacy_pipeline_enabled", True)
    assert (await client.post("/api/recommendations/jobs")).status_code in (202, 500)  # enabled path is covered elsewhere


async def test_worker_never_claims_legacy_jobs_when_off(db_session, test_engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "legacy_pipeline_enabled", False)
    monkeypatch.setattr(settings, "worker_poll_interval_seconds", 0)
    db_session.add(User(id=SINGLE_USER_ID, email="u@l", full_name="U", hashed_password="x"))
    # a stale 'running' job with an expired lease is exactly what used to be reclaimed and re-run
    db_session.add(RecommendationJob(user_id=SINGLE_USER_ID, status="running", created_at=utcnow(), lease_expires_at=utcnow().replace(year=2020)))
    await db_session.commit()

    calls = []

    async def spy(job_id, token):
        calls.append(job_id)
    monkeypatch.setattr(worker_module, "_process_job", spy)

    async def no_barrier(conn):
        return None
    monkeypatch.setattr(worker_module, "assert_migration_head", no_barrier)

    class _Conn:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
    from types import SimpleNamespace

    monkeypatch.setattr(worker_module, "engine", SimpleNamespace(connect=lambda: _Conn()))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(worker_module.run_worker_loop(), timeout=1.0)
    assert calls == []  # the old pipeline was never started
