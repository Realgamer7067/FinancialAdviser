"""Smoke test for the new /api/research/sessions router (V3 Phase 08).
Mocking pattern copied from tests/test_research_orchestrator.py -- patches
`fetch_document` at the workflow module's import site so no real network
call happens, then exercises the router end to end via the `client` fixture."""

from datetime import datetime, timezone

from app.services.retrieval import FetchedDocument
from app.services.source_corpus_fixtures import representative_corpus


async def test_post_sessions_reaches_ready_to_publish(client, monkeypatch):
    doc = representative_corpus()[0]

    async def _fake_fetch(url, policy, *, resolver=None):
        return FetchedDocument(
            url=url,
            final_url=url,
            content_hash="a" * 64,
            content_type="text/plain",
            byte_count=len(doc.raw_text),
            retrieved_at=datetime.now(timezone.utc),
            raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    res = await client.post(
        "/api/research/sessions",
        json={
            "question": "How is Example Bank Ltd performing?",
            "instrument_ids": [],
            "cutoff_policy": {"cutoff_date": "2026-09-14"},
            "budget_envelope": {"max_fetches": 10},
            "branch_fetch_urls": {
                "financials_valuation": ["https://fixtures.internal.example/f1"],
                "events_governance": ["https://fixtures.internal.example/f2"],
                "peers_downside": ["https://fixtures.internal.example/f3"],
            },
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["state"] == "ready_to_publish"
    assert len(body["branches"]) == 3
    assert all(b["status"] == "complete" for b in body["branches"])
    assert body["verification"] is not None
    assert body["verification"]["total_material_claims"] >= 0

    session_id = body["id"]

    res2 = await client.get(f"/api/research/sessions/{session_id}")
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["id"] == session_id
    assert body2["state"] == "ready_to_publish"
    assert len(body2["branches"]) == 3
    # Verification/contradictions are not persisted -- GET must not fabricate them.
    assert body2["verification"] is None
    assert body2["contradictions"] == []


async def test_get_unknown_session_returns_404(client):
    res = await client.get("/api/research/sessions/00000000-0000-0000-0000-000000000099")
    assert res.status_code == 404


async def test_post_sessions_auto_discovers_urls_for_empty_branches(client, monkeypatch):
    """find_sources defaults True -- a branch the caller leaves empty
    should get real discover_branch_urls-supplied URLs, not just sit
    "no fetch_urls provided" the way it did before search existed."""
    doc = representative_corpus()[0]

    async def _fake_fetch(url, policy, *, resolver=None):
        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    seen_branch_types = []

    async def _fake_discover(question, branch_type, api_key=None):
        seen_branch_types.append(branch_type)
        return ["https://fixtures.internal.example/auto-discovered"]

    monkeypatch.setattr("app.api.research.discover_branch_urls", _fake_discover)

    res = await client.post(
        "/api/research/sessions",
        json={
            "question": "How is Example Bank Ltd performing?",
            "instrument_ids": [],
            "cutoff_policy": {"cutoff_date": "2026-09-14"},
            "budget_envelope": {"max_fetches": 10},
            "branch_fetch_urls": {},  # every branch left empty -- should trigger discovery for all 3
        },
    )
    assert res.status_code == 201
    assert set(seen_branch_types) == {"financials_valuation", "events_governance", "peers_downside"}
    body = res.json()
    assert all(b["status"] == "complete" for b in body["branches"])


async def test_post_sessions_find_sources_false_skips_discovery(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.research.discover_branch_urls", lambda *a, **k: calls.append(1))

    res = await client.post(
        "/api/research/sessions",
        json={
            "question": "How is Example Bank Ltd performing?",
            "instrument_ids": [],
            "cutoff_policy": {"cutoff_date": "2026-09-14"},
            "budget_envelope": {"max_fetches": 10},
            "branch_fetch_urls": {},
            "find_sources": False,
        },
    )
    assert res.status_code == 201
    assert calls == []
    body = res.json()
    assert all(b["status"] == "unavailable" for b in body["branches"])


async def test_post_sessions_synthesizes_and_publishes_when_evidence_verifies(client, monkeypatch):
    doc = representative_corpus()[0]

    async def _fake_fetch(url, policy, *, resolver=None):
        return FetchedDocument(
            url=url, final_url=url, content_hash="a" * 64, content_type="text/plain",
            byte_count=len(doc.raw_text), retrieved_at=datetime.now(timezone.utc), raw_text=doc.raw_text,
        )

    monkeypatch.setattr("app.services.research_workflow.fetch_document", _fake_fetch)

    from app.services.research_orchestrator import SynthesisResult
    from app.models.research_report import ResearchReport
    import uuid as uuid_module
    from datetime import datetime as dt, timezone as tz

    fake_report = ResearchReport(
        id=uuid_module.uuid4(),
        session_id=uuid_module.uuid4(),
        artifact_key="fake-key",
        manifest_snapshot={},
        content={"entity": "Example Bank Ltd", "short_assessment": "fake"},
        published_at=dt.now(tz.utc),
    )

    async def _fake_synthesize(db, session_id, llm=None):
        from app.models.research import ResearchSession

        session = await db.get(ResearchSession, session_id)
        session.state = "published"
        await db.flush()
        return SynthesisResult(report=fake_report, session=session, error=None)

    monkeypatch.setattr("app.api.research.synthesize_and_publish", _fake_synthesize)

    res = await client.post(
        "/api/research/sessions",
        json={
            "question": "How is Example Bank Ltd performing?",
            "instrument_ids": [],
            "cutoff_policy": {"cutoff_date": "2026-09-14"},
            "budget_envelope": {"max_fetches": 10},
            "branch_fetch_urls": {
                "financials_valuation": ["https://fixtures.internal.example/f1"],
                "events_governance": ["https://fixtures.internal.example/f2"],
                "peers_downside": ["https://fixtures.internal.example/f3"],
            },
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["state"] == "published"
    assert body["report"]["entity"] == "Example Bank Ltd"
    assert body["synthesis_error"] is None

    # GET on a published session must return the persisted report too.
    res2 = await client.get(f"/api/research/sessions/{body['id']}")
    assert res2.status_code == 200
