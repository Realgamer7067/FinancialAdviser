"""V3 Phase 05 (docs/V3-IMPLEMENTATION-PLAN.md Sections 6.2 and 15.1) --
deterministic financial CAPACITY and goal-SUITABILITY computation, kept
architecturally separate from company/product research quality.

This module is deliberately new and standalone. It does NOT replace the
existing V2 entangled path (`app/scoring/subscores.py::portfolio_score`
feeding into `app/scoring/final_score.py::compute_final_score` via
`app/pipelines/recommendation_pipeline.py`'s `sub_scores["portfolio"]`) --
that untangling is coordinator follow-up work reviewing all Phase 05
workers together, explicitly out of scope here. See V3 15.1: "Remove the
portfolio contribution from the new assessment policy... Neither a model
explanation nor portfolio weight feeds back into company-quality scoring."

Three inputs this module keeps separate, per V3 5.1:
1. Risk TOLERANCE -- a questionnaire score. Not read by this module at all
   (see `resolve_scenario`'s signature -- it has no risk-tolerance
   parameter, by design).
2. Financial risk CAPACITY -- can the user actually afford it. Computed by
   `compute_capacity` below from cash-flow/reserve inputs.
3. Goal CONSTRAINTS -- horizon, liquidity need. Fed into `resolve_scenario`
   as `goal_horizon_years`.

"A high questionnaire score cannot override a near-term withdrawal
requirement or missing reserve" (V3 5.1) is enforced structurally: this
module never sees a risk-tolerance score to override anything with.
"""

from dataclasses import dataclass
from decimal import Decimal

# A goal horizon below this is treated as "near-term" for the purposes of
# forcing the most conservative eligible scenario, independent of whichever
# scenario the horizon band alone would select. Documented, not derived from
# any reviewed policy -- see allocation_policy.yaml's is_synthetic framing.
NEAR_TERM_HORIZON_YEARS = Decimal("2")


@dataclass(frozen=True)
class CapacityResult:
    """Financial CAPACITY (can they afford it) -- separate from risk
    TOLERANCE (questionnaire score) and from goal CONSTRAINTS (horizon,
    liquidity need). V3 5.1: 'Separate risk tolerance, financial risk
    capacity and goal constraints. A high questionnaire score cannot
    override a near-term withdrawal requirement or missing reserve.'

    Units: `deployable_cash` and `emergency_reserve_shortfall` are both
    one-time lump-sum Rupee amounts (not monthly flows) -- see
    `compute_capacity`'s docstring for the exact formula and why monthly
    income/expense/debt/commitment inputs are folded into a monthly-surplus
    check rather than mixed directly into the lump-sum figure.
    """

    deployable_cash: Decimal  # after reserves/debt-priority policy inputs are subtracted
    emergency_reserve_shortfall: Decimal  # 0 if reserve is adequate, else the gap
    binding_rules: list[str]  # named reasons, e.g. "emergency_reserve_below_3_months_expenses", "near_term_goal_forces_conservative_scenario"


@dataclass(frozen=True)
class SuitabilityResult:
    """Corresponds to V3 15.1's `SuitabilityResult` -- user/goal-specific
    eligibility, computed SEPARATELY from company/product research quality.
    Never feeds back into a company's own assessment score."""

    scenario_id: str  # which allocation_policy.yaml scenario applies
    capacity: CapacityResult
    eligible: bool
    binding_rules: list[str]
    profile_version: int  # V3 10.2: personalized outputs bind to input versions
    policy_version: str


def compute_capacity(
    monthly_income: Decimal | None,
    essential_expenses: Decimal,
    debt_payments: Decimal,
    existing_commitments_total: Decimal,
    one_time_investable_cash: Decimal,
    liquidity_reserve_target_months: Decimal,
    liquidity_reserve_current: Decimal,
    monthly_surplus_confirmed: Decimal | None = None,
) -> CapacityResult:
    """Deterministic capacity computation. No LLM, no lookup -- plain
    arithmetic over user/policy-supplied inputs (V3 6.2: "Emergency reserve
    size and debt-priority thresholds are explicit policy/user inputs").

    Units, spelled out because the frozen signature mixes monthly flows and
    one-time lump sums:

    - `monthly_income`, `essential_expenses`, `debt_payments`,
      `existing_commitments_total`, `monthly_surplus_confirmed` are all
      MONTHLY Rupee flows.
    - `one_time_investable_cash`, `liquidity_reserve_current` are one-time
      lump-sum Rupee amounts (money already in hand).
    - `liquidity_reserve_target_months` is a multiplier (months of
      `essential_expenses` the policy wants held in reserve), not itself a
      Rupee amount.

    Formula implemented:

        monthly_surplus = monthly_surplus_confirmed if monthly_income is None
                           else monthly_income - essential_expenses
                                - debt_payments - existing_commitments_total

        reserve_target = essential_expenses * liquidity_reserve_target_months
        emergency_reserve_shortfall = max(0, reserve_target - liquidity_reserve_current)

        deployable_cash = max(0, one_time_investable_cash - emergency_reserve_shortfall)

    i.e. `deployable_cash` is the one-time lump left over after topping up
    the emergency reserve shortfall out of the same lump (reserve has
    priority -- V3 6.2's explicit reserve/debt-priority policy). Monthly
    income/expenses/debt/commitments do not get added into that lump
    directly (that would be a unit error); instead they only drive
    `monthly_surplus`, which in turn drives `binding_rules` --
    `monthly_surplus_non_positive` if the household has no monthly slack at
    all, which callers may treat as tightening eligibility even when a
    one-time lump exists.

    `monthly_income=None` with `monthly_surplus_confirmed` given is the
    explicit "income unknown but surplus confirmed" case (V3 5.1: "Income
    range alone cannot prove exact affordability; user-confirmed surplus
    can support a constrained plan with that limitation recorded"). That
    limitation is recorded as the binding_rules entry
    "income_unknown_using_confirmed_surplus", not silently proceeded past.
    """
    binding_rules: list[str] = []

    if monthly_income is None:
        if monthly_surplus_confirmed is None:
            raise ValueError(
                "monthly_income is None and monthly_surplus_confirmed is not "
                "provided -- cannot determine monthly surplus from either input."
            )
        monthly_surplus = monthly_surplus_confirmed
        binding_rules.append("income_unknown_using_confirmed_surplus")
    else:
        monthly_surplus = monthly_income - essential_expenses - debt_payments - existing_commitments_total

    if monthly_surplus <= 0:
        binding_rules.append("monthly_surplus_non_positive")

    reserve_target = essential_expenses * liquidity_reserve_target_months
    emergency_reserve_shortfall = max(Decimal("0"), reserve_target - liquidity_reserve_current)
    if emergency_reserve_shortfall > 0:
        binding_rules.append("emergency_reserve_below_target")

    deployable_cash = max(Decimal("0"), one_time_investable_cash - emergency_reserve_shortfall)

    return CapacityResult(
        deployable_cash=deployable_cash,
        emergency_reserve_shortfall=emergency_reserve_shortfall,
        binding_rules=binding_rules,
    )


