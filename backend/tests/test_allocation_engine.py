"""Tests for the V3 Phase 05 deterministic allocation engine
(app/services/allocation_engine.py). Section references are to
docs/V3-IMPLEMENTATION-PLAN.md section 6.
"""

from decimal import Decimal

from app.services.allocation_engine import (
    AllocationPlan,
    ExposureBreakdown,
    apply_fund_look_through,
    compute_current_exposure,
    rounding_and_fallback,
    target_gap_allocation,
    validate_constraints,
)


def assert_cash_conserved(contributions: dict[str, Decimal], unallocated: Decimal, original_cash: Decimal) -> None:
    total = sum(contributions.values(), Decimal("0")) + unallocated
    assert total == original_cash, f"cash conservation broken: {total} != {original_cash}"


def test_v3_6_6_worked_fixture_exact():
    """The single most important test: existing 100k at 60/30/10, target
    50/40/10, new 20k -> contribution EXACTLY 0/18000/2000."""

    current = compute_current_exposure(
        {
            "equity": Decimal("60000"),
            "fixed_income": Decimal("30000"),
            "cash": Decimal("10000"),
        }
    )
    target = {
        "equity": Decimal("0.50"),
        "fixed_income": Decimal("0.40"),
        "cash": Decimal("0.10"),
    }
    deployable_cash = Decimal("20000")
    total_planning_wealth = Decimal("120000")

    contributions = target_gap_allocation(current, target, deployable_cash, total_planning_wealth)

    assert contributions["equity"] == Decimal("0")
    assert contributions["fixed_income"] == Decimal("18000")
    assert contributions["cash"] == Decimal("2000")

    unallocated = deployable_cash - sum(contributions.values(), Decimal("0"))
    assert unallocated == Decimal("0")
    assert_cash_conserved(contributions, unallocated, deployable_cash)


def test_target_already_funded_all_cash_unallocated():
    # Note: target fractions here intentionally sum to 0.65, not 1 -- an
    # "other"/unmodeled 30000 slice of current wealth (not tracked by any
    # target class) absorbs the rest. This is required for the scenario to
    # be mathematically possible at all: if target fractions summed to 1
    # and every target class were simultaneously already >= its target,
    # that would force current_total >= W = current_total + C, i.e. C <= 0
    # -- so "already funded AND C > 0" can only happen when the target
    # doesn't claim the entire portfolio.
    current = compute_current_exposure(
        {
            "equity": Decimal("80000"),
            "fixed_income": Decimal("60000"),
            "cash": Decimal("30000"),
            "other": Decimal("30000"),
        }
    )
    target = {
        "equity": Decimal("0.30"),
        "fixed_income": Decimal("0.25"),
        "cash": Decimal("0.10"),
    }
    deployable_cash = Decimal("10000")
    total_planning_wealth = Decimal("210000")

    contributions = target_gap_allocation(current, target, deployable_cash, total_planning_wealth)

    assert all(v == Decimal("0") for v in contributions.values())
    unallocated = deployable_cash - sum(contributions.values(), Decimal("0"))
    assert unallocated == deployable_cash
    assert_cash_conserved(contributions, unallocated, deployable_cash)


def test_oversubscribed_gap_proportional_not_dict_order_greedy():
    """current 70k equity / 20k fi / 10k cash, C=20k, target 50/40/10 ->
    W=120k, targets 60k/48k/12k, gaps 0/28k/2k = 30k > C=20k.
    Gap-proportional split: fi = 20000*28/30 = 18666.66 (ROUND_DOWN),
    cash = 20000*2/30 = 1333.33 (ROUND_DOWN) with dust to alphabetically
    first gapped class ('cash' < 'fixed_income' alphabetically).
    This distinguishes gap-proportional from naive dict-order-greedy
    (which would give fi=20000, cash=0).
    """

    current = compute_current_exposure(
        {
            "equity": Decimal("70000"),
            "fixed_income": Decimal("20000"),
            "cash": Decimal("10000"),
        }
    )
    target = {
        "equity": Decimal("0.50"),
        "fixed_income": Decimal("0.40"),
        "cash": Decimal("0.10"),
    }
    deployable_cash = Decimal("20000")
    total_planning_wealth = Decimal("120000")

    contributions = target_gap_allocation(current, target, deployable_cash, total_planning_wealth)

    assert contributions["equity"] == Decimal("0")
    # Not the greedy dict-order answer:
    assert contributions["fixed_income"] != Decimal("20000")
    assert contributions["cash"] != Decimal("0")

    # Proportional math, dust to alphabetically-first gapped class ("cash").
    assert contributions["fixed_income"] == Decimal("18666.66")
    # cash should absorb the rounding dust so totals hit exactly 20000
    assert contributions["cash"] == deployable_cash - contributions["fixed_income"]

    unallocated = deployable_cash - sum(contributions.values(), Decimal("0"))
    assert unallocated == Decimal("0")
    assert_cash_conserved(contributions, unallocated, deployable_cash)


