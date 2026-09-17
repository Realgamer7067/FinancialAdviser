"""V3 Phase 07: CompanyAssessment/SuitabilityNote schema tests (docs/
V3-IMPLEMENTATION-PLAN.md section 9.5) and the versioned synthesis/
verification prompts (app/council/research_prompts.py)."""

from app.council.research_prompts import SYNTHESIS_PROMPT_V1, VERIFICATION_PROMPT_V1
from app.schemas.research_assessment import ClaimReference, CompanyAssessment, SuitabilityNote


def _example_payload() -> dict:
    supporting = ClaimReference(fact_id="f1", text="Revenue grew 12% YoY", support_status="supported")
    opposing = ClaimReference(fact_id="f2", text="Margins compressed 200bps", support_status="supported")
    financial = ClaimReference(fact_id="f3", text="Debt/equity 1.2x", support_status="unknown")
    return dict(
        entity="Example Bank Ltd (SYNTHETIC)",
        short_assessment="Steady revenue growth offset by margin pressure.",
        business_explanation="Retail and corporate banking across India.",
        strongest_supporting_evidence=[supporting],
        strongest_opposing_evidence=[opposing],
        financial_context=[financial],
        valuation_assumptions=["Base case assumes 10% loan book growth; sensitivity +/-2%."],
        risks=["Asset quality deterioration in a downturn."],
        catalysts=["Upcoming quarterly results."],
        missing_facts=["No point-in-time NPA data for the most recent quarter."],
        conditions_that_would_change_assessment=["A material rise in gross NPA ratio."],
        manifest_version="manifest_v1",
        generated_at="2026-09-14T00:00:00+00:00",
    )


def test_company_assessment_round_trips_through_pydantic_validation():
    payload = _example_payload()
    assessment = CompanyAssessment(**payload)
    dumped = assessment.model_dump()
    reloaded = CompanyAssessment(**dumped)
    assert reloaded == assessment
    assert reloaded.entity == "Example Bank Ltd (SYNTHETIC)"
    assert reloaded.strongest_supporting_evidence[0].fact_id == "f1"


def test_company_assessment_has_no_target_price_or_confidence_field():
    field_names = set(CompanyAssessment.model_fields.keys())
    expected = {
        "entity",
        "short_assessment",
        "business_explanation",
        "strongest_supporting_evidence",
        "strongest_opposing_evidence",
        "financial_context",
        "valuation_assumptions",
        "risks",
        "catalysts",
        "missing_facts",
        "conditions_that_would_change_assessment",
        "manifest_version",
        "generated_at",
    }
    assert field_names == expected
    for name in field_names:
        assert "target_price" not in name
        assert "confidence" not in name


def test_suitability_note_is_separate_and_has_no_company_evidence_fields():
    note = SuitabilityNote(
        profile_version=3, policy_version="risk_policy_v2", eligible=True, binding_rules=["max_equity_60pct"]
    )
    assert note.eligible is True
    field_names = set(SuitabilityNote.model_fields.keys())
    assert field_names == {"profile_version", "policy_version", "eligible", "binding_rules"}
    # Not merged with CompanyAssessment -- disjoint field sets.
    assert field_names.isdisjoint(CompanyAssessment.model_fields.keys())


def test_synthesis_and_verification_prompts_are_nonempty_and_forbid_invented_numbers():
    assert isinstance(SYNTHESIS_PROMPT_V1, str) and len(SYNTHESIS_PROMPT_V1.strip()) > 0
    assert isinstance(VERIFICATION_PROMPT_V1, str) and len(VERIFICATION_PROMPT_V1.strip()) > 0

    assert "Never invent an exact target price or a calibrated confidence number" in SYNTHESIS_PROMPT_V1
    assert "target price" in SYNTHESIS_PROMPT_V1.lower()
    assert "confidence" in SYNTHESIS_PROMPT_V1.lower()

    assert "not ground truth" in VERIFICATION_PROMPT_V1
    assert "Do not propose a target price or a confidence number" in VERIFICATION_PROMPT_V1
