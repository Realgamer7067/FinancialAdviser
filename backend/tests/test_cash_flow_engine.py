"""V3 Phase 05 cash-flow engine (docs/V3-IMPLEMENTATION-PLAN.md section 7).
Coordinator-written verification pass -- the original cash-flow worker's own
test file was lost when its session hit a rate limit mid-task; this covers
the required edge cases from section 7.4 against the module as it landed on
disk, checked by direct code review before writing these tests."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.cash_flow_engine import (
    AssumptionProvenance,
    CashFlowEvent,
    ContributionTiming,
    ProjectionAssumption,
    RateBasis,
    back_solve_required_contribution,
    monthly_rate,
    project_fixed_contribution,
    project_with_events,
)

_D0 = Decimal("0")


def _assumption(rate="0.12", basis=RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING, inflation=None):
    return ProjectionAssumption(
        annual_rate=Decimal(rate),
        rate_basis=basis,
        provenance=AssumptionProvenance.USER_SCENARIO,
        inflation_rate=Decimal(inflation) if inflation is not None else None,
    )


def _conserved(result):
    """Every entry's balance identity, and the cumulative identity, must hold."""
    balance = result.ledger[0].balance_before if result.ledger else None
    for entry in result.ledger:
        assert entry.balance_after == entry.balance_before + entry.contribution + entry.growth - entry.fees
    if result.ledger:
        initial = result.ledger[0].balance_before
        assert (
            initial + result.cumulative_contributions + result.cumulative_growth - result.cumulative_fees
            == result.nominal_final_value
        )


def test_zero_return():
    result = project_fixed_contribution(Decimal("1000"), Decimal("100"), 12, _assumption("0.0"))
    assert result.nominal_final_value == Decimal("1000") + Decimal("100") * 12
    _conserved(result)


def test_zero_future_budget():
    result = project_fixed_contribution(Decimal("1000"), Decimal("0"), 12, _assumption("0.12"))
    assert result.cumulative_contributions == _D0
    assert result.nominal_final_value > Decimal("1000")  # still grows
    _conserved(result)


def test_negative_but_not_below_100_percent_effective_annual():
    result = project_fixed_contribution(
        Decimal("1000"), Decimal("0"), 12, _assumption("-0.30", basis=RateBasis.EFFECTIVE_ANNUAL)
    )
    assert result.nominal_final_value < Decimal("1000")
    _conserved(result)


def test_effective_annual_at_or_below_negative_100_percent_rejected():
    with pytest.raises(ValueError):
        monthly_rate(_assumption("-1.0", basis=RateBasis.EFFECTIVE_ANNUAL))
    with pytest.raises(ValueError):
        monthly_rate(_assumption("-1.5", basis=RateBasis.EFFECTIVE_ANNUAL))


def test_non_finite_rate_rejected():
    bad = ProjectionAssumption(
        annual_rate=Decimal("NaN"), rate_basis=RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING,
        provenance=AssumptionProvenance.USER_SCENARIO,
    )
    with pytest.raises(ValueError):
        monthly_rate(bad)


def test_target_already_funded_gap_is_zero():
    result = project_fixed_contribution(
        Decimal("1000000"), Decimal("0"), 12, _assumption("0.12"), target_amount=Decimal("500000")
    )
    assert result.gap_to_target == _D0


def test_partial_year():
    result = project_fixed_contribution(Decimal("0"), Decimal("1000"), 7, _assumption("0.12"))
    assert len(result.ledger) == 7
    _conserved(result)


def test_beginning_vs_end_of_month_beginning_is_at_least_as_much():
    end = project_fixed_contribution(
        Decimal("0"), Decimal("1000"), 12, _assumption("0.12"), timing=ContributionTiming.END_OF_MONTH
    )
    beginning = project_fixed_contribution(
        Decimal("0"), Decimal("1000"), 12, _assumption("0.12"), timing=ContributionTiming.BEGINNING_OF_MONTH
    )
    assert beginning.nominal_final_value > end.nominal_final_value


def test_fees_consuming_residual_budget():
    result = project_fixed_contribution(
        Decimal("0"), Decimal("1000"), 12, _assumption("0.01"), monthly_fee_rate=Decimal("0.02")
    )
    _conserved(result)
    assert result.cumulative_fees > _D0


def test_skipped_contribution_event():
    events = [CashFlowEvent(event_date=date(2026, 3, 1), event_type="skip", amount=_D0, note="skip march")]
    result = project_with_events(
        Decimal("0"), Decimal("1000"), 6, _assumption("0.12"), events, start_date=date(2026, 1, 1)
    )
    skipped = [e for e in result.ledger if e.contribution == _D0]
    assert len(skipped) == 1
    _conserved(result)