def test_zero_deployable_cash_no_crash_no_division_by_zero():
    current = compute_current_exposure(
        {
            "equity": Decimal("60000"),
            "fixed_income": Decimal("30000"),
            "cash": Decimal("10000"),
        }
    )
    target = {
        "equity": Decimal("0.50"),
        "fixed_income": Decimal("0.40"),
        "cash": Decimal("0.10"),
    }
    deployable_cash = Decimal("0")
    total_planning_wealth = Decimal("100000")

    contributions = target_gap_allocation(current, target, deployable_cash, total_planning_wealth)

    assert all(v == Decimal("0") for v in contributions.values())
    unallocated = deployable_cash - sum(contributions.values(), Decimal("0"))
    assert unallocated == Decimal("0")
    assert_cash_conserved(contributions, unallocated, deployable_cash)


def test_locked_overweight_holding_makes_target_unreachable_infeasible_retained_cash():
    """Construct the "no permitted deployment" bucket deliberately: equity
    is locked/overweight (already far above its target, buy-only can't fix
    that), and the ONLY class with a genuine gap (fixed_income) is blocked
    by an annual product cap that's already fully used. There is nowhere
    permitted to deploy new cash toward the target, so the caller must
    retain it and report a shortfall rather than force a purchase into a
    capped-out product or silently call the plan compliant.
    """

    current = compute_current_exposure(
        {
            "equity": Decimal("95000"),  # locked, far above its 50% target already
            "fixed_income": Decimal("2000"),
            "cash": Decimal("3000"),
        }
    )
    target = {
        "equity": Decimal("0.50"),
        "fixed_income": Decimal("0.40"),
        "cash": Decimal("0.10"),
    }
    deployable_cash = Decimal("5000")
    total_planning_wealth = Decimal("105000")  # 100000 current + 5000 new

    raw_contributions = target_gap_allocation(current, target, deployable_cash, total_planning_wealth)

    # equity already overweight -> zero contribution proposed for it
    assert raw_contributions["equity"] == Decimal("0")
    # fixed_income has the real (and only meaningful) gap
    assert raw_contributions["fixed_income"] > Decimal("0")

    tentative_plan = AllocationPlan(
        policy_version="v1",
        current_exposure=current,
        target_exposure=target,
        deployable_cash=deployable_cash,
        proposed_contributions=raw_contributions,
        unallocated_cash=deployable_cash - sum(raw_contributions.values(), Decimal("0")),
        method="target_gap",
    )

    # The sole product that could absorb the fixed_income gap is already
    # fully used up against its annual cap by other goals this year.
    results = validate_constraints(
        tentative_plan,
        annual_product_caps={"fixed_income": Decimal("2000")},
        existing_product_usage={"fixed_income": Decimal("2000")},
    )
    cap_result = next(r for r in results if r.name.startswith("annual_product_cap"))
    assert cap_result.satisfied is False

    # Because the only under-target class is blocked and equity can't be
    # fixed buy-only, the final plan retains cash instead of forcing the
    # capped purchase.
    final_plan = AllocationPlan(
        policy_version="v1",
        current_exposure=current,
        target_exposure=target,
        deployable_cash=deployable_cash,
        proposed_contributions={k: Decimal("0") for k in target},
        unallocated_cash=deployable_cash,
        constraint_results=results,
        method="infeasible_retained_cash",
        shortfall_note=(
            "equity is locked/overweight at 95000 against a 52500 target and cannot be "
            "reduced buy-only; the only remaining under-target class (fixed_income) is "
            "blocked because its annual product cap (2000) is already fully used by "
            "other goals. No permitted deployment exists for the 5000 deployable cash; "
            "it is retained rather than forced into a capped-out product."
        ),
    )

    assert final_plan.method == "infeasible_retained_cash"
    assert final_plan.shortfall_note is not None
    assert final_plan.unallocated_cash == deployable_cash
    assert all(v == Decimal("0") for v in final_plan.proposed_contributions.values())
    assert_cash_conserved(final_plan.proposed_contributions, final_plan.unallocated_cash, deployable_cash)