def _scenario_matches_horizon(scenario: dict, goal_horizon_years: Decimal) -> bool:
    lo = Decimal(str(scenario["eligible_goal_horizon_years_min"]))
    hi = scenario.get("eligible_goal_horizon_years_max")
    if hi is None:
        return goal_horizon_years >= lo
    return lo <= goal_horizon_years < Decimal(str(hi))


def _most_conservative_scenario(scenarios: list[dict]) -> dict:
    # "Most conservative" is derived from the policy's own numbers, not a
    # hardcoded scenario id -- so this keeps working if allocation_policy.yaml's
    # scenarios are edited/reordered/renamed. Lower domestic_equity exposure
    # is more conservative; tie-break on the stock-sleeve cap.
    return min(
        scenarios,
        key=lambda s: (
            Decimal(str(s["target_exposure"]["domestic_equity"])),
            Decimal(str(s["max_direct_stock_sleeve_fraction"])),
        ),
    )


def resolve_scenario(
    policy: dict,  # the parsed allocation_policy.yaml content
    *,
    goal_horizon_years: Decimal,
    capacity: CapacityResult,
    profile_version: int = 0,
) -> SuitabilityResult:
    """Selects the scenario whose horizon band matches goal_horizon_years,
    but a near-term binding rule (e.g. emergency_reserve_shortfall > 0, or
    goal_horizon_years < NEAR_TERM_HORIZON_YEARS) forces the MOST
    conservative eligible scenario regardless of what the horizon band
    alone would pick -- V3 5.1: "A high questionnaire score cannot override
    a near-term withdrawal requirement or missing reserve."

    This function does not read a risk-tolerance questionnaire score AT ALL
    -- that's a deliberately separate input this function's signature
    doesn't even accept, proving the separation V3 15.1 asks for.

    `eligible` is orthogonal to `binding_rules`: a reserve shortfall or
    income-unknown marker being present does not by itself make the result
    ineligible -- it still resolves to a (forced-conservative) usable
    scenario. `eligible=False` is reserved for the case where NO scenario in
    the policy can be resolved at all (no band matches and no scenarios
    exist to fall back to), which does not happen with a well-formed
    3-scenario policy but is guarded against defensively.

    `profile_version` is not part of the frozen contract's shown call shape
    (a keyword-only addition, defaulted to 0) -- added because
    `SuitabilityResult.profile_version` is a required field the contract
    itself declares (V3 10.2: personalized outputs bind to input versions)
    but the shown `resolve_scenario` signature has nowhere else to source it
    from; callers should pass the real profile version once wired in.
    """
    scenarios = policy["scenarios"]
    binding_rules: list[str] = list(capacity.binding_rules)

    near_term = goal_horizon_years < NEAR_TERM_HORIZON_YEARS
    has_reserve_shortfall = capacity.emergency_reserve_shortfall > 0
    force_conservative = near_term or has_reserve_shortfall
    if force_conservative:
        # Single named rule covers both triggers (near-term horizon and/or
        # reserve shortfall) -- the reserve shortfall itself is already
        # separately recorded as "emergency_reserve_below_target" via
        # capacity.binding_rules above.
        binding_rules.append("near_term_goal_forces_conservative_scenario")

    if not scenarios:
        return SuitabilityResult(
            scenario_id="",
            capacity=capacity,
            eligible=False,
            binding_rules=binding_rules,
            profile_version=profile_version,
            policy_version=policy.get("policy_version", ""),
        )

    if force_conservative:
        chosen = _most_conservative_scenario(scenarios)
    else:
        matched = [s for s in scenarios if _scenario_matches_horizon(s, goal_horizon_years)]
        chosen = matched[0] if matched else _most_conservative_scenario(scenarios)

    # dedupe while preserving order
    seen = set()
    deduped_rules = []
    for rule in binding_rules:
        if rule not in seen:
            seen.add(rule)
            deduped_rules.append(rule)

    return SuitabilityResult(
        scenario_id=chosen["id"],
        capacity=capacity,
        eligible=True,
        binding_rules=deduped_rules,
        profile_version=profile_version,
        policy_version=policy.get("policy_version", ""),
    )
