"""Phase 07 research workflow worker (V3 implementation plan section 9.2/9.3).

No real network/model call anywhere in these tests -- `fetch_document` is
monkeypatched at the point `app.services.research_workflow` imports it, so
no DNS/TCP/HTTP happens at all (not even against the resolver-injection
point, which only defends against real SSRF and still needs a real
transport underneath it)."""

from datetime import datetime, timezone

import pytest

from app.services.retrieval import FetchedDocument, FetchPolicy, RetrievalRejected
from app.models.evidence import Fact, FactPassageLink, Passage, SourceDocument
from app.models.research import ResearchBranch, ResearchSession
from app.services.research_workflow import (
    BudgetExhausted,
    InvalidStateTransition,
    check_budget,
    check_material_contradiction,
    cancel_session,
    create_session,
    run_branch,
    run_standard_checklist,
    transition,
)
import app.services.research_workflow as research_workflow


def _policy():
    return FetchPolicy(allowed_hosts=None, max_bytes=1_000_000, max_pages=None, timeout_seconds=5.0, max_redirects=3)


def _document(url: str, text: str) -> FetchedDocument:
    return FetchedDocument(
        url=url,
        final_url=url,
        content_hash="a" * 64,
        content_type="text/plain",
        byte_count=len(text),
        retrieved_at=datetime.now(timezone.utc),
        raw_text=text,
    )


async def _create_test_session(db_session, *, budget_envelope=None):
    return await create_session(
        db_session,
        user_id=None,
        question="Is Example Bank Ltd a buy?",
        instrument_ids=["instrument-1"],
        mode="standard",
        cutoff_policy={"cutoff_date": "2026-09-14", "accept_sources_published_before": "2026-09-14"},
        budget_envelope=budget_envelope or {"searches": 8, "fetches": 20, "tokens": 50000, "deadline_seconds": 120},
    )


# --------------------------------------------------------------------------
# Ordinary report: standard checklist runs 3 branches, all complete
# --------------------------------------------------------------------------


async def test_standard_checklist_creates_three_pending_branches(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()

    branches = await run_standard_checklist(db_session, session.id)
    await db_session.commit()

    assert len(branches) == 3
    assert {b.branch_type for b in branches} == {"financials_valuation", "events_governance", "peers_downside"}
    assert all(b.status == "pending" for b in branches)


async def test_ordinary_branch_run_all_urls_succeed_ends_complete(db_session, monkeypatch):
    session = await _create_test_session(db_session)
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "financials_valuation"]
    await db_session.commit()

    async def fake_fetch(url, policy, **kwargs):
        return _document(url, f"Revenue for Example Bank grew 12% at {url}.")

    monkeypatch.setattr(research_workflow, "fetch_document", fake_fetch)

    result = await run_branch(
        db_session,
        branch.id,
        fetch_urls=["https://fixtures.example/a", "https://fixtures.example/b"],
        retrieval_policy=_policy(),
    )
    await db_session.commit()

    assert result.status == "complete"
    assert result.gap_reason is None
    assert len(result.fact_ids) == 2  # one passage each, one url each


# --------------------------------------------------------------------------
# Missing source: all fetch URLs fail -> 'unavailable'
# --------------------------------------------------------------------------


async def test_branch_all_urls_fail_ends_unavailable(db_session, monkeypatch):
    session = await _create_test_session(db_session)
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "events_governance"]
    await db_session.commit()

    async def failing_fetch(url, policy, **kwargs):
        raise RetrievalRejected(f"host not in allowlist for {url}")

    monkeypatch.setattr(research_workflow, "fetch_document", failing_fetch)

    result = await run_branch(
        db_session,
        branch.id,
        fetch_urls=["https://missing.example/doc1", "https://missing.example/doc2"],
        retrieval_policy=_policy(),
    )
    await db_session.commit()

    assert result.status == "unavailable"
    assert result.gap_reason is not None
    assert "missing.example" in result.gap_reason
    assert result.fact_ids == []


# --------------------------------------------------------------------------
# Budget exhausted mid-branch -> partial, no further fetches attempted
# --------------------------------------------------------------------------