def test_fund_look_through_preserves_unknown_remainder_not_redistributed():
    """A fund disclosing only 85% of its holdings' asset-class breakdown
    must preserve exactly 15% (scaled by fund value) as unknown_remainder
    -- proving it does NOT get folded into the known 85%."""

    direct = {"equity": Decimal("10000")}
    fund_value = Decimal("50000")
    fund_fractions = {
        "equity": Decimal("0.60"),
        "fixed_income": Decimal("0.25"),
        # 0.15 undisclosed
    }
    fund_holdings = [(fund_value, fund_fractions)]

    breakdown = apply_fund_look_through(direct, fund_holdings)

    expected_unknown = Decimal("0.15") * fund_value  # 7500
    assert breakdown.unknown_remainder == expected_unknown

    expected_equity = Decimal("10000") + Decimal("0.60") * fund_value  # 10000 + 30000
    expected_fi = Decimal("0.25") * fund_value  # 12500
    assert breakdown.by_asset_class["equity"] == expected_equity
    assert breakdown.by_asset_class["fixed_income"] == expected_fi

    # Total should equal direct + fund_value exactly (nothing lost, nothing
    # invented): known classes + unknown_remainder == direct + fund_value.
    total_known = sum(breakdown.by_asset_class.values(), Decimal("0"))
    assert total_known + breakdown.unknown_remainder == Decimal("10000") + fund_value

    contributions = {"equity": Decimal("0")}  # not exercising cash here
    unallocated = Decimal("0")
    assert_cash_conserved(contributions, unallocated, Decimal("0"))


def test_direct_stock_cap_binding_on_both_total_wealth_and_stock_sleeve():
    current = compute_current_exposure(
        {
            "equity": Decimal("40000"),
            "fixed_income": Decimal("50000"),
            "cash": Decimal("10000"),
        }
    )
    target = {"equity": Decimal("0.40"), "fixed_income": Decimal("0.50"), "cash": Decimal("0.10")}
    deployable_cash = Decimal("0")
    plan = AllocationPlan(
        policy_version="v1",
        current_exposure=current,
        target_exposure=target,
        deployable_cash=deployable_cash,
        proposed_contributions={"equity": Decimal("0"), "fixed_income": Decimal("0"), "cash": Decimal("0")},
        unallocated_cash=deployable_cash,
    )

    # Total wealth = 100000. Stock sleeve = only TCS + INFY = 25000.
    # TCS = 15000 -> 15% of total wealth, 60% of stock sleeve. Cap 15% ->
    # binds (violates) on stock sleeve, right at the edge (satisfies) on
    # total wealth, so both checks must be independently visible.
    per_symbol_weights = {"TCS": Decimal("15000"), "INFY": Decimal("10000")}

    results = validate_constraints(
        plan,
        max_single_stock_weight=Decimal("0.15"),
        per_symbol_weights=per_symbol_weights,
    )

    wealth_result = next(r for r in results if r.name == "direct_stock_cap_total_wealth[TCS]")
    sleeve_result = next(r for r in results if r.name == "direct_stock_cap_stock_sleeve[TCS]")

    assert wealth_result.satisfied is True  # 15000/100000 = 0.15, at the cap, satisfied
    assert sleeve_result.satisfied is False  # 15000/25000 = 0.60, way over the cap

    unallocated = deployable_cash - sum(plan.proposed_contributions.values(), Decimal("0"))
    assert_cash_conserved(plan.proposed_contributions, unallocated, deployable_cash)


