"""End-to-end research orchestration glue (Phase 07 integration)."""

from sqlalchemy import select

from app.models.research import ResearchSession
from app.schemas.research_assessment import CompanyAssessment
from app.services.research_orchestrator import run_research_session, synthesize_and_publish
from app.services.retrieval import FetchPolicy
from app.services.source_corpus_fixtures import representative_corpus


def _fake_resolver(ips):
    def resolver(host, port):
        return ips
    return resolver


async def test_orchestration_reaches_ready_to_publish_with_real_fetches(db_session, monkeypatch):
    doc = representative_corpus()[0]

    # Patch fetch_document at the workflow module's import site to avoid
    # real network -- return a canned FetchedDocument for any URL.
    import app.services.retrieval as retrieval_module
    from app.services.retrieval import FetchedDocument
    from datetime import datetime, timezone

    async def _fake_fetch(url, policy, *, resolver=None):
        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    result = await run_research_session(
        db_session,
        user_id=None,
        question="How is Example Bank Ltd performing?",
        instrument_ids=[],
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
        branch_fetch_urls={
            "financials_valuation": ["https://fixtures.internal.example/f1"],
            "events_governance": ["https://fixtures.internal.example/f2"],
            "peers_downside": ["https://fixtures.internal.example/f3"],
        },
        retrieval_policy=FetchPolicy(allowed_hosts=None, max_bytes=100000, max_pages=None, timeout_seconds=5, max_redirects=2),
        resolver=_fake_resolver(["93.184.216.34"]),
    )
    await db_session.commit()

    assert result.session.state == "ready_to_publish"
    assert len(result.branches) == 3
    assert all(b.status == "complete" for b in result.branches)
    assert result.verification is not None

    # ADVERSARIAL FINDING (V3 Phase 10 release-acceptance review, 2026-09-15):
    # run_branch links every fact it creates to the SAME passage it was
    # copied from ("supports"), so evidence_ledger.verify_fact's layer 5
    # ("source_support": is there >=1 real 'supports' link to non-empty
    # passage text) is true BY CONSTRUCTION for every orchestrator-produced
    # fact -- it can never observe a source_fact that ISN'T "supported",
    # because the only passage a source_fact is ever linked to is its own
    # origin passage. That makes `fully_verifiable` a rubber stamp for any
    # branch that successfully fetched *something*, not a genuine check
    # that independent source text backs the claim. This assertion proves
    # the rubber-stamp behavior rather than merely asserting "verification
    # ran" -- if this ever legitimately changes (e.g. a real cross-passage
    # corroboration requirement is added), this assertion should be revisited,
    # not silently loosened.
    assert result.verification.supported_count == result.verification.total_material_claims
    assert result.verification.fully_verifiable is True


async def test_orchestration_stops_cleanly_when_all_sources_fail(db_session, monkeypatch):
    async def _always_fail(url, policy, *, resolver=None):
        from app.services.retrieval import RetrievalRejected
        raise RetrievalRejected("fixture: simulated fetch failure")

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _always_fail)

    result = await run_research_session(
        db_session,
        user_id=None,
        question="Unreachable evidence case",
        instrument_ids=[],
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
        branch_fetch_urls={
            "financials_valuation": ["https://fixtures.internal.example/dead"],
            "events_governance": [],
            "peers_downside": [],
        },
        retrieval_policy=FetchPolicy(allowed_hosts=None, max_bytes=100000, max_pages=None, timeout_seconds=5, max_redirects=2),
        resolver=_fake_resolver(["93.184.216.34"]),
    )
    await db_session.commit()

    # No hard crash -- session still reaches a terminal/near-terminal state
    # with named gaps recorded, never silently pretends success.
    assert result.session.state == "ready_to_publish"
    assert any(b.status in ("unavailable", "complete") for b in result.branches)
    assert len(result.named_gaps) >= 1


async def test_orchestration_stops_dispatching_new_branches_once_session_cancelled_mid_run(db_session, monkeypatch):
    """Adversarial check (V3 Phase 10 release-acceptance review): STATE.md /
    phase-07.md disclose 'branch-level cancellation isn't wired (only
    session-level is); run_branch doesn't check session state before
    executing.' `run_branch` genuinely still has no such check (confirmed
    by reading app/services/research_workflow.py directly). But
    `run_research_session`'s own docstring claims IT is the caller that
    checks session state before every branch dispatch, so a concurrently-
    cancelled session stops receiving NEW branch dispatches. This test
    proves that claim empirically rather than trusting the docstring: the
    fake fetch for the FIRST branch cancels the session as a side effect
    (simulating a concurrent user cancellation), and we assert no fetch is
    ever attempted for the 2nd/3rd branches."""
    doc = representative_corpus()[0]
    fetch_calls: list[str] = []

    async def _fetch_then_cancel_session(url, policy, *, resolver=None):
        from datetime import datetime, timezone

        from app.services.retrieval import FetchedDocument

        fetch_calls.append(url)
        # Simulate a concurrent cancellation landing right after the first
        # branch's fetch starts -- bypass the public API and flip state
        # directly, exactly as if another request/process cancelled it.
        session = (await db_session.execute(select(ResearchSession))).scalars().first()
        session.state = "cancelled"
        await db_session.flush()
        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fetch_then_cancel_session)

    result = await run_research_session(
        db_session,
        user_id=None,
        question="Cancellation mid-run case",
        instrument_ids=[],
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
        branch_fetch_urls={
            "financials_valuation": ["https://fixtures.internal.example/f1"],
            "events_governance": ["https://fixtures.internal.example/f2"],
            "peers_downside": ["https://fixtures.internal.example/f3"],
        },
        retrieval_policy=FetchPolicy(allowed_hosts=None, max_bytes=100000, max_pages=None, timeout_seconds=5, max_redirects=2),
        resolver=_fake_resolver(["93.184.216.34"]),
    )
    await db_session.commit()

    # Only the first branch's fetch ever ran -- the 2nd/3rd branches' URLs
    # were never dispatched once cancellation was observed.
    assert fetch_calls == ["https://fixtures.internal.example/f1"]
    assert result.session.state == "cancelled"
    assert result.stopped_reason is not None and "cancelled" in result.stopped_reason.lower()


