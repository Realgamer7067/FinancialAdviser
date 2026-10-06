"""V3 Phase 07: report-level verification pass tests (docs/
V3-IMPLEMENTATION-PLAN.md sections 9.4-9.5).

Fixture pattern mirrors tests/test_evidence_ledger.py -- real Fact/
FactPassageLink/Passage rows via evidence_ledger.create_fact/
link_fact_to_passage, no mocked verify_fact."""

from datetime import datetime, timezone

from app.models.evidence import Passage, SourceDocument
from app.schemas.research_assessment import ClaimReference
from app.services.evidence_ledger import create_fact, link_fact_to_passage
from app.services.research_verification import (
    apply_sector_template,
    validate_period_alignment,
    verify_report_claims,
)


async def _make_document(db_session):
    doc = SourceDocument(
        url="https://fixtures.internal.example/doc1",
        content_hash="a" * 64,
        publication_time=datetime.now(timezone.utc),
        retrieval_time=datetime.now(timezone.utc),
        parser_version="test-v1",
        rights_note="public_filing",
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


async def _make_passage(db_session, doc, text="Revenue grew 12% year over year."):
    passage = Passage(document_id=doc.id, text=text, text_hash="b" * 64, location="page 1")
    db_session.add(passage)
    await db_session.flush()
    return passage


async def test_verify_report_claims_tallies_mixed_statuses_and_unresolved_critical(db_session):
    doc = await _make_document(db_session)
    good_passage = await _make_passage(db_session, doc, text="Revenue grew 12% YoY.")
    bad_passage = await _make_passage(db_session, doc, text="Revenue actually FELL.")
    empty_passage = await _make_passage(db_session, doc, text="   ")

    supported_fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, supported_fact.id, good_passage.id, "supports")

    contradicted_fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, contradicted_fact.id, bad_passage.id, "refutes")

    # "supports" link but the linked passage has no real text -- per V3 9.4
    # ("a real link without a supporting passage does not count as verified
    # support") and evidence_ledger.verify_fact, this resolves to
    # "unsupported" (a link exists, but not real support, and no refutes).
    truly_unsupported_fact = await create_fact(
        db_session, claim_type="source_fact", text="Claim with a link but no real passage text",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units=None, value=None,
    )
    await link_fact_to_passage(db_session, truly_unsupported_fact.id, empty_passage.id, "supports")

    unlinked_fact = await create_fact(
        db_session, claim_type="source_fact", text="Another unlinked claim",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units=None, value=None,
    )
    # No links at all -> "unknown" per evidence_ledger.
    await db_session.commit()

    fact_ids = [
        str(supported_fact.id),
        str(contradicted_fact.id),
        str(truly_unsupported_fact.id),
        str(unlinked_fact.id),
    ]
    critical_ids = [str(supported_fact.id), str(contradicted_fact.id), str(truly_unsupported_fact.id)]

    summary = await verify_report_claims(db_session, fact_ids, critical_fact_ids=critical_ids)

    assert summary.total_material_claims == 4
    assert summary.supported_count == 1
    assert summary.contradicted_count == 1
    assert summary.unsupported_count == 1
    assert summary.unknown_count == 1  # unlinked_fact only

    # Both the contradicted and truly-unsupported facts are critical and unresolved.
    # Compared as a set -- verify_report_claims iterates fact_ids in order, but
    # that ordering is an incidental property of the loop, not part of the contract.
    assert set(summary.unresolved_critical_claim_ids) == {str(contradicted_fact.id), str(truly_unsupported_fact.id)}
    assert len(summary.unresolved_critical_claim_ids) == 2
    assert summary.fully_verifiable is False


async def test_verify_report_claims_fully_verifiable_when_no_critical_unresolved(db_session):
    doc = await _make_document(db_session)
    passage = await _make_passage(db_session, doc)
    supported_fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, supported_fact.id, passage.id, "supports")
    await db_session.commit()

    summary = await verify_report_claims(db_session, [str(supported_fact.id)])
    assert summary.fully_verifiable is True
    assert summary.unresolved_critical_claim_ids == []


async def test_verify_report_claims_defaults_all_facts_to_critical_when_none_given(db_session):
    fact = await create_fact(
        db_session, claim_type="source_fact", text="Unlinked claim",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units=None, value=None,
    )
    await db_session.commit()
    # No links -> "unknown", which is not unsupported/contradicted, so still
    # not flagged as unresolved-critical even though critical_fact_ids=None
    # treats every fact as critical.
    summary = await verify_report_claims(db_session, [str(fact.id)])
    assert summary.unknown_count == 1
    assert summary.unresolved_critical_claim_ids == []
    assert summary.fully_verifiable is True


def test_validate_period_alignment_flags_real_mismatch():
    class _FakeFact:
        def __init__(self, period):
            self.period = period

    claim_a = ClaimReference(fact_id="fa", text="Revenue Q3", support_status="supported")
    claim_b = ClaimReference(fact_id="fb", text="Revenue Q1 next FY", support_status="supported")
    facts_by_id = {"fa": _FakeFact("FY2025-Q3"), "fb": _FakeFact("FY2026-Q1")}

    warnings = validate_period_alignment([claim_a, claim_b], facts_by_id)
    assert len(warnings) == 1
    assert "FY2025-Q3" in warnings[0]
    assert "FY2026-Q1" in warnings[0]


def test_validate_period_alignment_empty_for_same_period():
    class _FakeFact:
        def __init__(self, period):
            self.period = period

    claim_a = ClaimReference(fact_id="fa", text="Revenue", support_status="supported")
    claim_b = ClaimReference(fact_id="fb", text="Net profit", support_status="supported")
    facts_by_id = {"fa": _FakeFact("FY2026-Q1"), "fb": _FakeFact("FY2026-Q1")}

    assert validate_period_alignment([claim_a, claim_b], facts_by_id) == []


def test_apply_sector_template_removes_leverage_ratios_for_bank():
    ratios = {"debt_to_equity": 1.2, "roe": 0.15, "interest_coverage": 3.0}
    result = apply_sector_template("bank", ratios)
    assert result == {"roe": 0.15}


def test_apply_sector_template_leaves_non_financial_sector_unchanged():
    ratios = {"debt_to_equity": 1.2, "roe": 0.15}
    result = apply_sector_template("industrial", ratios)
    assert result == ratios