def test_withdrawal_before_maturity():
    events = [CashFlowEvent(event_date=date(2026, 4, 1), event_type="withdrawal", amount=Decimal("500"), note="early withdrawal")]
    result = project_with_events(
        Decimal("2000"), Decimal("0"), 6, _assumption("0.06"), events, start_date=date(2026, 1, 1)
    )
    _conserved(result)
    assert any(e.contribution == Decimal("-500") for e in result.ledger)


def test_leap_year_calendar_stepping():
    result = project_fixed_contribution(
        Decimal("0"), Decimal("100"), 3, _assumption("0.0"), start_date=date(2028, 1, 31)
    )
    # Jan 31 2028 (leap year) + 1 month must clamp to Feb 29, not overflow.
    assert result.ledger[0].as_of_date == date(2028, 2, 29)


def test_back_solve_never_negative_when_overfunded():
    contribution = back_solve_required_contribution(
        Decimal("10000000"), 12, _assumption("0.12"), Decimal("1")
    )
    assert contribution == _D0


def test_back_solve_matches_forward_projection():
    assumption = _assumption("0.10")
    target = Decimal("50000")
    required = back_solve_required_contribution(Decimal("0"), 24, assumption, target)
    forward = project_fixed_contribution(Decimal("0"), required, 24, assumption)
    assert abs(forward.nominal_final_value - target) < Decimal("0.01")


def test_back_solve_matches_forward_projection_nonzero_initial_effective_annual():
    """Round-trip check the existing back-solve test doesn't cover: nonzero
    initial balance AND EFFECTIVE_ANNUAL rate basis (not just zero-initial /
    nominal-monthly). Solving for a contribution then projecting it forward
    must reproduce the target within rounding tolerance -- audit item 3."""
    assumption = _assumption("0.08", basis=RateBasis.EFFECTIVE_ANNUAL)
    initial = Decimal("25000")
    target = Decimal("300000")
    months = 36

    required = back_solve_required_contribution(initial, months, assumption, target)
    assert required > _D0  # sanity: this case must not already be funded by initial alone

    forward = project_fixed_contribution(initial, required, months, assumption)
    assert abs(forward.nominal_final_value - target) < Decimal("0.01")

    # NOTE: not using the strict `_conserved()` helper here. Under
    # EFFECTIVE_ANNUAL basis, monthly_rate() involves a fractional Decimal
    # exponent ((1+R)**(1/12)), which under the default 28-significant-digit
    # Decimal context produces balances with ~29-30 significant digits after
    # a few months of compounding. Re-summing balance_before + contribution +
    # growth - fees in a DIFFERENT operand order than the module's own
    # balance_before + growth + contribution - fees then rounds differently
    # at the 28th significant digit, producing a ~1e-23 discrepancy -- far
    # below any paisa (0.01) significance, but it means the module's
    # documented "exact" per-entry identity is only exact up to Decimal
    # context precision, not bit-exact under every summation order. Verified
    # by hand here with a tolerance appropriate to that precision limit
    # instead of asserting strict equality.
    for entry in forward.ledger:
        reconstructed = entry.balance_before + entry.contribution + entry.growth - entry.fees
        assert abs(entry.balance_after - reconstructed) < Decimal("1E-15")


def test_today_money_target_inflates_before_gap():
    assumption = _assumption("0.10", inflation="0.06")
    result = project_fixed_contribution(
        Decimal("0"), Decimal("100"), 12, assumption, target_amount=Decimal("10000"), target_basis="today_money"
    )
    # Inflated target > nominal target; nominal_final_value (~1256) falls well
    # short of it, so a real gap must be reported (not zero).
    assert result.gap_to_target is not None and result.gap_to_target > _D0

    future_money_result = project_fixed_contribution(
        Decimal("0"), Decimal("100"), 12, assumption, target_amount=Decimal("10000"), target_basis="future_money"
    )
    # Inflating the target must make the gap strictly larger than treating
    # the same numeric target as already future-money (never inflated twice).
    assert result.gap_to_target > future_money_result.gap_to_target


def test_legacy_nominal_convention_matches_financial_planning_module():
    """Cross-check against the existing, untouched financial_planning.py::
    sip_future_value -- this new module's NOMINAL_ANNUAL_MONTHLY_COMPOUNDING
    basis (r = R/12) must agree with the legacy service's ordinary-annuity,
    end-of-month convention for equivalent inputs."""
    from app.services.financial_planning import sip_future_value

    annual_rate_pct = 12.0
    years = 5
    monthly_contribution = Decimal("5000")

    new_result = project_fixed_contribution(
        Decimal("0"), monthly_contribution, years * 12,
        _assumption(str(annual_rate_pct / 100)),
        timing=ContributionTiming.END_OF_MONTH,
    )

    legacy_points = sip_future_value(float(monthly_contribution), annual_rate_pct, years)
    legacy_final_value = legacy_points[-1]["projected_value"]

    assert abs(float(new_result.nominal_final_value) - legacy_final_value) < 1.0