def _fake_assessment() -> CompanyAssessment:
    return CompanyAssessment(
        entity="Example Bank Ltd",
        short_assessment="Fake assessment for test purposes.",
        business_explanation="Fake business explanation.",
        strongest_supporting_evidence=[],
        strongest_opposing_evidence=[],
        financial_context=[],
        valuation_assumptions=[],
        risks=[],
        catalysts=[],
        missing_facts=[],
        conditions_that_would_change_assessment=[],
        manifest_version="placeholder",  # synthesize_and_publish overrides this with a real deterministic value
        generated_at="placeholder",  # same -- overridden, just needs to satisfy schema validation here
    )


class _FakeLLM:
    """Test double for QwenOpenAICompatibleProvider -- avoids a real network
    call while exercising synthesize_and_publish's real logic (payload
    construction, publish, state transition) around it."""

    def __init__(self, response=None, raise_error=None):
        self._response = response
        self._raise_error = raise_error
        self.last_payload = None

    async def complete_structured(self, system_prompt, user_payload, response_model, prompt_version):
        self.last_payload = user_payload
        if self._raise_error:
            from app.models_iface.llm import StructuredOutputError

            raise StructuredOutputError(self._raise_error)
        return self._response, {"model_name": "FakeModel", "model_version": "fake-v1", "prompt_version": prompt_version}


async def test_synthesize_and_publish_only_hands_supported_facts_to_the_model(db_session, monkeypatch):
    doc = representative_corpus()[0]

    async def _fake_fetch(url, policy, *, resolver=None):
        from datetime import datetime, timezone

        from app.services.retrieval import FetchedDocument

        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    result = await run_research_session(
        db_session,
        user_id=None,
        question="How is Example Bank Ltd performing?",
        instrument_ids=[],
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
        branch_fetch_urls={
            "financials_valuation": ["https://fixtures.internal.example/f1"],
            "events_governance": [],
            "peers_downside": [],
        },
        retrieval_policy=FetchPolicy(allowed_hosts=None, max_bytes=100000, max_pages=None, timeout_seconds=5, max_redirects=2),
        resolver=_fake_resolver(["93.184.216.34"]),
    )
    await db_session.commit()
    assert result.session.state == "ready_to_publish"

    fake_llm = _FakeLLM(response=_fake_assessment())
    synth = await synthesize_and_publish(db_session, result.session.id, llm=fake_llm)

    assert synth.error is None
    assert synth.report is not None
    assert synth.session.state == "published"
    assert synth.report.content["entity"] == "Example Bank Ltd"
    # Every fact_id handed to the model must be one the deterministic ledger
    # actually marked "supported" -- never an unverified fact_id.
    assert len(fake_llm.last_payload["facts"]) > 0
    for f in fake_llm.last_payload["facts"]:
        assert f["fact_id"] in [str(fid) for b in result.branches for fid in (b.fact_ids or [])]


async def test_synthesize_and_publish_fails_closed_when_model_call_fails(db_session, monkeypatch):
    doc = representative_corpus()[0]

    async def _fake_fetch(url, policy, *, resolver=None):
        from datetime import datetime, timezone

        from app.services.retrieval import FetchedDocument

        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    result = await run_research_session(
        db_session,
        user_id=None,
        question="How is Example Bank Ltd performing?",
        instrument_ids=[],
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
        branch_fetch_urls={
            "financials_valuation": ["https://fixtures.internal.example/f1"],
            "events_governance": [],
            "peers_downside": [],
        },
        retrieval_policy=FetchPolicy(allowed_hosts=None, max_bytes=100000, max_pages=None, timeout_seconds=5, max_redirects=2),
        resolver=_fake_resolver(["93.184.216.34"]),
    )
    await db_session.commit()

    fake_llm = _FakeLLM(raise_error="simulated model failure")
    synth = await synthesize_and_publish(db_session, result.session.id, llm=fake_llm)

    assert synth.report is None
    assert synth.error is not None and "model call failed" in synth.error
    # Session stays at ready_to_publish -- never force-advanced to
    # "published" on a failed/fabricated synthesis.
    assert synth.session.state == "ready_to_publish"


async def test_synthesize_and_publish_errors_when_no_evidence_verified(db_session):
    from app.services.research_workflow import create_session, transition

    session = await create_session(
        db_session,
        user_id=None,
        question="No evidence case",
        instrument_ids=[],
        mode="standard",
        cutoff_policy={"cutoff_date": "2026-09-14"},
        budget_envelope={"max_fetches": 10},
    )
    for state in ("resolving", "retrieving", "calculating", "synthesizing", "verifying", "ready_to_publish"):
        await transition(db_session, session.id, state)
    await db_session.commit()

    fake_llm = _FakeLLM(response=_fake_assessment())
    synth = await synthesize_and_publish(db_session, session.id, llm=fake_llm)

    assert synth.report is None
    assert "no evidence" in synth.error.lower()
    assert synth.session.state == "ready_to_publish"
