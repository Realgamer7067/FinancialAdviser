"""V3 Phase 05 -- capacity/suitability worker tests.

Covers: deployable-cash formula correctness, the income-unknown/
confirmed-surplus escape hatch, reserve-shortfall forcing the most
conservative scenario regardless of horizon, the near-term-horizon
override, structural proof that risk-tolerance is not a parameter
`resolve_scenario` can even accept, and that allocation_policy.yaml itself
loads and is honestly labelled synthetic.
"""

import inspect
from decimal import Decimal

from app.core.config import allocation_policy_config
from app.services.capacity_policy import (
    NEAR_TERM_HORIZON_YEARS,
    compute_capacity,
    resolve_scenario,
)


def test_income_known_adequate_reserve_and_surplus():
    result = compute_capacity(
        monthly_income=Decimal("100000"),
        essential_expenses=Decimal("40000"),
        debt_payments=Decimal("10000"),
        existing_commitments_total=Decimal("5000"),
        one_time_investable_cash=Decimal("500000"),
        liquidity_reserve_target_months=Decimal("6"),
        liquidity_reserve_current=Decimal("300000"),
    )
    # monthly_surplus = 100000 - 40000 - 10000 - 5000 = 45000 (>0, no rule)
    # reserve_target = 40000 * 6 = 240000; current 300000 >= target -> shortfall 0
    # deployable_cash = max(0, 500000 - 0) = 500000
    assert result.emergency_reserve_shortfall == Decimal("0")
    assert result.deployable_cash == Decimal("500000")
    assert result.binding_rules == []


def test_income_unknown_but_surplus_confirmed():
    result = compute_capacity(
        monthly_income=None,
        essential_expenses=Decimal("40000"),
        debt_payments=Decimal("0"),
        existing_commitments_total=Decimal("0"),
        one_time_investable_cash=Decimal("200000"),
        liquidity_reserve_target_months=Decimal("6"),
        liquidity_reserve_current=Decimal("240000"),
        monthly_surplus_confirmed=Decimal("15000"),
    )
    assert "income_unknown_using_confirmed_surplus" in result.binding_rules
    # reserve_target = 240000, current 240000 -> shortfall 0
    assert result.emergency_reserve_shortfall == Decimal("0")
    # capacity still computed from confirmed surplus path, not blocked outright
    assert result.deployable_cash == Decimal("200000")


def test_emergency_reserve_shortfall_forces_conservative_scenario_over_growth_horizon():
    policy = allocation_policy_config()
    capacity = compute_capacity(
        monthly_income=Decimal("150000"),
        essential_expenses=Decimal("50000"),
        debt_payments=Decimal("0"),
        existing_commitments_total=Decimal("0"),
        one_time_investable_cash=Decimal("300000"),
        liquidity_reserve_target_months=Decimal("6"),
        liquidity_reserve_current=Decimal("50000"),  # target = 300000, shortfall = 250000
    )
    assert capacity.emergency_reserve_shortfall == Decimal("250000")
    assert "emergency_reserve_below_target" in capacity.binding_rules

    # goal_horizon_years=15 alone would pick the "growth" scenario by band,
    # but the reserve shortfall must force the most conservative one instead.
    result = resolve_scenario(policy, goal_horizon_years=Decimal("15"), capacity=capacity)
    assert result.eligible is True
    assert result.scenario_id == "conservative_capacity_short_horizon"
    assert "near_term_goal_forces_conservative_scenario" in result.binding_rules


def test_near_term_goal_forces_conservative_regardless_of_hypothetical_risk_tolerance():
    # No risk-tolerance parameter is passed anywhere here -- resolve_scenario's
    # signature has none. Horizon/capacity alone determine the outcome, even
    # for a horizon this short where the band alone would already agree; the
    # load-bearing proof of the override mechanism is the reserve-shortfall
    # test above (long horizon overridden by capacity), this test just
    # confirms the near-term threshold path also fires and is named.
    policy = allocation_policy_config()
    capacity = compute_capacity(
        monthly_income=Decimal("150000"),
        essential_expenses=Decimal("50000"),
        debt_payments=Decimal("0"),
        existing_commitments_total=Decimal("0"),
        one_time_investable_cash=Decimal("300000"),
        liquidity_reserve_target_months=Decimal("6"),
        liquidity_reserve_current=Decimal("300000"),  # adequate reserve, no shortfall
    )
    assert capacity.emergency_reserve_shortfall == Decimal("0")

    result = resolve_scenario(
        policy, goal_horizon_years=NEAR_TERM_HORIZON_YEARS - Decimal("1"), capacity=capacity
    )
    assert result.scenario_id == "conservative_capacity_short_horizon"
    assert "near_term_goal_forces_conservative_scenario" in result.binding_rules

    # sanity: a comfortably long horizon with no shortfall picks the growth
    # scenario, proving the override is conditional, not always-on.
    result_growth = resolve_scenario(policy, goal_horizon_years=Decimal("15"), capacity=capacity)
    assert result_growth.scenario_id == "growth_capacity_long_horizon"
    assert "near_term_goal_forces_conservative_scenario" not in result_growth.binding_rules


def test_resolve_scenario_signature_has_no_risk_tolerance_parameter():
    # Machine-checked structural proof of the V3 15.1 separation claim:
    # resolve_scenario cannot read a risk-tolerance questionnaire score
    # because its signature has no such parameter at all.
    params = set(inspect.signature(resolve_scenario).parameters)
    for name in params:
        lowered = name.lower()
        assert "risk_tolerance" not in lowered
        assert "questionnaire" not in lowered
        assert "risk_profile" not in lowered


def test_allocation_policy_yaml_loads_and_is_labelled_synthetic():
    policy = allocation_policy_config()
    assert policy["is_synthetic"] is True
    assert policy["schema_version"] == 1
    assert isinstance(policy["policy_version"], str) and policy["policy_version"]
    assert policy["rationale"]

    required_scenario_keys = {
        "id",
        "label",
        "target_exposure",
        "max_direct_stock_sleeve_fraction",
        "eligible_goal_horizon_years_min",
        "eligible_goal_horizon_years_max",
    }
    assert len(policy["scenarios"]) >= 1
    for scenario in policy["scenarios"]:
        assert required_scenario_keys.issubset(scenario.keys())
        exposure_sum = sum(Decimal(str(v)) for v in scenario["target_exposure"].values())
        assert abs(exposure_sum - Decimal("1")) < Decimal("0.01")

    assert "issuer_concentration_limit" in policy
