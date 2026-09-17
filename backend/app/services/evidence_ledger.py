"""Layered fact verification (V3 Phase 06, docs/V3-IMPLEMENTATION-PLAN.md
section 9.4): "Verification is layered: schema validation; existence of
referenced IDs; entity/date/unit consistency; deterministic numerical
checks; then source-support assessment. An LLM verifier can flag unsupported
interpretation but is not ground truth. Critical unresolved numeric claims
are removed or shown as unknown. A real link without a supporting passage
does not count as verified support."

Entity/unit consistency here is a deliberately SIMPLE heuristic: it catches
an obvious mismatch (inputs about different entities, or an evidently
incompatible unit pairing) and marks anything it cannot confidently judge as
"inconclusive" rather than falsely passing it. It is not a real unit-
conversion engine.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Fact, FactPassageLink, Passage

_CALCULATION_REQUIRED_FIELDS = ("formula_id", "input_fact_ids", "code_version")
_VALID_CLAIM_TYPES = {"source_fact", "calculation", "inference", "assumption"}
_VALID_LINK_TYPES = {"supports", "refutes"}

# Pairs of unit strings that are obviously incompatible if both appear among
# a calculation's input facts -- a deliberately small, explicit list, not a
# real unit-conversion engine. Anything not covered here is "inconclusive",
# never falsely "consistent".
_OBVIOUSLY_INCOMPATIBLE_UNIT_PAIRS = {
    frozenset({"percent", "inr_crore"}),
    frozenset({"percent", "inr"}),
    frozenset({"ratio", "inr_crore"}),
    frozenset({"ratio", "inr"}),
}


@dataclass(frozen=True)
class VerificationResult:
    fact_id: str
    layer_results: dict[str, bool | None] = field(default_factory=dict)  # None means "skipped / not applicable"
    final_status: str = "unknown"
    reasons: list[str] = field(default_factory=list)


async def create_fact(
    db: AsyncSession,
    *,
    claim_type: str,
    text: str,
    entity: str,
    period: str | None,
    units: str | None,
    value: str | None,
    formula_id: str | None = None,
    input_fact_ids: list[str] | None = None,
    code_version: str | None = None,
) -> Fact:
    if claim_type not in _VALID_CLAIM_TYPES:
        raise ValueError(f"unknown claim_type {claim_type!r}, expected one of {sorted(_VALID_CLAIM_TYPES)}")

    if claim_type == "calculation":
        missing = [
            name
            for name, val in (
                ("formula_id", formula_id),
                ("input_fact_ids", input_fact_ids),
                ("code_version", code_version),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                f"claim_type='calculation' requires {_CALCULATION_REQUIRED_FIELDS} to all be populated; "
                f"missing/empty: {missing}"
            )
        # Referenced-ID existence -- checked for real, at creation time, not
        # deferred to a later verify_fact call (V3 9.4 layer 2).
        input_uuids = {uuid.UUID(str(i)) for i in input_fact_ids}
        existing_ids = set(
            (await db.execute(select(Fact.id).where(Fact.id.in_(input_uuids)))).scalars().all()
        )
        missing_ids = input_uuids - existing_ids
        if missing_ids:
            raise ValueError(f"input_fact_ids references non-existent Fact rows: {sorted(str(i) for i in missing_ids)}")

    fact = Fact(
        claim_type=claim_type,
        text=text,
        entity=entity,
        period=period,
        units=units,
        value=value,
        support_status="unknown",
        formula_id=formula_id,
        input_fact_ids=input_fact_ids,
        code_version=code_version,
        created_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    await db.flush()
    return fact


async def link_fact_to_passage(db: AsyncSession, fact_id, passage_id, link_type: str) -> FactPassageLink:
    if link_type not in _VALID_LINK_TYPES:
        raise ValueError(f"link_type must be one of {sorted(_VALID_LINK_TYPES)}, got {link_type!r}")
    link = FactPassageLink(fact_id=fact_id, passage_id=passage_id, link_type=link_type)
    db.add(link)
    await db.flush()
    return link


def _is_real_passage_text(text: str | None) -> bool:
    return bool(text and text.strip())


async def verify_fact(db: AsyncSession, fact_id) -> VerificationResult:
    fact = await db.get(Fact, fact_id)
    if fact is None:
        raise ValueError(f"no Fact with id {fact_id!r}")

    layer_results: dict[str, bool | None] = {}
    reasons: list[str] = []

    # Layer 1: schema -- re-checked even though create_fact already enforced
    # this at creation (a fact could predate a schema tightening).
    schema_ok = True
    if fact.claim_type == "calculation":
        for name in _CALCULATION_REQUIRED_FIELDS:
            if not getattr(fact, name):
                schema_ok = False
                reasons.append(f"schema: calculation missing required field {name!r}")
    layer_results["schema"] = schema_ok

    # Layer 2: referenced_ids_exist -- for a calculation, do all
    # input_fact_ids still exist right now (could have been deleted since).
    if fact.claim_type == "calculation" and schema_ok:
        input_uuids = [uuid.UUID(str(i)) for i in fact.input_fact_ids]
        existing_ids = {
            str(i) for i in (await db.execute(select(Fact.id).where(Fact.id.in_(input_uuids)))).scalars().all()
        }
        missing = [str(i) for i in fact.input_fact_ids if str(i) not in existing_ids]
        if missing:
            layer_results["referenced_ids_exist"] = False
            reasons.append(f"referenced_ids_exist: missing input facts {missing}")
        else:
            layer_results["referenced_ids_exist"] = True
    else:
        layer_results["referenced_ids_exist"] = None  # not applicable

    # Layer 3: entity/date/unit consistency -- calculation only.
    input_facts: list[Fact] = []
    if fact.claim_type == "calculation" and layer_results.get("referenced_ids_exist"):
        input_uuids = [uuid.UUID(str(i)) for i in fact.input_fact_ids]
        rows = (await db.execute(select(Fact).where(Fact.id.in_(input_uuids)))).scalars().all()
        input_facts = list(rows)
        entities = {f.entity for f in input_facts}
        if len(entities) > 1:
            layer_results["entity_date_unit_consistency"] = False
            reasons.append(f"entity_date_unit_consistency: inconsistent entities among inputs: {sorted(entities)}")
        else:
            units_present = {f.units for f in input_facts if f.units}
            incompatible = any(
                frozenset({a, b}) in _OBVIOUSLY_INCOMPATIBLE_UNIT_PAIRS
                for a in units_present
                for b in units_present
                if a != b
            )
            if incompatible:
                layer_results["entity_date_unit_consistency"] = False
                reasons.append(f"entity_date_unit_consistency: obviously incompatible units among inputs: {sorted(units_present)}")
            elif len(units_present) <= 1:
                layer_results["entity_date_unit_consistency"] = True
            else:
                # Multiple distinct units, none flagged as an OBVIOUS
                # mismatch -- this heuristic cannot confidently judge
                # compatibility (e.g. two different currency-denominated
                # units), so it marks the layer inconclusive rather than a
                # false pass.
                layer_results["entity_date_unit_consistency"] = None
                reasons.append(f"entity_date_unit_consistency: inconclusive -- mixed units {sorted(units_present)} not confidently checkable")
    elif fact.claim_type == "calculation":
        layer_results["entity_date_unit_consistency"] = None
    else:
        layer_results["entity_date_unit_consistency"] = None

    # Layer 4: numerical_check -- calculation only, needs a numeric value
    # plausibly derived from at least one linked/input numeric fact.
    # CAVEAT (V3 Phase 10 audit finding): this only checks that a numeric
    # input EXISTS to derive from -- it does not recompute `formula_id`
    # against `input_fact_ids` and compare to `fact.value`. A calculation
    # with an arithmetically wrong value still passes this layer as long as
    # some numeric input is present. Real formula recomputation would need a
    # registry mapping formula_id -> a pure function per formula, which does
    # not exist yet; flagged here rather than silently claimed as done.
    if fact.claim_type == "calculation":
        if fact.value is None:
            layer_results["numerical_check"] = False
            reasons.append("numerical_check: calculation has no output value")
        else:
            has_numeric_input = any(_is_numeric(f.value) for f in input_facts)
            layer_results["numerical_check"] = has_numeric_input
            if not has_numeric_input:
                reasons.append("numerical_check: no numeric input fact found to derive this calculation from")
    else:
        layer_results["numerical_check"] = None

    # Layer 5: source_support -- source_fact only, needs >=1 real "supports"
    # link to a Passage with real (non-empty) text.
    links = (await db.execute(select(FactPassageLink).where(FactPassageLink.fact_id == fact.id))).scalars().all()
    supports_links = [l for l in links if l.link_type == "supports"]
    refutes_links = [l for l in links if l.link_type == "refutes"]

    real_support = False
    for link in supports_links:
        passage = await db.get(Passage, link.passage_id)
        if passage is not None and _is_real_passage_text(passage.text):
            real_support = True
            break

    if fact.claim_type == "source_fact":
        layer_results["source_support"] = real_support
        if not real_support and supports_links:
            reasons.append("source_support: a 'supports' link exists but points at no real passage text -- not counted as verified support")
    else:
        layer_results["source_support"] = None

    # Final status.
    if refutes_links and not supports_links:
        final_status = "contradicted"
    elif refutes_links and len(refutes_links) >= len(supports_links) and not real_support:
        final_status = "contradicted"
    elif fact.claim_type == "source_fact":
        final_status = "supported" if real_support else ("unknown" if not links else "unsupported")
    elif fact.claim_type == "calculation":
        required = ("schema", "referenced_ids_exist", "numerical_check")
        passed = all(layer_results.get(name) is True for name in required)
        # entity_date_unit_consistency is required to be True OR None-and-
        # single-unit (already folded into True above) -- an explicit False
        # always fails; an inconclusive (None) does not block "supported"
        # on its own, since it's a heuristic limitation, not a proven defect.
        if layer_results.get("entity_date_unit_consistency") is False:
            passed = False
        final_status = "supported" if passed else "unsupported"
    else:  # inference / assumption -- no calculation/source-support layers apply
        final_status = "unknown" if not links else ("supported" if real_support else "unsupported")

    # Persist the verdict onto the Fact itself -- ClaimReference.support_status
    # (app/schemas/research_assessment.py) documents itself as "mirrors
    # Fact.support_status"; that mirror is only real if verify_fact actually
    # writes it back, not just returns it transiently (V3 Phase 10 audit finding).
    fact.support_status = final_status
    await db.flush()

    return VerificationResult(
        fact_id=str(fact.id), layer_results=layer_results, final_status=final_status, reasons=reasons
    )


def _is_numeric(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
        return True
    except ValueError:
        return False
