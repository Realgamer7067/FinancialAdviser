"""Coverage for the V3 Phase 07 research-report identity/versioning and
warm-cache reuse primitive (app/models/research_report.py,
app/services/research_reuse.py)."""

from datetime import datetime, timezone

import pytest

from app.core.single_user import SINGLE_USER_ID
from app.models.research import ResearchSession
from app.services.research_reuse import (
    compare_two_reports,
    compute_artifact_key,
    create_follow_up,
    diff_source_ids,
    find_reusable_report,
    publish_report,
)


async def _make_session(db_session):
    session = ResearchSession(
        user_id=SINGLE_USER_ID,
        question="Should I look at TCS?",
        instrument_ids=[],
        mode="standard",
        cutoff_policy={"cutoff_date": "2026-09-01", "accept_sources_published_before": "2026-09-01"},
        state="published",
        budget_envelope={"max_searches": 10, "max_fetches": 10, "max_tokens": 10000, "deadline_seconds": 120},
        budget_consumed={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.flush()
    return session


def _base_key_kwargs(**overrides):
    kwargs = dict(
        entity="TCS",
        question_scope="standard_company_brief",
        cutoff_date="2026-09-01",
        prompt_version="research_prompts_v1",
        model_version="qwen-v1",
        research_policy_version="policy_v1",
    )
    kwargs.update(overrides)
    return kwargs


async def _publish(db_session, session, *, content=None, artifact_key=None, **kwargs):
    return await publish_report(
        db_session,
        session_id=session.id,
        content=content if content is not None else {"assessment": "hold"},
        artifact_key=artifact_key if artifact_key is not None else compute_artifact_key(**_base_key_kwargs()),
        manifest_snapshot=kwargs.pop(
            "manifest_snapshot",
            {
                "fact_ids": ["f1"],
                "source_document_ids": ["d1"],
                "cutoff_date": "2026-09-01",
                "prompt_version": "research_prompts_v1",
                "model_version": "qwen-v1",
            },
        ),
        **kwargs,
    )


# -- compute_artifact_key -----------------------------------------------


def test_compute_artifact_key_deterministic():
    kwargs = _base_key_kwargs()
    assert compute_artifact_key(**kwargs) == compute_artifact_key(**kwargs)


@pytest.mark.parametrize(
    "field",
    ["entity", "question_scope", "cutoff_date", "prompt_version", "model_version", "research_policy_version"],
)
def test_compute_artifact_key_changes_per_field(field):
    base = compute_artifact_key(**_base_key_kwargs())
    changed = compute_artifact_key(**_base_key_kwargs(**{field: "CHANGED_VALUE"}))
    assert base != changed


# -- find_reusable_report -------------------------------------------------


async def test_find_reusable_report_returns_exact_match(db_session):
    session = await _make_session(db_session)
    key = compute_artifact_key(**_base_key_kwargs())
    published = await _publish(db_session, session, artifact_key=key)
    await db_session.commit()

    found = await find_reusable_report(db_session, key)
    assert found is not None
    assert found.id == published.id


async def test_find_reusable_report_returns_none_for_different_key(db_session):
    session = await _make_session(db_session)
    key = compute_artifact_key(**_base_key_kwargs())
    await _publish(db_session, session, artifact_key=key)
    await db_session.commit()

    different_key = compute_artifact_key(**_base_key_kwargs(entity="INFY"))
    found = await find_reusable_report(db_session, different_key)
    assert found is None


# -- profile/policy-only change -------------------------------------------


def test_research_policy_version_change_invalidates_key():
    # research_policy_version models the "profile/policy-relevant"
    # parameter for THIS shared-research artifact key. Per V3 13.2's cache
    # table, "Company report" and "Suitability/plan" are separate rows with
    # separate dependency keys -- personal-profile fields (risk profile,
    # holdings, goals) belong to the Suitability/plan cache key (Phase 05's
    # SuitabilityResult), not here. What DOES belong here is the
    # *research policy* version (source allowlists, verification/claim
    # rules, cutoff acceptance policy) since that changes what evidence a
    # company report is allowed to be built from -- a policy change must
    # invalidate reuse of the underlying research artifact itself.
    key_a = compute_artifact_key(**_base_key_kwargs(research_policy_version="policy_v1"))
    key_b = compute_artifact_key(**_base_key_kwargs(research_policy_version="policy_v2"))
    assert key_a != key_b


# -- publish_report / parent immutability ---------------------------------


async def test_refresh_does_not_mutate_parent(db_session):
    session = await _make_session(db_session)
    parent = await _publish(
        db_session,
        session,
        content={"assessment": "hold", "version": 1},
        manifest_snapshot={"fact_ids": ["f1"], "source_document_ids": ["d1"]},
    )
    await db_session.commit()
    parent_id = parent.id

    child = await _publish(
        db_session,
        session,
        content={"assessment": "buy", "version": 2},
        manifest_snapshot={"fact_ids": ["f1", "f2"], "source_document_ids": ["d1", "d2"]},
        parent_report_id=parent_id,
        revision_kind="refresh_sources",
        changed_source_ids=["d2"],
    )
    await db_session.commit()
    db_session.expunge_all()

    from sqlalchemy import select

    from app.models.research_report import ResearchReport

    refetched_parent = (
        await db_session.execute(select(ResearchReport).where(ResearchReport.id == parent_id))
    ).scalar_one()
    assert refetched_parent.content == {"assessment": "hold", "version": 1}
    assert refetched_parent.manifest_snapshot == {"fact_ids": ["f1"], "source_document_ids": ["d1"]}
    assert refetched_parent.parent_report_id is None

    refetched_child = (
        await db_session.execute(select(ResearchReport).where(ResearchReport.id == child.id))
    ).scalar_one()
    assert refetched_child.parent_report_id == parent_id
    assert refetched_child.revision_kind == "refresh_sources"
    assert refetched_child.changed_source_ids == ["d2"]


# -- create_follow_up ------------------------------------------------------


async def test_create_follow_up_rejects_invalid_revision_kind(db_session):
    session = await _make_session(db_session)
    parent = await _publish(db_session, session)
    await db_session.commit()

    with pytest.raises(ValueError):
        await create_follow_up(db_session, parent_report_id=parent.id, revision_kind="not_a_real_kind")


async def test_create_follow_up_rejects_nonexistent_parent(db_session):
    import uuid

    with pytest.raises(ValueError):
        await create_follow_up(
            db_session, parent_report_id=uuid.uuid4(), revision_kind="reuse_report_snapshot"
        )


async def test_create_follow_up_returns_linking_metadata(db_session):
    session = await _make_session(db_session)
    parent = await _publish(db_session, session)
    await db_session.commit()

    result = await create_follow_up(
        db_session,
        parent_report_id=parent.id,
        revision_kind="reuse_report_snapshot",
        changed_source_ids=None,
    )
    assert result == {
        "parent_report_id": parent.id,
        "revision_kind": "reuse_report_snapshot",
        "changed_source_ids": None,
    }


# -- diff_source_ids --------------------------------------------------------


def test_diff_source_ids_symmetric_difference():
    assert set(diff_source_ids(["a", "b"], ["b", "c"])) == {"a", "c"}


def test_diff_source_ids_only_addition():
    assert diff_source_ids(["a", "b"], ["a", "b", "c"]) == ["c"]


# -- compare_two_reports -----------------------------------------------------


async def test_compare_two_reports_reuses_content_unmodified(db_session):
    session = await _make_session(db_session)
    report_a = await _publish(
        db_session,
        session,
        content={"assessment": "buy", "entity": "TCS"},
        artifact_key=compute_artifact_key(**_base_key_kwargs(entity="TCS")),
    )
    report_b = await _publish(
        db_session,
        session,
        content={"assessment": "hold", "entity": "INFY"},
        artifact_key=compute_artifact_key(**_base_key_kwargs(entity="INFY")),
    )
    await db_session.commit()

    result = await compare_two_reports(db_session, report_a.id, report_b.id)
    assert result["report_a"] == {"assessment": "buy", "entity": "TCS"}
    assert result["report_b"] == {"assessment": "hold", "entity": "INFY"}
    assert result["manifest_a"] == report_a.manifest_snapshot
    assert result["manifest_b"] == report_b.manifest_snapshot


async def test_compare_two_reports_raises_for_missing_report(db_session):
    session = await _make_session(db_session)
    report_a = await _publish(db_session, session)
    await db_session.commit()

    import uuid

    with pytest.raises(ValueError):
        await compare_two_reports(db_session, report_a.id, uuid.uuid4())
