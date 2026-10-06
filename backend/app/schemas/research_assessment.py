"""Research report/assessment output schemas (V3 Phase 07, docs/V3-IMPLEMENTATION-
PLAN.md section 9.5, "Research output contract").

These are Pydantic response shapes, not SQLAlchemy models -- `CompanyAssessment`
is what a (future, model-assisted) synthesis step produces after Phase 06's
claim ledger has verified the underlying facts; it is not itself persisted by
this task.

V3 9.5: "The report never invents an exact target price or calibrated
confidence." `CompanyAssessment` has NO `target_price` and NO `confidence`
field anywhere -- that absence is deliberate and structural, enforced by
`test_research_assessment_schema.py` inspecting `model_fields` directly, not
just by convention.

V3 15.1: `SuitabilityNote` (personal suitability) is attached SEPARATELY,
using its own profile/policy versions -- it is never merged into
`CompanyAssessment` and never feeds back into company-quality evidence.
"""

from pydantic import BaseModel


class ClaimReference(BaseModel):
    """A pointer from an assessment section back to one claim-ledger Fact
    (app/models/evidence.py::Fact), carrying the support status that fact
    had at verification time so a reader never has to re-look-up the ledger
    to see whether a cited claim was actually verified."""

    fact_id: str
    text: str
    support_status: str  # mirrors Fact.support_status / VerificationResult.final_status


class CompanyAssessment(BaseModel):
    """V3 9.5: 'A report contains a short assessment, business/product
    explanation, strongest supporting and opposing evidence, period-aligned
    financial context, valuation/scenario assumptions, risks, catalysts,
    missing facts, and conditions that would change the assessment.'"""

    entity: str
    short_assessment: str
    business_explanation: str
    strongest_supporting_evidence: list[ClaimReference]
    strongest_opposing_evidence: list[ClaimReference]
    financial_context: list[ClaimReference]  # period-aligned -- see validate_period_alignment below
    valuation_assumptions: list[str]  # deterministic inputs/sensitivity ranges if a valuation scenario exists -- plain text descriptions, not a number this schema invents itself
    risks: list[str]
    catalysts: list[str]
    missing_facts: list[str]
    conditions_that_would_change_assessment: list[str]
    # V3 9.5: "The report never invents an exact target price or calibrated
    # confidence." This schema has NO target_price or confidence field at
    # all -- their absence is deliberate and structural, not an oversight.
    manifest_version: str  # ties this assessment to a specific evidence-manifest snapshot
    generated_at: str  # ISO datetime string


class SuitabilityNote(BaseModel):
    """V3 15.1: attached SEPARATELY, using its own profile/policy versions
    -- never merged into CompanyAssessment, and never feeds back into it."""

    profile_version: int
    policy_version: str
    eligible: bool
    binding_rules: list[str]
