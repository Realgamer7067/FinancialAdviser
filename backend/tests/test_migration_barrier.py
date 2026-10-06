"""V3 Phase 11 instruction 2: the migration startup barrier
(app/core/migration_barrier.py) shared by app/main.py and app/worker.py must
fail clearly when the database's applied Alembic revision doesn't match the
code's expected head, and pass silently when it does.

Uses a scratch SQLite engine, not Postgres -- this environment has no
docker/postgres binaries at all (confirmed: `which docker pg_ctl postgres
initdb` all empty), and the barrier's own logic (compare applied revision to
`ScriptDirectory.get_current_head()`) is dialect-independent -- Alembic's
`MigrationContext` reads/writes the plain `alembic_version` table the same
way on any SQLAlchemy-supported backend.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.migration_barrier import MigrationMismatchError, assert_migration_head, expected_head


@pytest_asyncio.fixture
async def scratch_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    yield engine
    await engine.dispose()


async def _stamp(engine, revision: str | None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        if revision is not None:
            await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": revision})


@pytest.mark.asyncio
async def test_expected_head_resolves_to_a_real_revision():
    # Sanity check on the resolver itself, independent of any DB: it must
    # find the actual head under backend/alembic/versions, not raise, and
    # not silently return None.
    head = expected_head()
    assert head and isinstance(head, str)


@pytest.mark.asyncio
async def test_matching_revision_passes(scratch_engine):
    await _stamp(scratch_engine, expected_head())
    async with scratch_engine.connect() as conn:
        await assert_migration_head(conn)  # must not raise


@pytest.mark.asyncio
async def test_mismatched_revision_raises_clearly(scratch_engine):
    await _stamp(scratch_engine, "0000_stale_bogus_revision")
    async with scratch_engine.connect() as conn:
        with pytest.raises(MigrationMismatchError) as exc_info:
            await assert_migration_head(conn)
    message = str(exc_info.value)
    assert "0000_stale_bogus_revision" in message
    assert expected_head() in message


@pytest.mark.asyncio
async def test_fresh_unmigrated_database_raises(scratch_engine):
    # No alembic_version table at all (e.g. a brand-new empty DB nobody has
    # run `alembic upgrade head` against yet) must fail loudly too, not be
    # mistaken for "up to date."
    async with scratch_engine.connect() as conn:
        with pytest.raises(MigrationMismatchError):
            await assert_migration_head(conn)
