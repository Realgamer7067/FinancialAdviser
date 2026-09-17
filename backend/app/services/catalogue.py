"""Support-level gate for the product catalogue (V3 Phase 03,
docs/V3-IMPLEMENTATION-PLAN.md section 4.2). See
app/models/catalogue.py::ProductCatalogEntry for the table this operates on."""

from app.models.catalogue import ProductCatalogEntry

# Product families whose terms are contractually fixed at issuance rather than
# priced by an ongoing market -- V3 4.1 lists these as "manual dated issuer
# terms" / locked-account products, so they can qualify for instrument
# planning without a `valuation_date` the way a market-priced instrument
# (equity, a fund's NAV date, an ETF's trade price) needs one.
_CONTRACTUAL_TERMS_PRODUCT_TYPES = {"bank_fd", "bank_rd", "locked_account"}

_LEVELS = ("education_only", "holdings_only", "category_planning", "instrument_planning")
_LEVEL_RANK = {level: i for i, level in enumerate(_LEVELS)}

# V3 section 4.1's per-product-family V3.0 treatment table caps some families
# below what their populated terms alone would otherwise justify -- this is a
# POLICY decision (a product scope boundary), not a data-completeness gate,
# and must never be bypassed just because an entry happens to have every
# field filled in. Found as a real gap during Phase 03 integration: the
# terms-completeness check below could resolve a fully-populated hybrid_fund
# entry to `instrument_planning`, contradicting V3 4.1's explicit "Hold
# existing positions; new selection in V3.1" scope for that family.
_POLICY_CEILING: dict[str, str] = {
    "hybrid_fund": "holdings_only",  # V3 4.1: existing positions only in V3.0, new selection deferred to V3.1
}


def resolve_support_level(entry: ProductCatalogEntry) -> str:
    """Independently RE-DERIVES what support level an entry actually
    qualifies for, from its own populated fields, rather than trusting the
    stored `support_level` column blindly. Per V3 4.2: 'Missing critical
    terms prevents promotion to instrument planning.' Critical terms for
    instrument_planning: valuation_method AND (valuation_date is not None
    OR product_type in a set of terms-are-contractual-not-market-priced
    types like bank_fd/bank_rd/locked_account) AND minimum_initial is not
    None AND quantity_granularity is not None AND at least one
    eligible_contribution_method. Missing any of those caps the entry at
    'category_planning' regardless of what its stored support_level column
    says. If even exposure_vector or product_type is missing/empty, cap at
    'education_only'.

    A SEPARATE, independent cap applies on top: `_POLICY_CEILING` caps
    specific product families at a maximum level regardless of term
    completeness (V3 4.1's per-family V3.0 scope decisions, e.g. hybrid_fund
    -> holdings_only). The final result is the MINIMUM of the terms-derived
    level and any applicable policy ceiling -- terms completeness can never
    promote an entry past its family's policy ceiling, and a policy ceiling
    never demands MORE terms than the data-completeness check already
    requires (it only ever lowers the result).

    This function's return value is the SOURCE OF TRUTH a caller should use
    for gating -- treat the stored column as a cached hint that can be
    stale, not authoritative.
    """
    if not entry.product_type or not entry.exposure_vector:
        return "education_only"

    has_valuation_basis = bool(entry.valuation_method) and (
        entry.valuation_date is not None or entry.product_type in _CONTRACTUAL_TERMS_PRODUCT_TYPES
    )
    has_minimum_initial = entry.minimum_initial is not None
    has_quantity_granularity = bool(entry.quantity_granularity)
    has_contribution_method = bool(entry.eligible_contribution_methods)

    terms_level = (
        "instrument_planning"
        if (has_valuation_basis and has_minimum_initial and has_quantity_granularity and has_contribution_method)
        else "category_planning"
    )

    ceiling = _POLICY_CEILING.get(entry.product_type)
    if ceiling is not None and _LEVEL_RANK[ceiling] < _LEVEL_RANK[terms_level]:
        return ceiling
    return terms_level
