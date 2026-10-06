"""Migration startup barrier (V3 Phase 11, instruction 2).

Both the API (`app/main.py`) and the worker (`app/worker.py`) must refuse to
start against a database whose applied Alembic revision doesn't match the
revision the running code was built for. Before this module existed, neither
process checked this at all -- a stale schema (migration not yet applied) or
an ahead schema (code rolled back below a migration someone already ran)
would silently start serving/processing against the wrong shape, failing
later with a confusing column/table error deep in a request or pipeline run
instead of a clear one at boot.

Resolves the expected head from the migration scripts on disk (never assumes
"whatever this checkout happens to be on" beyond that), and the actual
applied revision from the database's `alembic_version` table via Alembic's
own `MigrationContext` (not a hand-rolled query) -- both fixed to the
backend package's own `alembic.ini`/`alembic/` directory (not CWD-relative)
so this works the same whether the process was started from `backend/`,
the repo root, or a container WORKDIR.
"""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncConnection

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = _BACKEND_ROOT / "alembic"


class MigrationMismatchError(RuntimeError):
    """Raised when the database's applied Alembic revision doesn't match the
    revision the running code expects. Startup must abort, never continue."""


def expected_head() -> str:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise MigrationMismatchError(
            f"No migration head found under {_ALEMBIC_SCRIPT_LOCATION} -- "
            "script directory is empty or misconfigured."
        )
    return head


def _sync_check(connection) -> None:
    expected = expected_head()
    context = MigrationContext.configure(connection)
    current = context.get_current_revision()
    if current != expected:
        raise MigrationMismatchError(
            f"Database schema is at Alembic revision {current!r} but this "
            f"code expects {expected!r}. Run `alembic upgrade head` (from "
            "`backend/`) before starting the API or worker -- refusing to "
            "serve/process against a stale or ahead schema."
        )


async def assert_migration_head(conn: AsyncConnection) -> None:
    """Raises `MigrationMismatchError` if `conn`'s database is not exactly at
    `expected_head()`. Call once at process startup, before serving requests
    or claiming jobs."""
    await conn.run_sync(_sync_check)
