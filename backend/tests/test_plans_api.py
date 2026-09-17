"""POST /api/plans -- V3 Phase 05 integration (allocation_engine.py +
allocation_policy.yaml exposed as a real endpoint). Exact allocation math is
already exhaustively tested in test_allocation_engine.py; this covers the
API wiring: request/response shape, cash conservation end-to-end, unknown
scenario handling, and the is_synthetic honesty flag."""

from decimal import Decimal


async def test_plan_computes_gap_closing_contribution_and_conserves_cash(client):
    res = await client.post(
        "/api/plans",
        json={
            "scenario_id": "moderate_capacity_medium_horizon",
            "current_exposure": {"domestic_equity": "60000", "fixed_income": "30000", "cash": "10000"},
            "new_cash": "20000",
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["is_synthetic"] is True
    assert body["scenario_id"] == "moderate_capacity_medium_horizon"

    contributions = {k: Decimal(v) for k, v in body["proposed_contributions"].items()}
    unallocated = Decimal(body["unallocated_cash"])
    # Cash conservation: contributions + unallocated must equal exactly the new cash.
    assert sum(contributions.values(), Decimal("0")) + unallocated == Decimal("20000")


async def test_plan_unknown_scenario_id_rejected(client):
    res = await client.post(
        "/api/plans",
        json={"scenario_id": "not_a_real_scenario", "current_exposure": {"cash": "1000"}, "new_cash": "500"},
    )
    assert res.status_code == 422


async def test_plan_negative_new_cash_rejected(client):
    res = await client.post(
        "/api/plans",
        json={
            "scenario_id": "moderate_capacity_medium_horizon",
            "current_exposure": {"cash": "1000"},
            "new_cash": "-500",
        },
    )
    assert res.status_code == 422


async def test_list_scenarios_returns_synthetic_flag_and_scenarios(client):
    res = await client.get("/api/plans/scenarios")
    assert res.status_code == 200
    body = res.json()
    assert body["is_synthetic"] is True
    assert len(body["scenarios"]) >= 1
    assert all("id" in s and "target_exposure" in s for s in body["scenarios"])


async def test_plan_with_zero_new_cash_gives_zero_contributions(client):
    # With positive new_cash, total_planning_wealth grows by that amount, so
    # by construction at least one class's target (a fraction of the NEW,
    # larger total) exceeds its current amount -- "every class already
    # funded" is only representable with new_cash=0. That's correct
    # allocation math (pigeonhole on the target fractions summing to 100%
    # of a strictly larger base), not a test artifact to route around.
    res = await client.post(
        "/api/plans",
        json={
            "scenario_id": "growth_capacity_long_horizon",
            "current_exposure": {"domestic_equity": "700000", "fixed_income": "200000", "cash": "100000"},
            "new_cash": "0",
        },
    )
    assert res.status_code == 200
    body = res.json()
    contributions = {k: Decimal(v) for k, v in body["proposed_contributions"].items()}
    assert all(v == Decimal("0") for v in contributions.values())
    assert Decimal(body["unallocated_cash"]) == Decimal("0")