def test_annual_product_cap_spans_multiple_goals_not_independent_per_goal():
    """Two separate goal-driven calls both proposing a contribution to the
    SAME capped product must be seen as one combined total, not two
    independent per-goal caps."""

    current = compute_current_exposure({"fixed_income": Decimal("0")})
    target = {"fixed_income": Decimal("1.0")}

    # Goal A's call: proposes 6000 toward "ppf_scheme", cap is 10000, no
    # prior usage from other goals yet.
    deployable_cash_a = Decimal("6000")
    plan_a = AllocationPlan(
        policy_version="v1",
        current_exposure=current,
        target_exposure=target,
        deployable_cash=deployable_cash_a,
        proposed_contributions={"fixed_income": Decimal("6000")},
        unallocated_cash=Decimal("0"),
    )
    results_a = validate_constraints(
        plan_a,
        annual_product_caps={"fixed_income": Decimal("10000")},
        existing_product_usage={},
    )
    cap_a = next(r for r in results_a if r.name.startswith("annual_product_cap"))
    assert cap_a.satisfied is True  # 6000 <= 10000

    # Goal B's call: proposes another 6000 toward the SAME product. If caps
    # were (incorrectly) independent per goal this would also show
    # satisfied; because the cap spans all goals, existing_product_usage
    # carries Goal A's 6000 forward and the combined 12000 > 10000 fails.
    deployable_cash_b = Decimal("6000")
    plan_b = AllocationPlan(
        policy_version="v1",
        current_exposure=current,
        target_exposure=target,
        deployable_cash=deployable_cash_b,
        proposed_contributions={"fixed_income": Decimal("6000")},
        unallocated_cash=Decimal("0"),
    )
    results_b = validate_constraints(
        plan_b,
        annual_product_caps={"fixed_income": Decimal("10000")},
        existing_product_usage={"fixed_income": Decimal("6000")},
    )
    cap_b = next(r for r in results_b if r.name.startswith("annual_product_cap"))
    assert cap_b.satisfied is False  # 6000 + 6000 = 12000 > 10000, correctly combined

    for plan, cash in ((plan_a, deployable_cash_a), (plan_b, deployable_cash_b)):
        unallocated = cash - sum(plan.proposed_contributions.values(), Decimal("0"))
        assert_cash_conserved(plan.proposed_contributions, unallocated, cash)


def test_rounding_and_fallback_minimum_larger_than_gap_zeros_and_redistributes():
    """A minimum purchase amount larger than the naive gap-closing
    contribution rounds that class down to ZERO (buy-only rule stated in
    the module docstring), and the leftover is redistributed to another
    under-target class."""

    proposed = {"cash": Decimal("500"), "fixed_income": Decimal("18000")}
    deployable_cash = Decimal("18500")

    # "cash" product has a minimum purchase of 1000, larger than its
    # proposed 500 -> rounds to zero, 500 freed and redistributed
    # alphabetically: 'cash' < 'fixed_income', but 'cash' is now zeroed
    # (skipped as a below-minimum recipient), so 'fixed_income' absorbs it.
    rounded, unallocated = rounding_and_fallback(
        proposed,
        deployable_cash,
        minimums={"cash": Decimal("1000")},
    )

    assert rounded["cash"] == Decimal("0")
    assert rounded["fixed_income"] == Decimal("18500")  # 18000 + freed 500
    assert unallocated == Decimal("0")
    assert_cash_conserved(rounded, unallocated, deployable_cash)


def test_rounding_and_fallback_increment_rounding_and_conservation():
    proposed = {"equity": Decimal("1234.56"), "fixed_income": Decimal("5000")}
    deployable_cash = Decimal("6234.56")

    rounded, unallocated = rounding_and_fallback(
        proposed,
        deployable_cash,
        increments={"equity": Decimal("100")},
    )

    # 1234.56 rounds down to nearest 100 -> 1200, freeing 34.56, which is
    # redistributed alphabetically: 'equity' still has a nonzero working
    # amount and comes first alphabetically, absorbs freed cash (no
    # increment constraint blocking it further since only equity had one).
    assert rounded["equity"] + rounded["fixed_income"] == deployable_cash - unallocated
    assert_cash_conserved(rounded, unallocated, deployable_cash)


def test_rounding_and_fallback_no_redistribution_target_retains_as_cash():
    """If every recipient of freed cash is itself below-minimum/zeroed,
    the freed cash is retained rather than force-fit anywhere."""

    proposed = {"cash": Decimal("50"), "fixed_income": Decimal("40")}
    deployable_cash = Decimal("90")

    rounded, unallocated = rounding_and_fallback(
        proposed,
        deployable_cash,
        minimums={"cash": Decimal("1000"), "fixed_income": Decimal("1000")},
    )

    assert rounded["cash"] == Decimal("0")
    assert rounded["fixed_income"] == Decimal("0")
    assert unallocated == deployable_cash
    assert_cash_conserved(rounded, unallocated, deployable_cash)


def test_exposure_breakdown_aggregation_basic():
    breakdown = compute_current_exposure(
        {"equity": Decimal("1000"), "cash": Decimal("500")},
        unknown_remainder=Decimal("50"),
    )
    assert breakdown.by_asset_class["equity"] == Decimal("1000")
    assert breakdown.unknown_remainder == Decimal("50")

    contributions = {"equity": Decimal("0")}
    unallocated = Decimal("0")
    assert_cash_conserved(contributions, unallocated, Decimal("0"))
