"""Report-level verification pass (V3 Phase 07, docs/V3-IMPLEMENTATION-
PLAN.md sections 9.4 "Claim ledger" and 9.5 "Research output contract").

This module does NOT reimplement fact verification -- it calls
`app.services.evidence_ledger.verify_fact` per material claim (that
function already runs the full layered check -- schema, referenced-ID
existence, entity/date/unit consistency, numerical checks, then
source-support -- and returns a `VerificationResult.final_status` of
supported/unsupported/unknown/contradicted) and tallies/interprets those
results at the report level:

- `verify_report_claims` tallies final_status counts across every material
  claim in a report and flags which "critical" claims (V3 9.4: "Critical
  unresolved numeric claims are removed or shown as unknown") came back
  unsupported/contradicted so a caller can strip or mark them unknown
  before publishing.
- `validate_period_alignment` and `apply_sector_template` are narrow,
  explicit, deterministic report-construction checks called out by V3 9.5
  ("period-aligned financial context", "Sector templates prevent applying
  industrial debt ratios blindly to banks") -- neither is a general
  fiscal-calendar or financial-ratio reasoning engine, and each says so.
"""

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evidence_ledger import verify_fact

if TYPE_CHECKING:
    from app.models.evidence import Fact
    from app.schemas.research_assessment import ClaimReference

# Ratio-name substrings that describe an industrial/non-financial company's
# capital structure (leverage against equity, ability to service debt from
# operating earnings) and don't apply the same way to a bank/NBFC's balance
# sheet, where liabilities are largely deposits/borrowings by business
# design rather than a leverage choice comparable to a manufacturer's. This
# is a deliberately small, explicit list -- not a general sector-ratio
# adjustment engine (V3 9.5).
_NON_FINANCIAL_LEVERAGE_RATIO_SUBSTRINGS = ("debt_to_equity", "interest_coverage")
_FINANCIAL_SECTORS = {"bank", "non_bank_financial"}


@dataclass(frozen=True)
class ReportVerificationSummary:
    total_material_claims: int
    supported_count: int
    unsupported_count: int
    unknown_count: int
    contradicted_count: int
    unresolved_critical_claim_ids: list[str] = field(default_factory=list)
    fully_verifiable: bool = False
    """CAVEAT (V3 Phase 10 audit finding): True means every critical claim's
    Fact passed evidence_ledger's layered checks, including source_support --
    but source_support today only proves a claim links to SOME real passage
    text, and `research_workflow.run_branch` links each Fact to the exact
    passage it was extracted from. So `fully_verifiable=True` proves internal
    consistency (the claim traces to a real, fetched document), NOT
    independent corroboration across multiple sources. Do not read this field
    as a factuality/quality score -- that would need either a second
    independent source per critical claim or a human/LLM factuality reviewer,
    neither of which exists in this pipeline yet."""


async def verify_report_claims(
    db: AsyncSession, fact_ids: list[str], *, critical_fact_ids: list[str] | None = None
) -> ReportVerificationSummary:
    """Calls evidence_ledger.verify_fact on every id in fact_ids, tallies
    final_status counts. `critical_fact_ids` (a subset of fact_ids, or None
    meaning "all facts are critical") identifies which claims are material
    enough that an unsupported/contradicted result must block publication
    (V3 9.4: 'Critical unresolved numeric claims are removed or shown as
    unknown'). unresolved_critical_claim_ids collects every critical fact_id
    whose final_status is 'unsupported' or 'contradicted' -- these are the
    ones a caller must strip from or mark unknown in the final report before
    publishing, never silently keep as if verified."""

    critical_set = set(critical_fact_ids) if critical_fact_ids is not None else set(fact_ids)

    supported = unsupported = unknown = contradicted = 0
    unresolved_critical: list[str] = []

    for fact_id in fact_ids:
        # evidence_ledger.verify_fact does `db.get(Fact, fact_id)`, whose
        # SQLAlchemy Uuid column type expects a real uuid.UUID (not a plain
        # str) to match the identity map -- this module's contract takes
        # fact_ids as `list[str]` (they're report-level references, not ORM
        # handles), so convert at the boundary.
        result = await verify_fact(db, uuid.UUID(str(fact_id)))
        status = result.final_status
        if status == "supported":
            supported += 1
        elif status == "unsupported":
            unsupported += 1
        elif status == "contradicted":
            contradicted += 1
        else:  # "unknown" (or any other value verify_fact might return)
            unknown += 1

        if fact_id in critical_set and status in ("unsupported", "contradicted"):
            unresolved_critical.append(fact_id)

    return ReportVerificationSummary(
        total_material_claims=len(fact_ids),
        supported_count=supported,
        unsupported_count=unsupported,
        unknown_count=unknown,
        contradicted_count=contradicted,
        unresolved_critical_claim_ids=unresolved_critical,
        fully_verifiable=len(unresolved_critical) == 0,
    )


def validate_period_alignment(claims: list["ClaimReference"], facts_by_id: dict[str, "Fact"]) -> list[str]:
    """V3 9.5: 'Fund comparison uses comparable categories, plan options,
    time windows and benchmarks.' For THIS task, implement a narrower,
    concrete check: given a list of financial_context claims, look up each
    one's underlying Fact.period, and return a list of warning strings for
    any pair of claims in the SAME report whose `period` strings differ.

    LIMITATION (stated openly, per task instructions): this is a simple
    string-equality-based check across the SET of periods present in the
    given claims -- it does not understand fiscal calendars, does not know
    that "FY2025-Q4" and "FY2026-Q1" might be adjacent or overlapping
    reporting windows for a company with a non-standard fiscal year, and
    does not attempt to reconcile different-but-comparable period
    conventions. It only flags "more than one distinct period string is
    present", leaving judgment about materiality to the caller/reader.
    """
    periods: dict[str, list[str]] = {}
    for claim in claims:
        fact = facts_by_id.get(claim.fact_id)
        period = getattr(fact, "period", None) if fact is not None else None
        if period is None:
            continue
        periods.setdefault(period, []).append(claim.fact_id)

    distinct_periods = sorted(periods.keys())
    if len(distinct_periods) <= 1:
        return []

    warnings: list[str] = []
    for i, period_a in enumerate(distinct_periods):
        for period_b in distinct_periods[i + 1 :]:
            warnings.append(
                f"period mismatch: claims {periods[period_a]} use period {period_a!r} "
                f"while claims {periods[period_b]} use period {period_b!r} -- "
                "comparing these side by side without flagging the period mismatch "
                "is the failure mode V3 9.5 warns against (string-equality check "
                "only, not a real fiscal-calendar reasoner)."
            )
    return warnings


def apply_sector_template(entity_sector: str, ratios: dict[str, float]) -> dict[str, float]:
    """V3 9.5: 'Sector templates prevent applying industrial debt ratios
    blindly to banks.' Implement a SMALL, explicit template: if
    entity_sector is "bank" or "non_bank_financial", REMOVE any ratio key
    whose name contains 'debt_to_equity' or 'interest_coverage' -- these are
    industrial-company capital-structure ratios that don't apply the same
    way to a bank/NBFC's balance sheet (deposits/borrowings are the business
    itself, not a comparable leverage choice). For any other sector, return
    `ratios` unchanged.

    This is a deliberately narrow, explicit rule -- not a general
    financial-ratio sector-adjustment engine.
    """
    if entity_sector not in _FINANCIAL_SECTORS:
        return ratios

    return {
        key: value
        for key, value in ratios.items()
        if not any(substr in key for substr in _NON_FINANCIAL_LEVERAGE_RATIO_SUBSTRINGS)
    }
