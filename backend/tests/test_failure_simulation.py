"""Tests for the Phase 04 failure-simulation harness
(app/services/failure_simulation.py) -- pure arithmetic/routing simulation,
no I/O, no randomness, nothing to mock.
"""

import math

import pytest

from app.services.failure_simulation import (
    ProjectState,
    SimulatedOutcome,
    simulate_dispatch,
    simulate_five_project_outage_scenario,
)


def test_simulate_dispatch_success_when_one_healthy_project_has_budget():
    projects = [
        ProjectState(alias="p1", healthy=False, remaining_daily_budget_usd=10.0),
        ProjectState(alias="p2", healthy=True, remaining_daily_budget_usd=0.05),
    ]
    assert simulate_dispatch(projects, cost_per_call_usd=0.01) == SimulatedOutcome.SUCCESS


def test_simulate_dispatch_exhausted_when_no_eligible_project():
    projects = [
        ProjectState(alias="p1", healthy=False, remaining_daily_budget_usd=100.0),
        ProjectState(alias="p2", healthy=True, remaining_daily_budget_usd=0.001),
    ]
    assert simulate_dispatch(projects, cost_per_call_usd=0.01) == SimulatedOutcome.ALL_PROJECTS_EXHAUSTED


def test_simulate_dispatch_empty_project_list_is_exhausted():
    assert simulate_dispatch([], cost_per_call_usd=0.01) == SimulatedOutcome.ALL_PROJECTS_EXHAUSTED


def test_simulate_dispatch_negative_cost_raises():
    with pytest.raises(ValueError):
        simulate_dispatch([], cost_per_call_usd=-1.0)


def test_outage_scenario_zero_healthy_reports_zero_servable_and_fallback_required():
    result = simulate_five_project_outage_scenario(
        num_healthy=0, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0
    )
    assert result["servable_calls"] == 0
    assert result["fallback_to_cache_required"] is True
    assert result["outcome"] == SimulatedOutcome.ALL_PROJECTS_EXHAUSTED
    assert result["num_healthy"] == 0
    assert result["num_unhealthy"] == 5


def test_outage_scenario_all_five_healthy_reports_full_combined_budget():
    result = simulate_five_project_outage_scenario(
        num_healthy=5, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0
    )
    combined_budget = 5 * 5.0
    expected_calls = math.floor(combined_budget / 0.01 + 1e-9)
    assert result["combined_budget_usd"] == combined_budget
    assert result["servable_calls"] == expected_calls
    assert result["fallback_to_cache_required"] is False
    assert result["outcome"] == SimulatedOutcome.SUCCESS


def test_outage_scenario_partial_healthy_scales_linearly():
    two_healthy = simulate_five_project_outage_scenario(
        num_healthy=2, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0
    )
    four_healthy = simulate_five_project_outage_scenario(
        num_healthy=4, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0
    )
    assert four_healthy["servable_calls"] == 2 * two_healthy["servable_calls"]


def test_outage_scenario_out_of_range_num_healthy_raises():
    with pytest.raises(ValueError):
        simulate_five_project_outage_scenario(num_healthy=6, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0)
    with pytest.raises(ValueError):
        simulate_five_project_outage_scenario(
            num_healthy=-1, cost_per_call_usd=0.01, daily_budget_per_project_usd=5.0
        )


def test_outage_scenario_nonpositive_cost_raises():
    with pytest.raises(ValueError):
        simulate_five_project_outage_scenario(num_healthy=3, cost_per_call_usd=0.0, daily_budget_per_project_usd=5.0)


def test_outage_scenario_budget_too_small_for_one_call_requires_fallback():
    result = simulate_five_project_outage_scenario(
        num_healthy=1, cost_per_call_usd=10.0, daily_budget_per_project_usd=1.0
    )
    assert result["servable_calls"] == 0
    assert result["fallback_to_cache_required"] is True
