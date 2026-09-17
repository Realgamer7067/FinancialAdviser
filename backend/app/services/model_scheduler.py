"""Phase 04 five-project Gemini scheduler -- dispatch/accounting service
(V3 build plan section 12.2, steps 1-8).

Coordination model: a shared PostgreSQL-backed (SQLite-compatible for tests)
table IS the coordination mechanism across however many worker
processes/deployments are running -- no in-process semaphore, no Redis, no
message queue. Every write that must not race with another writer's
equivalent write is a single atomic conditional ``UPDATE ... WHERE <predicate>``
(or an ``INSERT`` whose uniqueness constraint does the conflict detection),
never a prior ``SELECT`` followed by a separate ``UPDATE``/``INSERT`` -- the
same technique ``app/pipelines/publication.py`` (Phase 01, C2) uses to close
its read-compare-unconditional-write race.

Reservation lifecycle (append-only): ``reserved`` -> exactly one of
``committed`` / ``released`` / ``expired`` / ``unknown_billing``. Nothing
transitions out of a terminal status.

KNOWN LIMITATION (explicitly not fixed here, see ``reserve()``): the daily
spend-cap check is "sum existing rows, then decide, then insert" -- that is
inherently racy under true concurrency (two concurrent reservations can both
read a cap-under-budget total and both insert, jointly exceeding the cap).
This is accepted as a *soft*, best-effort cap, not a hard atomic guarantee.
A hard guarantee needs either a DB-level aggregate constraint/trigger or
``SELECT ... FOR UPDATE`` on a running-total row -- out of scope here since
this dev environment has no live PostgreSQL to prove real row-locking
behavior against (only SQLite, which has no equivalent). The uniqueness-
constraint-based dedup in step 3 below (``task_attempt_id``) is NOT subject
to this limitation -- that one is a real atomic guarantee via the DB's
unique index, independent of any lock.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduler import ModelCallReservation, ModelProject
from app.utils.time import utcnow


class ReservationStateError(Exception):
    """Raised by commit()/release()/mark_unknown_billing() when the target
    reservation is not in the expected 'reserved' state (already reconciled,
    or does not exist) -- a deliberate hard failure rather than a silent
    no-op, so a caller can never accidentally double-commit or double-release
    a reservation without finding out."""


async def find_existing_reservation(db: AsyncSession, artifact_key: str) -> ModelCallReservation | None:
    """Dedup check (dispatch step 1): look up any reservation already made
    for this artifact key, regardless of status, so a caller can decide
    whether to reuse it instead of reserving fresh quota for the same task.

    Ordered by reserved_at DESC with id DESC as a tiebreaker -- reserved_at
    alone is not guaranteed unique (two reservations for the same
    artifact_key can land in the same clock tick), so the id tiebreaker
    makes the "most recent" pick deterministic rather than arbitrary."""
    result = await db.execute(
        select(ModelCallReservation)
        .where(ModelCallReservation.artifact_key == artifact_key)
        .order_by(ModelCallReservation.reserved_at.desc(), ModelCallReservation.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def eligible_projects(
    db: AsyncSession, model_id: str, *, exclude_unhealthy: bool = True
) -> list[ModelProject]:
    """Dispatch step 2: projects that support ``model_id`` and (by default)
    are currently healthy. ``supported_model_ids`` is a JSON list column;
    filtered in Python after an is_healthy-scoped fetch rather than with a
    dialect-specific JSON-contains operator, to stay portable across SQLite
    (tests) and Postgres per this codebase's convention (no
    postgresql.*/JSONB-specific constructs in app/models/)."""
    stmt = select(ModelProject)
    if exclude_unhealthy:
        stmt = stmt.where(ModelProject.is_healthy.is_(True))
    result = await db.execute(stmt)
    projects = result.scalars().all()
    return [p for p in projects if model_id in (p.supported_model_ids or [])]


async def _committed_and_reserved_cost_today(db: AsyncSession, project_id: UUID, now: datetime) -> float:
    """Sum of today's committed cost, still-live (non-expired) reserved cost,
    and unknown_billing cost for a project -- the input to the soft spend-cap
    check in reserve(). "Today" = reserved_at >= start of the current UTC
    day.

    unknown_billing rows are included at their estimated_cost_usd (the best
    figure available, since actual_cost_usd is unknown by definition for
    that status) -- per V3 section 12.3, "never automatically refund a
    possibly billed request to zero." Excluding them here would let a
    timed-out-but-possibly-billed call count as free against the cap, which
    is exactly what that rule forbids.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(ModelCallReservation.estimated_cost_usd), 0.0)).where(
            ModelCallReservation.project_id == project_id,
            ModelCallReservation.reserved_at >= day_start,
            (
                (ModelCallReservation.status.in_(["committed", "unknown_billing"]))
                | (
                    (ModelCallReservation.status == "reserved")
                    & (ModelCallReservation.expires_at > now)
                )
            ),
        )
    )
    return float(result.scalar_one())


