"""Synthetic product-catalogue fixtures (V3 Phase 03). NOT auto-run anywhere
-- tests and dev scripts call `seed_synthetic_catalogue()` explicitly.

Every entry here is clearly-labeled SYNTHETIC example data: obviously
fictional issuer/product names and identifiers, `is_synthetic=True`, and
`source_ids=["synthetic_fixture_v1"]`. No real reviewed financial product
data has been supplied to this project (docs/v3-execution/STATE.md records
this as an unresolved external input) -- never present these as real live
market terms, matching the convention in app/providers/demo_market_data.py /
demo_fundamentals.py."""

from datetime import date

from app.models.catalogue import ProductCatalogEntry
from app.utils.time import utcnow

_TODAY = date(2026, 9, 1)
_SYNTHETIC_SOURCE = ["synthetic_fixture_v1"]


def seed_synthetic_catalogue() -> list[ProductCatalogEntry]:
    """Builds ~6-8 example ProductCatalogEntry objects spanning different V3
    4.1 product families, including deliberately incomplete ones so
    resolve_support_level() has something real to downgrade. Callers are
    responsible for adding them to a session and committing."""

    entries = [
        # 1. direct_listed_equity, fully populated -> instrument_planning
        ProductCatalogEntry(
            external_ids={"isin": "SYN0000000001", "symbol": "EXAMPLECO"},
            parent_exposure_id="exposure_exampleco",
            product_type="direct_listed_equity",
            issuer_or_amc="Example Fictional Industries Ltd (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="instrument_planning",
            exposure_vector={"domestic_equity": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="market_price",
            valuation_date=_TODAY,
            eligible_contribution_methods=["lump_sum"],
            minimum_initial=1,
            minimum_additional=1,
            increment=1,
            quantity_granularity="whole_unit",
            settlement_delay_days=1,
            maturity_or_lock_rule=None,
            fee_assumptions={"brokerage_bps": 3},
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 2. equity_index_fund, fully populated -> instrument_planning
        ProductCatalogEntry(
            external_ids={"scheme_code": "SYNSCH0001", "plan": "direct_growth"},
            parent_exposure_id="exposure_example_nifty50_index",
            product_type="equity_index_fund",
            issuer_or_amc="Example Fictional Asset Managers (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="instrument_planning",
            exposure_vector={"domestic_equity": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="nav",
            valuation_date=_TODAY,
            eligible_contribution_methods=["lump_sum", "sip"],
            minimum_initial=500,
            minimum_additional=100,
            increment=1,
            quantity_granularity="fractional",
            settlement_delay_days=2,
            maturity_or_lock_rule=None,
            fee_assumptions={"expense_ratio": 0.002, "exit_load": None},
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 3. equity_index_fund, MISSING minimum_initial -> derived down to
        # category_planning even though stored column below claims otherwise.
        ProductCatalogEntry(
            external_ids={"scheme_code": "SYNSCH0002", "plan": "regular_growth"},
            parent_exposure_id="exposure_example_nifty50_index",
            product_type="equity_index_fund",
            issuer_or_amc="Example Fictional Asset Managers (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="instrument_planning",  # deliberately stale/wrong stored value
            exposure_vector={"domestic_equity": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="nav",
            valuation_date=_TODAY,
            eligible_contribution_methods=["lump_sum", "sip"],
            minimum_initial=None,  # missing critical term
            minimum_additional=None,
            increment=1,
            quantity_granularity="fractional",
            settlement_delay_days=2,
            maturity_or_lock_rule=None,
            fee_assumptions={"expense_ratio": 0.009, "exit_load": 0.01},
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 4. bank_fd, only issuer_or_amc/product_type/exposure_vector populated
        # -> resolves to category_planning per our rule (no valuation_method).
        ProductCatalogEntry(
            external_ids={},
            parent_exposure_id=None,
            product_type="bank_fd",
            issuer_or_amc="Example Fictional Bank (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="instrument_planning",  # deliberately stale/wrong stored value
            exposure_vector={"fixed_income": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="",  # unset -- valuation_method is non-nullable in the schema, "" means "not
            # actually known" and is treated as falsy/missing by resolve_support_level()
            valuation_date=None,
            eligible_contribution_methods=[],
            minimum_initial=None,
            minimum_additional=None,
            increment=None,
            quantity_granularity="",  # unset -- quantity_granularity is non-nullable in the schema, "" means "not
            # actually known" and is treated as falsy/missing by resolve_support_level()
            settlement_delay_days=None,
            maturity_or_lock_rule=None,
            fee_assumptions=None,
            eligibility_predicates=None,
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 5. hybrid_fund -- V3 4.1: "Hold existing positions; new selection in
        # V3.1". Stored support_level="holdings_only" intentionally. All
        # other fields are fully populated, but resolve_support_level's
        # _POLICY_CEILING now caps hybrid_fund at holdings_only regardless of
        # term completeness -- the derived and stored levels agree here.
        ProductCatalogEntry(
            external_ids={"scheme_code": "SYNSCH0003", "plan": "direct_growth"},
            parent_exposure_id="exposure_example_hybrid_balanced",
            product_type="hybrid_fund",
            issuer_or_amc="Example Fictional Asset Managers (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="holdings_only",  # policy cap per V3 4.1 -- see note above
            exposure_vector={"domestic_equity": 0.6, "fixed_income": 0.4},
            exposure_as_of=_TODAY,
            valuation_method="nav",
            valuation_date=_TODAY,
            eligible_contribution_methods=["lump_sum", "sip"],
            minimum_initial=1000,
            minimum_additional=500,
            increment=1,
            quantity_granularity="fractional",
            settlement_delay_days=3,
            maturity_or_lock_rule=None,
            fee_assumptions={"expense_ratio": 0.015, "exit_load": 0.01},
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 6. treasury_bill -- category-level info only (V3 4.1: "Category
        # comparison; verified instrument planning only when terms/prices
        # exist") -> category_planning.
        ProductCatalogEntry(
            external_ids={},
            parent_exposure_id=None,
            product_type="treasury_bill",
            issuer_or_amc="Government of India (SYNTHETIC category placeholder)",
            currency="INR",
            status="active",
            support_level="category_planning",
            exposure_vector={"fixed_income": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="issuer_quoted_rate",
            valuation_date=None,
            eligible_contribution_methods=["lump_sum"],
            minimum_initial=None,
            minimum_additional=None,
            increment=None,
            quantity_granularity="",  # unset -- quantity_granularity is non-nullable in the schema
            settlement_delay_days=None,
            maturity_or_lock_rule="91_182_364_day_tenures_category_level_only",
            fee_assumptions=None,
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
        # 7. equity_index_etf, fully populated -> instrument_planning (extra
        # family for coverage breadth).
        ProductCatalogEntry(
            external_ids={"isin": "SYN0000000002", "symbol": "EXAMPLEETF"},
            parent_exposure_id="exposure_example_nifty50_index",
            product_type="equity_index_etf",
            issuer_or_amc="Example Fictional Asset Managers (SYNTHETIC)",
            currency="INR",
            status="active",
            support_level="instrument_planning",
            exposure_vector={"domestic_equity": 1.0},
            exposure_as_of=_TODAY,
            valuation_method="market_price",
            valuation_date=_TODAY,
            eligible_contribution_methods=["lump_sum"],
            minimum_initial=1,
            minimum_additional=1,
            increment=1,
            quantity_granularity="whole_unit",
            settlement_delay_days=1,
            maturity_or_lock_rule=None,
            fee_assumptions={"expense_ratio": 0.0005},
            eligibility_predicates={"residency": "india_resident_individual"},
            source_ids=_SYNTHETIC_SOURCE,
            source_freshness=_TODAY,
            is_synthetic=True,
            created_at=utcnow(),
        ),
    ]
    return entries
