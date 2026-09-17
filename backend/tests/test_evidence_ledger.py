"""V3 Phase 06 claim ledger (docs/V3-IMPLEMENTATION-PLAN.md section 9.4).
Coordinator-written -- the original evidence worker's session hit a rate
limit before producing any files; this module and its tests were built
directly by the coordinator from the same frozen contract that task packet
specified."""

from datetime import datetime, timezone

import pytest

from app.models.evidence import SourceDocument
from app.services.evidence_ledger import create_fact, link_fact_to_passage, verify_fact


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
    from app.models.evidence import Passage
    passage = Passage(document_id=doc.id, text=text, text_hash="b" * 64, location="page 1")
    db_session.add(passage)
    await db_session.flush()
    return passage


async def test_create_source_fact_succeeds(db_session):
    fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await db_session.commit()
    assert fact.id is not None
    assert fact.support_status == "unknown"


async def test_calculation_missing_formula_id_rejected(db_session):
    with pytest.raises(ValueError):
        await create_fact(
            db_session, claim_type="calculation", text="derived ratio",
            entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="ratio", value="1.5",
            formula_id=None, input_fact_ids=[], code_version="v1",
        )


async def test_calculation_with_nonexistent_input_fact_rejected(db_session):
    import uuid
    with pytest.raises(ValueError):
        await create_fact(
            db_session, claim_type="calculation", text="derived ratio",
            entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="ratio", value="1.5",
            formula_id="debt_to_equity_v1", input_fact_ids=[str(uuid.uuid4())], code_version="v1",
        )


async def test_verify_source_fact_with_no_links_is_unknown(db_session):
    fact = await create_fact(
        db_session, claim_type="source_fact", text="x", entity="E", period=None, units=None, value=None,
    )
    await db_session.commit()
    result = await verify_fact(db_session, fact.id)
    assert result.final_status == "unknown"


async def test_verify_source_fact_with_real_support_link_is_supported(db_session):
    doc = await _make_document(db_session)
    passage = await _make_passage(db_session, doc)
    fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, fact.id, passage.id, "supports")
    await db_session.commit()

    result = await verify_fact(db_session, fact.id)
    assert result.final_status == "supported"
    assert result.layer_results["source_support"] is True


async def test_verify_fact_with_only_refutes_link_is_contradicted(db_session):
    doc = await _make_document(db_session)
    passage = await _make_passage(db_session, doc, text="Revenue actually FELL 5%.")
    fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, fact.id, passage.id, "refutes")
    await db_session.commit()

    result = await verify_fact(db_session, fact.id)
    assert result.final_status == "contradicted"


async def test_real_link_without_supporting_passage_text_does_not_count(db_session):
    # V3 9.4: "A real link without a supporting passage does not count as
    # verified support." A FactPassageLink pointing at a Passage with EMPTY
    # text must not be treated as real support.
    doc = await _make_document(db_session)
    empty_passage = await _make_passage(db_session, doc, text="   ")
    fact = await create_fact(
        db_session, claim_type="source_fact", text="claim with no real backing",
        entity="Example Bank Ltd (SYNTHETIC)", period=None, units=None, value=None,
    )
    await link_fact_to_passage(db_session, fact.id, empty_passage.id, "supports")
    await db_session.commit()

    result = await verify_fact(db_session, fact.id)
    assert result.final_status != "supported"
    assert result.layer_results["source_support"] is False


async def test_calculation_with_consistent_inputs_is_supported(db_session):
    input_fact = await create_fact(
        db_session, claim_type="source_fact", text="Total debt is 500",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="inr_crore", value="500",
    )
    await db_session.flush()
    calc = await create_fact(
        db_session, claim_type="calculation", text="Debt/equity ratio",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="ratio", value="1.5",
        formula_id="debt_to_equity_v1", input_fact_ids=[str(input_fact.id)], code_version="v1",
    )
    await db_session.commit()

    result = await verify_fact(db_session, calc.id)
    assert result.final_status == "supported"