async def test_budget_exhausted_mid_branch_ends_partial(db_session, monkeypatch):
    session = await _create_test_session(db_session, budget_envelope={"fetches": 1})
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "peers_downside"]
    await db_session.commit()

    call_count = {"n": 0}

    async def counting_fetch(url, policy, **kwargs):
        call_count["n"] += 1
        return _document(url, "Peer comparison data.")

    monkeypatch.setattr(research_workflow, "fetch_document", counting_fetch)

    result = await run_branch(
        db_session,
        branch.id,
        fetch_urls=["https://fixtures.example/peer1", "https://fixtures.example/peer2", "https://fixtures.example/peer3"],
        retrieval_policy=_policy(),
    )
    await db_session.commit()

    assert call_count["n"] == 1  # only the first fetch consumed the sole budget unit
    assert result.status == "partial"
    assert "budget exhausted" in result.gap_reason.lower()
    assert len(result.fact_ids) == 1

    await db_session.refresh(session)
    assert session.budget_exhausted_reason is not None
    assert session.named_gaps and session.named_gaps[0]["status"] == "partial"


async def test_budget_exhausted_respects_max_prefixed_envelope_key(db_session, monkeypatch):
    # The frozen ResearchSession.budget_envelope example uses "max_"-prefixed
    # keys (e.g. "max_fetches") -- a session created with that documented
    # shape must still be enforced, not silently unbounded.
    session = await _create_test_session(db_session, budget_envelope={"max_fetches": 1})
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "peers_downside"]
    await db_session.commit()

    call_count = {"n": 0}

    async def counting_fetch(url, policy, **kwargs):
        call_count["n"] += 1
        return _document(url, "Peer comparison data.")

    monkeypatch.setattr(research_workflow, "fetch_document", counting_fetch)

    result = await run_branch(
        db_session,
        branch.id,
        fetch_urls=["https://fixtures.example/peer1", "https://fixtures.example/peer2"],
        retrieval_policy=_policy(),
    )
    await db_session.commit()

    assert call_count["n"] == 1
    assert result.status == "partial"


