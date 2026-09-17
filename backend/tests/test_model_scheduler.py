"""Phase 04 scheduler worker: reservation dedup, atomic commit/release,
unknown-billing flagging, expiry, and soft daily spend-cap enforcement
(V3 build plan section 12.2)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.scheduler import ModelCallReservation, ModelProject
from app.services.model_scheduler import (
    ReservationStateError,
    commit,
    eligible_projects,
    expire_stale_reservations,
    find_existing_reservation,
    mark_unknown_billing,
    release,
    reserve,
)
from app.utils.time import utcnow


async def _make_project(db_session, **overrides):
    defaults = dict(
        alias="team-member-1-dev",
        cloud_project_id="gcp-project-1",
        owner="alice",
        environment="dev",
        supported_model_ids=["gemini-3.5-flash-lite"],
        daily_spend_cap_usd=10.0,
        credential_ref="GEMINI_PROJECT_1_KEY",
        is_healthy=True,
    )
    defaults.update(overrides)
    project = ModelProject(**defaults)
    db_session.add(project)
    await db_session.flush()
    return project


async def test_reserve_succeeds(db_session):
    project = await _make_project(db_session)
    reservation = await reserve(
        db_session,
        artifact_key="report:RELIANCE:2026-09-14",
        project_id=project.id,
        task_attempt_id="attempt-1",
        estimated_input_tokens=1000,
        estimated_output_tokens=200,
        estimated_cost_usd=0.05,
        ttl_seconds=300,
    )
    assert reservation is not None
    assert reservation.status == "reserved"
    assert reservation.artifact_key == "report:RELIANCE:2026-09-14"


async def test_duplicate_task_attempt_id_returns_none(db_session):
    project = await _make_project(db_session)
    first = await reserve(
        db_session,
        artifact_key="report:A",
        project_id=project.id,
        task_attempt_id="dup-attempt",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    assert first is not None

    second = await reserve(
        db_session,
        artifact_key="report:B",  # different artifact, same task_attempt_id
        project_id=project.id,
        task_attempt_id="dup-attempt",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    assert second is None

    # exactly one row exists for that task_attempt_id
    result = await db_session.execute(
        select(func.count()).select_from(ModelCallReservation).where(
            ModelCallReservation.task_attempt_id == "dup-attempt"
        )
    )
    assert result.scalar_one() == 1


async def test_find_existing_reservation(db_session):
    project = await _make_project(db_session)
    assert await find_existing_reservation(db_session, "report:X") is None

    created = await reserve(
        db_session,
        artifact_key="report:X",
        project_id=project.id,
        task_attempt_id="attempt-x",
        estimated_input_tokens=10,
        estimated_output_tokens=5,
        estimated_cost_usd=0.001,
        ttl_seconds=60,
    )
    found = await find_existing_reservation(db_session, "report:X")
    assert found is not None
    assert found.id == created.id


async def test_commit_transitions_status(db_session):
    project = await _make_project(db_session)
    reservation = await reserve(
        db_session,
        artifact_key="report:C",
        project_id=project.id,
        task_attempt_id="attempt-commit",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    await commit(db_session, reservation.id, actual_input_tokens=110, actual_output_tokens=22, actual_cost_usd=0.012)
    await db_session.refresh(reservation)
    assert reservation.status == "committed"
    assert reservation.actual_cost_usd == 0.012
    assert reservation.reconciled_at is not None


async def test_commit_twice_raises(db_session):
    project = await _make_project(db_session)
    reservation = await reserve(
        db_session,
        artifact_key="report:D",
        project_id=project.id,
        task_attempt_id="attempt-commit-twice",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    await commit(db_session, reservation.id, actual_input_tokens=1, actual_output_tokens=1, actual_cost_usd=0.001)
    with pytest.raises(ReservationStateError):
        await commit(db_session, reservation.id, actual_input_tokens=1, actual_output_tokens=1, actual_cost_usd=0.001)


async def test_release_on_committed_raises(db_session):
    project = await _make_project(db_session)
    reservation = await reserve(
        db_session,
        artifact_key="report:E",
        project_id=project.id,
        task_attempt_id="attempt-release-committed",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    await commit(db_session, reservation.id, actual_input_tokens=1, actual_output_tokens=1, actual_cost_usd=0.001)
    with pytest.raises(ReservationStateError):
        await release(db_session, reservation.id)


async def test_release_frees_reservation(db_session):
    project = await _make_project(db_session)
    reservation = await reserve(
        db_session,
        artifact_key="report:F",
        project_id=project.id,
        task_attempt_id="attempt-release",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    await release(db_session, reservation.id)
    await db_session.refresh(reservation)
    assert reservation.status == "released"
    assert reservation.reconciled_at is not None


async def test_mark_unknown_billing_distinct_and_summable(db_session):
    project = await _make_project(db_session)
    unknown = await reserve(
        db_session,
        artifact_key="report:G",
        project_id=project.id,
        task_attempt_id="attempt-unknown",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.02,
        ttl_seconds=300,
    )
    released = await reserve(
        db_session,
        artifact_key="report:H",
        project_id=project.id,
        task_attempt_id="attempt-released-2",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.03,
        ttl_seconds=300,
    )
    await mark_unknown_billing(db_session, unknown.id)
    await release(db_session, released.id)

    await db_session.refresh(unknown)
    await db_session.refresh(released)
    assert unknown.status == "unknown_billing"
    assert unknown.status != "committed"
    assert unknown.status != "released"

    # a cost report can find/sum "possibly billed" rows separately from
    # released (definitely-unused, zero-cost) ones
    result = await db_session.execute(
        select(func.coalesce(func.sum(ModelCallReservation.estimated_cost_usd), 0.0)).where(
            ModelCallReservation.status == "unknown_billing"
        )
    )
    assert result.scalar_one() == pytest.approx(0.02)

    result = await db_session.execute(
        select(func.coalesce(func.sum(ModelCallReservation.estimated_cost_usd), 0.0)).where(
            ModelCallReservation.status == "released"
        )
    )
    assert result.scalar_one() == pytest.approx(0.03)


async def test_expire_stale_reservations(db_session):
    project = await _make_project(db_session)
    now = utcnow()

    stale = await reserve(
        db_session,
        artifact_key="report:I",
        project_id=project.id,
        task_attempt_id="attempt-stale",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    fresh = await reserve(
        db_session,
        artifact_key="report:J",
        project_id=project.id,
        task_attempt_id="attempt-fresh",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.01,
        ttl_seconds=300,
    )
    # force `stale` into the past directly
    stale.expires_at = now - timedelta(seconds=10)
    await db_session.flush()

    count = await expire_stale_reservations(db_session, now=now)
    assert count == 1

    await db_session.refresh(stale)
    await db_session.refresh(fresh)
    assert stale.status == "expired"
    assert fresh.status == "reserved"

    # idempotent: running again affects nothing and does not error
    count_again = await expire_stale_reservations(db_session, now=now)
    assert count_again == 0


async def test_daily_spend_cap_rejects_without_creating_row(db_session):
    project = await _make_project(db_session, daily_spend_cap_usd=0.05)
    first = await reserve(
        db_session,
        artifact_key="report:K1",
        project_id=project.id,
        task_attempt_id="attempt-cap-1",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.04,
        ttl_seconds=300,
    )
    assert first is not None

    before_count = (
        await db_session.execute(select(func.count()).select_from(ModelCallReservation))
    ).scalar_one()

    second = await reserve(
        db_session,
        artifact_key="report:K2",
        project_id=project.id,
        task_attempt_id="attempt-cap-2",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.02,  # 0.04 + 0.02 > 0.05 cap
        ttl_seconds=300,
    )
    assert second is None

    after_count = (
        await db_session.execute(select(func.count()).select_from(ModelCallReservation))
    ).scalar_one()
    assert after_count == before_count


async def test_eligible_projects_excludes_unhealthy_and_unsupported(db_session):
    healthy_supported = await _make_project(
        db_session, alias="p1", supported_model_ids=["gemini-3.5-flash-lite"], is_healthy=True
    )
    unhealthy = await _make_project(
        db_session, alias="p2", supported_model_ids=["gemini-3.5-flash-lite"], is_healthy=False
    )
    wrong_model = await _make_project(
        db_session, alias="p3", supported_model_ids=["gemini-3.8-flash"], is_healthy=True
    )

    result = await eligible_projects(db_session, "gemini-3.5-flash-lite")
    ids = {p.id for p in result}
    assert healthy_supported.id in ids
    assert unhealthy.id not in ids
    assert wrong_model.id not in ids


async def test_reserve_preserves_prior_unflushed_work_in_session(db_session):
    """The IntegrityError->None translation in reserve() uses a SAVEPOINT
    (db.begin_nested()) specifically so a failed/duplicate reservation
    attempt cannot roll back other work the caller already flushed earlier
    in the same session. Prove a prior flushed row survives a successful
    reserve() call that happens afterward in the same session."""
    prior_project = await _make_project(db_session, alias="prior-project")
    project = await _make_project(db_session, alias="reserve-project")

    reservation = await reserve(
        db_session,
        artifact_key="report:SAVEPOINT",
        project_id=project.id,
        task_attempt_id="attempt-savepoint",
        estimated_input_tokens=10,
        estimated_output_tokens=5,
        estimated_cost_usd=0.001,
        ttl_seconds=60,
    )
    assert reservation is not None

    # prior work is still visible/committed within this session afterward
    result = await db_session.execute(
        select(ModelProject).where(ModelProject.id == prior_project.id)
    )
    assert result.scalar_one_or_none() is not None
    result = await db_session.execute(
        select(func.count()).select_from(ModelCallReservation)
    )
    assert result.scalar_one() == 1


async def test_daily_spend_cap_counts_unknown_billing_as_possibly_billed(db_session):
    """V3 section 12.3: never treat a possibly-billed request as free.
    unknown_billing rows must count against the cap the same as committed
    ones -- otherwise a timed-out call that may have actually billed the
    project would silently free up budget it hasn't actually freed."""
    project = await _make_project(db_session, daily_spend_cap_usd=0.05)
    first = await reserve(
        db_session,
        artifact_key="report:U1",
        project_id=project.id,
        task_attempt_id="attempt-unknownbilling-1",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.04,
        ttl_seconds=300,
    )
    assert first is not None
    await mark_unknown_billing(db_session, first.id)

    # 0.04 (unknown_billing) + 0.02 would exceed the 0.05 cap
    second = await reserve(
        db_session,
        artifact_key="report:U2",
        project_id=project.id,
        task_attempt_id="attempt-unknownbilling-2",
        estimated_input_tokens=100,
        estimated_output_tokens=20,
        estimated_cost_usd=0.02,
        ttl_seconds=300,
    )
    assert second is None


async def test_eligible_projects_empty_when_all_unavailable(db_session):
    await _make_project(db_session, alias="p1", supported_model_ids=["gemini-3.5-flash-lite"], is_healthy=False)
    await _make_project(db_session, alias="p2", supported_model_ids=["gemini-3.8-flash"], is_healthy=True)

    result = await eligible_projects(db_session, "gemini-3.5-flash-lite")
    assert result == []