async def reserve(
    db: AsyncSession,
    artifact_key: str,
    project_id: UUID,
    task_attempt_id: str,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    estimated_cost_usd: float,
    ttl_seconds: int,
) -> ModelCallReservation | None:
    """Dispatch step 4: atomically reserve quota for one task attempt.

    Dedup: relies entirely on the unique constraint on ``task_attempt_id`` --
    this function does NOT run a SELECT to pre-check for an existing
    reservation with the same task_attempt_id (that would reopen exactly the
    read-compare-write race this module exists to close). It attempts the
    INSERT and translates the resulting IntegrityError into a plain ``None``
    return.

    Soft spend cap: see the module docstring's KNOWN LIMITATION -- this is a
    check-then-insert (racy under true concurrency), not an atomic guarantee.
    Returns None (no row created) if the reservation would push today's
    committed+live-reserved cost for this project over its
    ``daily_spend_cap_usd``.
    """
    now = utcnow()
    project = await db.get(ModelProject, project_id)
    if project is None:
        return None

    current_cost = await _committed_and_reserved_cost_today(db, project_id, now)
    if current_cost + estimated_cost_usd > project.daily_spend_cap_usd:
        return None

    reservation = ModelCallReservation(
        artifact_key=artifact_key,
        project_id=project_id,
        task_attempt_id=task_attempt_id,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        status="reserved",
        reserved_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    try:
        async with db.begin_nested():
            db.add(reservation)
            await db.flush()
    except IntegrityError:
        # begin_nested() uses a SAVEPOINT, so this rollback undoes only the
        # failed insert -- it must NOT roll back the whole session (that
        # would also discard any earlier, already-flushed work from this
        # same caller/transaction).
        return None
    return reservation


async def commit(
    db: AsyncSession,
    reservation_id: UUID,
    actual_input_tokens: int,
    actual_output_tokens: int,
    actual_cost_usd: float,
) -> None:
    """Dispatch step 7 (successful reconciliation): atomic conditional UPDATE
    -- only transitions a reservation currently in status='reserved'.
    Raises ReservationStateError (does not silently no-op) if the reservation
    is already committed/released/expired/unknown_billing or does not exist,
    so a caller can never accidentally double-commit.

    Uses execution_options(synchronize_session=False): this does NOT update
    the in-session ORM identity map. If the caller already holds the
    ModelCallReservation instance (e.g. the object reserve() returned), that
    instance's .status/.actual_* attributes stay stale ("reserved") after
    this call returns -- re-query or await db.refresh(instance) before
    reading them."""
    now = utcnow()
    result = await db.execute(
        update(ModelCallReservation)
        .where(ModelCallReservation.id == reservation_id, ModelCallReservation.status == "reserved")
        .values(
            status="committed",
            actual_input_tokens=actual_input_tokens,
            actual_output_tokens=actual_output_tokens,
            actual_cost_usd=actual_cost_usd,
            reconciled_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ReservationStateError(
            f"reservation {reservation_id}: not in 'reserved' state (or does not exist) -- refusing to commit"
        )


async def release(db: AsyncSession, reservation_id: UUID) -> None:
    """Dispatch step 8 (unused reservation): atomic conditional UPDATE,
    status='reserved' -> 'released'. Raises ReservationStateError if the
    reservation is not currently 'reserved', for the same double-transition
    reason as commit(). Same synchronize_session=False caveat as commit() --
    a held ModelCallReservation instance is not auto-refreshed."""
    now = utcnow()
    result = await db.execute(
        update(ModelCallReservation)
        .where(ModelCallReservation.id == reservation_id, ModelCallReservation.status == "reserved")
        .values(status="released", reconciled_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ReservationStateError(
            f"reservation {reservation_id}: not in 'reserved' state (or does not exist) -- refusing to release"
        )


async def mark_unknown_billing(db: AsyncSession, reservation_id: UUID) -> None:
    """Dispatch step 7 (V3 section 12.3: "a timed-out request may have
    executed... never automatically refund a possibly billed request to
    zero"). Atomic conditional UPDATE, status='reserved' -> 'unknown_billing'
    -- a status visibly distinct from both 'committed' and 'released' so a
    cost report can flag it as possibly-billed-but-unconfirmed rather than
    silently treating it as free. Raises ReservationStateError if the
    reservation is not currently 'reserved'. Same synchronize_session=False
    caveat as commit() -- a held ModelCallReservation instance is not
    auto-refreshed."""
    now = utcnow()
    result = await db.execute(
        update(ModelCallReservation)
        .where(ModelCallReservation.id == reservation_id, ModelCallReservation.status == "reserved")
        .values(status="unknown_billing", reconciled_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise ReservationStateError(
            f"reservation {reservation_id}: not in 'reserved' state (or does not exist) -- refusing to mark unknown_billing"
        )


async def expire_stale_reservations(db: AsyncSession, now: datetime | None = None) -> int:
    """Atomic conditional UPDATE of every status='reserved' row past its
    expires_at to status='expired'. This is what makes a stalled/forgotten
    reservation's held quota available again without relying on every caller
    to remember to call release(). Idempotent: a second run affects zero
    rows for anything already expired (status is no longer 'reserved')."""
    now = now or utcnow()
    result = await db.execute(
        update(ModelCallReservation)
        .where(ModelCallReservation.status == "reserved", ModelCallReservation.expires_at < now)
        .values(status="expired", reconciled_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