async def test_branch_unexpected_exception_ends_failed(db_session, monkeypatch):
    session = await _create_test_session(db_session)
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "financials_valuation"]
    await db_session.commit()

    async def broken_fetch(url, policy, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(research_workflow, "fetch_document", broken_fetch)

    result = await run_branch(
        db_session,
        branch.id,
        fetch_urls=["https://fixtures.example/a"],
        retrieval_policy=_policy(),
    )
    await db_session.commit()

    assert result.status == "failed"
    assert "boom" in result.gap_reason

    await db_session.refresh(session)
    assert session.named_gaps and session.named_gaps[0]["status"] == "failed"


def test_check_budget_pure_function_raises_when_exceeded():
    session = ResearchSession(
        user_id=None,
        question="q",
        instrument_ids=[],
        mode="standard",
        cutoff_policy={},
        state="created",
        budget_envelope={"fetches": 2},
        budget_consumed={"fetches": 2},
        named_gaps=[],
    )
    with pytest.raises(BudgetExhausted):
        check_budget(session, "fetches", 1)
    # A resource absent from the envelope is treated as unbounded, not zero.
    check_budget(session, "tokens", 100000)


def test_check_budget_accepts_max_prefixed_key():
    session = ResearchSession(
        user_id=None,
        question="q",
        instrument_ids=[],
        mode="standard",
        cutoff_policy={},
        state="created",
        budget_envelope={"max_fetches": 2},
        budget_consumed={"max_fetches": 2},
        named_gaps=[],
    )
    with pytest.raises(BudgetExhausted):
        check_budget(session, "fetches", 1)


# --------------------------------------------------------------------------
# Cancelled branch/session
# --------------------------------------------------------------------------


async def test_cancel_from_non_terminal_state_succeeds(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()

    cancelled = await cancel_session(db_session, session.id)
    await db_session.commit()

    assert cancelled.state == "cancelled"


async def test_cancel_from_published_raises(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()

    for state in ("resolving", "retrieving", "calculating", "synthesizing", "verifying", "ready_to_publish", "published"):
        session = await transition(db_session, session.id, state)
    await db_session.commit()
    assert session.state == "published"

    with pytest.raises(InvalidStateTransition):
        await cancel_session(db_session, session.id)


# --------------------------------------------------------------------------
# Invalid transition attempts
# --------------------------------------------------------------------------


async def test_created_to_published_directly_raises(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()

    with pytest.raises(InvalidStateTransition):
        await transition(db_session, session.id, "published")


async def test_valid_forward_transition_succeeds(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()

    updated = await transition(db_session, session.id, "resolving")
    await db_session.commit()

    assert updated.state == "resolving"


# --------------------------------------------------------------------------
# Contradictory-filing case
# --------------------------------------------------------------------------


async def test_check_material_contradiction_detects_refutes_link(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "financials_valuation"]
    await db_session.commit()

    doc = SourceDocument(
        url="https://fixtures.example/doc",
        content_hash="b" * 64,
        publication_time=None,
        retrieval_time=datetime.now(timezone.utc),
        parser_version="test-v1",
        rights_note=None,
    )
    db_session.add(doc)
    await db_session.flush()

    passage = Passage(document_id=doc.id, text="Revenue actually fell 5%.", text_hash="c" * 64, location=None)
    db_session.add(passage)
    await db_session.flush()

    fact = Fact(
        claim_type="source_fact",
        text="Revenue grew 12%",
        entity="Example Bank Ltd",
        period="FY2026-Q2",
        units="percent",
        value="0.12",
        support_status="unknown",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(fact)
    await db_session.flush()

    link = FactPassageLink(fact_id=fact.id, passage_id=passage.id, link_type="refutes")
    db_session.add(link)
    await db_session.flush()

    branch.fact_ids = [str(fact.id)]
    await db_session.flush()
    await db_session.commit()

    contradictions = await check_material_contradiction(db_session, session.id)

    assert len(contradictions) == 1
    assert contradictions[0]["fact_id"] == str(fact.id)
    assert "refutes" in contradictions[0]["reason"]


async def test_check_material_contradiction_blind_to_conflicting_supports_only_facts(db_session):
    # ADVERSARIAL FINDING (V3 Phase 10 release-acceptance review, 2026-09-15):
    # check_material_contradiction only looks for FactPassageLink rows with
    # link_type == "refutes". It has NO notion of "two source_fact rows for
    # the same entity/period/claim area with conflicting numeric VALUES,
    # each only ever 'supports'-linked to its own source". Two branches
    # genuinely disagreeing (one source says NPA 1.8%, another says NPA
    # 3.2%, for the same entity/period) produce zero detected
    # contradictions here, because nothing ever created a "refutes" link --
    # nothing in this codebase does that reconciliation. This is an honest
    # scope limit (the function's own docstring only promises to scan for
    # 'refutes'-type FactPassageLink conflicts), but it means the practical
    # value-conflict case this task asked to probe is NOT caught by this
    # function at all -- only a pre-existing, explicitly-authored 'refutes'
    # link is.
    session = await _create_test_session(db_session)
    await db_session.commit()
    [branch] = [b for b in await run_standard_checklist(db_session, session.id) if b.branch_type == "financials_valuation"]
    await db_session.commit()

    doc = SourceDocument(
        url="https://fixtures.example/doc-a", content_hash="d" * 64, publication_time=None,
        retrieval_time=datetime.now(timezone.utc), parser_version="test-v1", rights_note=None,
    )
    db_session.add(doc)
    await db_session.flush()

    passage_a = Passage(document_id=doc.id, text="Gross NPA ratio stood at 1.8%.", text_hash="e" * 64, location=None)
    passage_b = Passage(document_id=doc.id, text="Gross NPA ratio stood at 3.2%.", text_hash="f" * 64, location=None)
    db_session.add_all([passage_a, passage_b])
    await db_session.flush()

    fact_a = Fact(
        claim_type="source_fact", text="Gross NPA ratio stood at 1.8%", entity="Example Bank Ltd",
        period="FY2026-Q2", units="percent", value="0.018", support_status="unknown",
        created_at=datetime.now(timezone.utc),
    )
    fact_b = Fact(
        claim_type="source_fact", text="Gross NPA ratio stood at 3.2%", entity="Example Bank Ltd",
        period="FY2026-Q2", units="percent", value="0.032", support_status="unknown",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([fact_a, fact_b])
    await db_session.flush()

    db_session.add_all([
        FactPassageLink(fact_id=fact_a.id, passage_id=passage_a.id, link_type="supports"),
        FactPassageLink(fact_id=fact_b.id, passage_id=passage_b.id, link_type="supports"),
    ])
    await db_session.flush()

    branch.fact_ids = [str(fact_a.id), str(fact_b.id)]
    await db_session.flush()
    await db_session.commit()

    contradictions = await check_material_contradiction(db_session, session.id)
    assert contradictions == []  # genuinely conflicting values, but undetected -- documented gap


async def test_check_material_contradiction_empty_when_no_refutes_links(db_session):
    session = await _create_test_session(db_session)
    await db_session.commit()
    await run_standard_checklist(db_session, session.id)
    await db_session.commit()

    contradictions = await check_material_contradiction(db_session, session.id)
    assert contradictions == []