async def test_calculation_with_inconsistent_entities_is_not_supported(db_session):
    input_a = await create_fact(
        db_session, claim_type="source_fact", text="Debt is 500",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="inr_crore", value="500",
    )
    input_b = await create_fact(
        db_session, claim_type="source_fact", text="Equity is 300",
        entity="A Totally Different Company (SYNTHETIC)", period="FY2026-Q2", units="inr_crore", value="300",
    )
    await db_session.flush()
    calc = await create_fact(
        db_session, claim_type="calculation", text="Mismatched-entity ratio",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="ratio", value="1.67",
        formula_id="debt_to_equity_v1", input_fact_ids=[str(input_a.id), str(input_b.id)], code_version="v1",
    )
    await db_session.commit()

    result = await verify_fact(db_session, calc.id)
    assert result.final_status == "unsupported"
    assert result.layer_results["entity_date_unit_consistency"] is False
    assert any("inconsistent entities" in r for r in result.reasons)


async def test_numerical_check_does_not_recompute_the_formula_bypass(db_session):
    # ADVERSARIAL FINDING (V3 Phase 10 release-acceptance review, 2026-09-15):
    # verify_fact's "numerical_check" layer for a calculation only asks
    # "is there at least one numeric input fact this could plausibly have
    # been derived from" -- it never actually recomputes `formula_id`
    # against the input values and compares to `value`. A calculation whose
    # stated value is wildly, obviously wrong for its own declared formula
    # still passes every layer and comes back "supported". This is a real
    # gap against the module's own docstring promise ("deterministic
    # numerical checks"), not a bypass of the code's actual (narrower,
    # undocumented-as-such) contract -- flagging it here rather than
    # silently treating "supported" as "verified correct".
    debt = await create_fact(
        db_session, claim_type="source_fact", text="Total debt is 500",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="inr_crore", value="500",
    )
    equity = await create_fact(
        db_session, claim_type="source_fact", text="Total equity is 250",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="inr_crore", value="250",
    )
    await db_session.flush()
    # The correct debt/equity ratio here is 2.0 -- this claims 999999.
    bogus_calc = await create_fact(
        db_session, claim_type="calculation", text="Debt/equity ratio",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="ratio", value="999999",
        formula_id="debt_to_equity_v1", input_fact_ids=[str(debt.id), str(equity.id)], code_version="v1",
    )
    await db_session.commit()

    result = await verify_fact(db_session, bogus_calc.id)
    assert result.layer_results["numerical_check"] is True  # passes despite being nonsense
    assert result.final_status == "supported"  # should NOT be, given the actual math


async def test_verify_fact_persists_result_back_to_the_fact_row(db_session):
    # FIXED (V3 Phase 10 release-acceptance review, 2026-09-15): verify_fact
    # used to return a VerificationResult without ever writing
    # fact.support_status back to the database row, so app/schemas/
    # research_assessment.py's ClaimReference.support_status ("mirrors
    # Fact.support_status") had nothing real to mirror. verify_fact now
    # persists final_status onto the Fact row it just checked.
    doc = await _make_document(db_session)
    passage = await _make_passage(db_session, doc, text="Revenue grew 12% YoY.")
    fact = await create_fact(
        db_session, claim_type="source_fact", text="Revenue grew 12% YoY",
        entity="Example Bank Ltd (SYNTHETIC)", period="FY2026-Q2", units="percent", value="0.12",
    )
    await link_fact_to_passage(db_session, fact.id, passage.id, "supports")
    await db_session.commit()

    result = await verify_fact(db_session, fact.id)
    assert result.final_status == "supported"

    await db_session.refresh(fact)
    assert fact.support_status == "supported"  # now persisted, matches verify_fact's own verdict


async def test_invalid_claim_type_rejected(db_session):
    with pytest.raises(ValueError):
        await create_fact(
            db_session, claim_type="not_a_real_type", text="x", entity="E", period=None, units=None, value=None,
        )


async def test_invalid_link_type_rejected(db_session):
    doc = await _make_document(db_session)
    passage = await _make_passage(db_session, doc)
    fact = await create_fact(
        db_session, claim_type="source_fact", text="x", entity="E", period=None, units=None, value=None,
    )
    with pytest.raises(ValueError):
        await link_fact_to_passage(db_session, fact.id, passage.id, "maybe")
