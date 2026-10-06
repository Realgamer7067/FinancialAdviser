"""Coverage for the Phase 03 product catalogue: resolve_support_level's
re-derivation rule, the seeded synthetic fixtures, and the /api/catalogue
routes' use of the derived (not stored) support level for filtering."""

from datetime import date


from app.models.catalogue import ProductCatalogEntry
from app.services.catalogue import resolve_support_level
from app.services.catalogue_fixtures import seed_synthetic_catalogue
from app.utils.time import utcnow

# Predicted resolved level for each fixture entry, in seed order (see
# app/services/catalogue_fixtures.py::seed_synthetic_catalogue). Derived from
# resolve_support_level's own rule, not asserted blindly:
#  1. direct_listed_equity, fully populated             -> instrument_planning
#  2. equity_index_fund, fully populated                -> instrument_planning
#  3. equity_index_fund, minimum_initial missing         -> category_planning
#  4. bank_fd, only type/issuer/exposure populated       -> category_planning
#     (valuation_method missing -> fails has_valuation_basis)
#  5. hybrid_fund, fully populated (stored=holdings_only) -> holdings_only
#     (V3 Phase 02 integration fix: _POLICY_CEILING caps hybrid_fund at
#     holdings_only regardless of term completeness, per V3 4.1's "Hold
#     existing positions; new selection in V3.1" -- terms completeness alone
#     used to let this resolve past the family's policy ceiling)
#  6. treasury_bill, category-level info only            -> category_planning
#  7. equity_index_etf, fully populated                  -> instrument_planning
_EXPECTED_RESOLVED_LEVELS = [
    "instrument_planning",
    "instrument_planning",
    "category_planning",
    "category_planning",
    "holdings_only",
    "category_planning",
    "instrument_planning",
]


def test_seeded_fixtures_resolve_to_expected_levels():
    entries = seed_synthetic_catalogue()
    assert len(entries) == len(_EXPECTED_RESOLVED_LEVELS)
    resolved = [resolve_support_level(e) for e in entries]
    assert resolved == _EXPECTED_RESOLVED_LEVELS


def test_seeded_fixtures_are_all_synthetic():
    entries = seed_synthetic_catalogue()
    for entry in entries:
        assert entry.is_synthetic is True
        assert entry.source_ids == ["synthetic_fixture_v1"]


def _fully_populated_entry(**overrides) -> ProductCatalogEntry:
    base = dict(
        external_ids={"isin": "SYNTEST0001"},
        parent_exposure_id=None,
        product_type="direct_listed_equity",
        issuer_or_amc="Example Fictional Co (SYNTHETIC)",
        currency="INR",
        status="active",
        support_level="instrument_planning",
        exposure_vector={"domestic_equity": 1.0},
        exposure_as_of=date(2026, 9, 1),
        valuation_method="market_price",
        valuation_date=date(2026, 9, 1),
        eligible_contribution_methods=["lump_sum"],
        minimum_initial=1,
        minimum_additional=1,
        increment=1,
        quantity_granularity="whole_unit",
        settlement_delay_days=1,
        maturity_or_lock_rule=None,
        fee_assumptions=None,
        eligibility_predicates=None,
        source_ids=["synthetic_fixture_v1"],
        source_freshness=date(2026, 9, 1),
        is_synthetic=True,
        created_at=utcnow(),
    )
    base.update(overrides)
    return ProductCatalogEntry(**base)


def test_fully_populated_entry_resolves_to_instrument_planning():
    entry = _fully_populated_entry()
    assert resolve_support_level(entry) == "instrument_planning"


def test_fully_populated_hybrid_fund_is_capped_at_holdings_only_by_policy():
    # V3 4.1: hybrid funds are existing-holdings-only in V3.0, new selection
    # deferred to V3.1 -- a fully-populated entry (every critical term
    # present) must NOT be promoted to instrument_planning just because the
    # data-completeness check alone would allow it. This is a policy
    # ceiling, not a data gap -- must hold even with zero missing terms.
    entry = _fully_populated_entry(product_type="hybrid_fund", support_level="holdings_only")
    assert resolve_support_level(entry) == "holdings_only"


def test_dropping_minimum_initial_demotes_to_category_planning():
    """Proves the re-derivation actually REACTS to the field changing, not
    just that a fixture happens to already be right."""
    entry = _fully_populated_entry()
    assert resolve_support_level(entry) == "instrument_planning"

    entry.minimum_initial = None
    assert resolve_support_level(entry) == "category_planning"


def test_missing_product_type_or_exposure_caps_at_education_only():
    entry = _fully_populated_entry(product_type="", exposure_vector={})
    assert resolve_support_level(entry) == "education_only"


async def test_api_lists_only_active_synthetic_entries_with_flag_visible(db_session, client):
    for entry in seed_synthetic_catalogue():
        db_session.add(entry)
    await db_session.commit()

    resp = await client.get("/api/catalogue")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 7
    for item in body:
        assert item["is_synthetic"] is True


async def test_api_filters_on_resolved_level_not_stored_column(db_session, client):
    # Stored support_level claims instrument_planning, but minimum_initial is
    # missing -- the derived level should be category_planning, and the
    # instrument_planning filter must NOT return this entry.
    misleading = _fully_populated_entry(
        external_ids={"isin": "SYNTEST0002"},
        minimum_initial=None,
        support_level="instrument_planning",
    )
    genuine = _fully_populated_entry(external_ids={"isin": "SYNTEST0003"})
    db_session.add(misleading)
    db_session.add(genuine)
    await db_session.commit()
    await db_session.refresh(misleading)
    await db_session.refresh(genuine)

    resp = await client.get("/api/catalogue", params={"support_level": "instrument_planning"})
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body}
    assert str(genuine.id) in ids
    assert str(misleading.id) not in ids

    resp2 = await client.get("/api/catalogue", params={"support_level": "category_planning"})
    ids2 = {item["id"] for item in resp2.json()}
    assert str(misleading.id) in ids2
    assert str(genuine.id) not in ids2


async def test_api_get_single_entry_shows_synthetic_flag_and_resolved_level(db_session, client):
    entry = _fully_populated_entry(external_ids={"isin": "SYNTEST0004"}, minimum_initial=None)
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    resp = await client.get(f"/api/catalogue/{entry.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_synthetic"] is True
    assert body["resolved_support_level"] == "category_planning"
    assert body["support_level"] == "instrument_planning"  # stale stored value, kept visible
