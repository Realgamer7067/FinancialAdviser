"""Unit tests for the pure SIP compound-growth math in
app/services/financial_planning.py -- no DB, no HTTP."""

from app.services.financial_planning import required_monthly_sip, sip_future_value


def test_sip_future_value_known_case():
    # 12%/yr = 1%/mo, monthly=1000, 1 year: FV = 1000 * ((1.01^12 - 1)/0.01)
    points = sip_future_value(1000, 12, 1)
    assert len(points) == 1
    point = points[0]
    assert point["year"] == 1
    assert point["invested_cumulative"] == 12000.0
    assert point["projected_value"] == round(1000 * (((1.01**12) - 1) / 0.01), 2)
    assert point["projected_value"] > point["invested_cumulative"]


def test_sip_future_value_zero_rate_is_linear():
    points = sip_future_value(500, 0, 3)
    assert [p["year"] for p in points] == [1, 2, 3]
    for p in points:
        assert p["projected_value"] == p["invested_cumulative"] == 500 * p["year"] * 12


def test_sip_future_value_series_is_monotonic():
    points = sip_future_value(2000, 10, 5)
    values = [p["projected_value"] for p in points]
    assert values == sorted(values)


def test_required_monthly_sip_zero_rate():
    assert required_monthly_sip(120000, 0, 10) == round(120000 / 120, 2)


def test_required_monthly_sip_round_trips_with_future_value():
    target = 1_000_000.0
    rate = 11.0
    years = 10
    monthly = required_monthly_sip(target, rate, years)
    projected = sip_future_value(monthly, rate, years)[-1]["projected_value"]
    assert abs(projected - target) < 1.0  # rounding tolerance only
