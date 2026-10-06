"""Angel holdings normalization and reconciliation."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.portfolio_intelligence.sources.angel.errors import BadResponse
from app.portfolio_intelligence.sources.angel.holdings import parse_holdings
from tests.angel_fixtures import TCS_ISIN, holding, holdings_payload

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)


def parse(payload):
    return parse_holdings(payload["data"], NOW)


def test_clean_import_is_complete_and_reconciles():
    p = parse(holdings_payload())
    assert p.status == "complete" and len(p.rows) == 1
    r = p.rows[0]
    assert r.units == Decimal("10") and r.value == Decimal("25002.50") and r.cost_basis is None
    assert p.reconciliation["material_gap"] is False and p.reconciliation["abs_diff"] == "0.00"
    assert p.metas[0]["provider_averageprice"] == "2000.5"  # kept verbatim, not turned into cost basis


def test_valid_empty_vs_missing_list():
    empty = parse(holdings_payload(rows=[], total=0))
    assert empty.status == "complete" and empty.rows == []
    with pytest.raises(BadResponse):
        parse_holdings({"totalholding": {}}, NOW)
    with pytest.raises(BadResponse):
        parse_holdings({"holdings": None}, NOW)


def test_t1_is_not_added_to_units():
    p = parse(holdings_payload([holding(quantity=10, t1quantity=4)], total=25002.5))
    assert p.rows[0].units == Decimal("10")
    assert p.metas[0]["t1quantity"] == "4" and p.metas[0]["t1_semantics_unverified"] is True


def test_malformed_row_quarantined_makes_partial():
    rows = [holding(), holding(quantity=0, tradingsymbol="BAD"), holding(isin="INE002A01019"), "junk"]
    p = parse(holdings_payload(rows, total=25002.5))
    assert p.status == "partial" and len(p.rows) == 1
    assert [q["ordinal"] for q in p.quarantined] == [2, 3, 4]


def test_material_reconciliation_gap_is_partial_not_balanced():
    p = parse(holdings_payload([holding()], total=30000))
    assert p.status == "partial" and p.reconciliation["material_gap"] is True
    assert len(p.rows) == 1  # no balancing row invented


def test_missing_aggregate_not_reconciled():
    p = parse(holdings_payload(total=None))
    assert p.status == "complete" and "not reconciled" in p.reconciliation["note"]


def test_missing_ltp_leaves_value_unknown():
    r = holding()
    del r["ltp"]
    p = parse(holdings_payload([r], total=None))
    assert p.rows[0].value is None


def test_same_isin_two_products_both_kept():
    p = parse(holdings_payload([holding(), holding(product="MTF", quantity=5)], total=None))
    assert len(p.rows) == 2


def test_isin_optional_row_kept():
    p = parse(holdings_payload([holding(isin=None, tradingsymbol="X-EQ")], total=None))
    assert p.rows[0].isin is None and p.rows[0].symbol == "X-EQ"
