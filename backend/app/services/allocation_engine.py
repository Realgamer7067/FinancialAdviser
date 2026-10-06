"""Deterministic allocation and target-gap engine (V3 Phase 05,
docs/V3-IMPLEMENTATION-PLAN.md section 6). Pure Python, no LLM calls --
Section 6.2: "They must not be generated per request by a language model."

This module receives already-decided inputs (`target_exposure`,
`deployable_cash`) from a separate policy/suitability worker -- it does not
derive risk profile, eligibility, or capacity itself (see
docs/v3-execution/CONTRACTS.md C4).

All money is `Decimal`. Buy-only: this module never proposes a sale, so a
locked/overweight holding can make a target mathematically unreachable via
new purchases alone -- callers must surface `shortfall_note` rather than
silently calling an incomplete plan "compliant" (V3 6.3).
"""

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class ExposureBreakdown:
    """sum(by_asset_class.values()) + unknown_remainder should equal the
    total wealth this breakdown was computed over, within rounding."""

    by_asset_class: dict[str, Decimal]
    unknown_remainder: Decimal = Decimal("0")


@dataclass(frozen=True)
class ConstraintResult:
    name: str
    satisfied: bool
    detail: str


@dataclass(frozen=True)
class AllocationPlan:
    policy_version: str
    current_exposure: ExposureBreakdown
    target_exposure: dict[str, Decimal]
    deployable_cash: Decimal
    proposed_contributions: dict[str, Decimal]
    unallocated_cash: Decimal
    constraint_results: list[ConstraintResult] = field(default_factory=list)
    method: str = "target_gap"
    shortfall_note: str | None = None


def compute_current_exposure(
    holdings_by_asset_class: dict[str, Decimal],
    unknown_remainder: Decimal = Decimal("0"),
) -> ExposureBreakdown:
    """Aggregate already-classified Decimal amounts. Does NOT resolve an
    instrument to an asset class or do fund look-through -- callers hand in
    pre-classified totals (fund look-through is `apply_fund_look_through`
    below)."""

    return ExposureBreakdown(
        by_asset_class=dict(holdings_by_asset_class),
        unknown_remainder=unknown_remainder,
    )


def apply_fund_look_through(
    direct_exposure_by_asset_class: dict[str, Decimal],
    fund_holdings: list[tuple[Decimal, dict[str, Decimal]]],
) -> ExposureBreakdown:
    """V3 6.4: normalize only documented coverage. Each fund's fraction dict
    need not sum to 1.0 -- whatever fraction is undisclosed becomes unknown,
    scaled by that fund's value, and is added to `unknown_remainder`. It is
    never redistributed into the known asset classes.

    Fund-of-fund recursion / look-through depth limiting is explicitly OUT
    OF SCOPE here: this function receives one flat list of (fund_value,
    fractions) pairs, not nested fund-of-fund data, so there is nothing to
    recurse over. A real depth-limited fund-of-fund resolver is a separate,
    later piece of work (see report).
    """

    merged: dict[str, Decimal] = dict(direct_exposure_by_asset_class)
    unknown_total = Decimal("0")  # direct holdings are always fully classified -> 0 contribution

    for fund_value, fractions in fund_holdings:
        disclosed_fraction = sum(fractions.values(), Decimal("0"))
        for asset_class, frac in fractions.items():
            merged[asset_class] = merged.get(asset_class, Decimal("0")) + frac * fund_value
        undisclosed_fraction = Decimal("1") - disclosed_fraction
        if undisclosed_fraction > 0:
            unknown_total += undisclosed_fraction * fund_value

    return ExposureBreakdown(by_asset_class=merged, unknown_remainder=unknown_total)


def target_gap_allocation(
    current_exposure: ExposureBreakdown,
    target_exposure: dict[str, Decimal],
    deployable_cash: Decimal,
    total_planning_wealth: Decimal,
) -> dict[str, Decimal]:
    """Gap-closing allocation, V3 6.6's worked fixture as the primary
    correctness check. A class already at/above its target amount gets
    ZERO new contribution regardless of its raw share of wealth -- the gap
    drives the split, not the nominal percentage.

    When total gap <= deployable_cash: every gap is closed exactly (this is
    the branch the ₹100k/₹20k/50-40-10 fixture exercises -- ₹0/₹18,000/
    ₹2,000, computed as exact Decimal subtraction, no rounding involved).

    When total gap > deployable_cash (oversubscribed): deployable_cash is
    split proportionally to each class's gap size ("minimizes weighted
    distance from targets" reading of V3 6.3), quantized to paise with
    ROUND_DOWN, and any rounding dust is assigned to the alphabetically
    first class with a positive gap so contributions still sum to exactly
    `deployable_cash` (cash conservation must hold by construction, not by
    luck).
    """

    gaps: dict[str, Decimal] = {}
    for asset_class, target_fraction in target_exposure.items():
        target_amount = target_fraction * total_planning_wealth
        current_amount = current_exposure.by_asset_class.get(asset_class, Decimal("0"))
        gap = target_amount - current_amount
        gaps[asset_class] = gap if gap > 0 else Decimal("0")

    total_gap = sum(gaps.values(), Decimal("0"))

    if total_gap <= 0 or deployable_cash <= 0:
        return {asset_class: Decimal("0") for asset_class in target_exposure}

    if total_gap <= deployable_cash:
        # Every gap can be closed exactly -- no rounding needed.
        return {asset_class: gaps[asset_class] for asset_class in target_exposure}

    # Oversubscribed: proportional split of deployable_cash across gaps.
    contributions: dict[str, Decimal] = {}
    for asset_class in target_exposure:
        if gaps[asset_class] > 0:
            raw = deployable_cash * gaps[asset_class] / total_gap
            contributions[asset_class] = raw.quantize(TWO_PLACES, rounding=ROUND_DOWN)
        else:
            contributions[asset_class] = Decimal("0")

    allocated = sum(contributions.values(), Decimal("0"))
    dust = deployable_cash - allocated
    if dust > 0:
        eligible = sorted(ac for ac in target_exposure if gaps[ac] > 0)
        if eligible:
            contributions[eligible[0]] += dust

    return contributions


def validate_constraints(
    plan: AllocationPlan,
    *,
    max_single_stock_weight: Decimal | None = None,
    per_symbol_weights: dict[str, Decimal] | None = None,
    issuer_concentration_limits: dict[str, Decimal] | None = None,
    annual_product_caps: dict[str, Decimal] | None = None,
    existing_product_usage: dict[str, Decimal] | None = None,
) -> list[ConstraintResult]:
    """INDEPENDENT final validator -- re-checks every constraint from
    scratch against the plan's ACTUAL numbers. Deliberately separate from
    `target_gap_allocation` (V3 6.1 step 9). Must be run on every plan,
    including `equal_weight_fallback` / `infeasible_retained_cash` plans.

    `per_symbol_weights` is a dict of symbol -> proposed rupee AMOUNT (not
    a pre-computed fraction) so this function can derive both binding
    denominators itself: total planning wealth W (derived here as
    sum(current by_asset_class) + unknown_remainder + deployable_cash,
    since `AllocationPlan` carries no separate W field) and the direct
    stock sleeve (sum of all `per_symbol_weights`). A cap can bind on
    either or both -- both are reported as separate, independently
    satisfied/violated `ConstraintResult`s (V3 6.3: "display both when
    binding"), never merged into one.

    `issuer_concentration_limits` is keyed the same way as
    `per_symbol_weights` (issuer id == symbol id in this MVP -- there is no
    symbol->issuer mapping available at this layer yet; a real issuer
    rollup, e.g. two tickers under one promoter group, is a follow-up).

    `annual_product_caps` spans ALL goals/accounts for a product (V3 6.3/
    6.5), not one cap per goal: pass `existing_product_usage` (this
    product's already-committed rupees from OTHER goal-driven calls this
    year) and this function adds the plan's own proposed contribution for
    that product on top before comparing to the cap -- so two separate
    calls contributing toward the same capped product are seen as one
    combined total by whichever caller accumulates `existing_product_usage`
    across calls.
    """

    results: list[ConstraintResult] = []

    total_wealth = (
        sum(plan.current_exposure.by_asset_class.values(), Decimal("0"))
        + plan.current_exposure.unknown_remainder
        + plan.deployable_cash
    )

    per_symbol_weights = per_symbol_weights or {}
    stock_sleeve_total = sum(per_symbol_weights.values(), Decimal("0"))

    if max_single_stock_weight is not None and per_symbol_weights:
        for symbol, amount in per_symbol_weights.items():
            wealth_fraction = amount / total_wealth if total_wealth > 0 else Decimal("0")
            wealth_ok = wealth_fraction <= max_single_stock_weight
            results.append(
                ConstraintResult(
                    name=f"direct_stock_cap_total_wealth[{symbol}]",
                    satisfied=wealth_ok,
                    detail=(
                        f"{symbol}: {wealth_fraction:.4f} of total planning wealth, "
                        f"cap is {max_single_stock_weight:.4f}"
                    ),
                )
            )

            sleeve_fraction = (
                amount / stock_sleeve_total if stock_sleeve_total > 0 else Decimal("0")
            )
            sleeve_ok = sleeve_fraction <= max_single_stock_weight
            results.append(
                ConstraintResult(
                    name=f"direct_stock_cap_stock_sleeve[{symbol}]",
                    satisfied=sleeve_ok,
                    detail=(
                        f"{symbol}: {sleeve_fraction:.4f} of stock sleeve, "
                        f"cap is {max_single_stock_weight:.4f}"
                    ),
                )
            )

    if issuer_concentration_limits:
        for issuer, cap in issuer_concentration_limits.items():
            amount = per_symbol_weights.get(issuer, Decimal("0"))
            fraction = amount / total_wealth if total_wealth > 0 else Decimal("0")
            satisfied = fraction <= cap
            results.append(
                ConstraintResult(
                    name=f"issuer_concentration[{issuer}]",
                    satisfied=satisfied,
                    detail=f"{issuer}: {fraction:.4f} of total planning wealth, cap is {cap:.4f}",
                )
            )

    if annual_product_caps:
        existing_product_usage = existing_product_usage or {}
        for product, cap in annual_product_caps.items():
            already_used = existing_product_usage.get(product, Decimal("0"))
            this_plan_contribution = plan.proposed_contributions.get(product, Decimal("0"))
            combined = already_used + this_plan_contribution
            satisfied = combined <= cap
            results.append(
                ConstraintResult(
                    name=f"annual_product_cap[{product}]",
                    satisfied=satisfied,
                    detail=(
                        f"{product}: cumulative {combined} (existing {already_used} + "
                        f"this plan {this_plan_contribution}) vs cap {cap}"
                    ),
                )
            )

    return results


def rounding_and_fallback(
    proposed_contributions: dict[str, Decimal],
    deployable_cash: Decimal,
    *,
    minimums: dict[str, Decimal] | None = None,
    increments: dict[str, Decimal] | None = None,
) -> tuple[dict[str, Decimal], Decimal]:
    """V3 6.5: round proposed spend down to an affordable permitted amount.

    Rule (stated explicitly, since 6.5 leaves the exact tie-break/rounding
    rule to the implementer): if a class's proposed contribution is below
    that class's `minimums` entry, it rounds down to ZERO (buy-only -- we
    never force a partial purchase below the product minimum), and the
    freed cash becomes a redistribution candidate. Otherwise the
    contribution rounds down to the nearest whole `increments` step for
    that class (no increment entry -> no further rounding).

    Freed cash is redistributed to other classes that still have a nonzero
    working contribution, in alphabetical order, respecting each
    candidate's own increment -- a deterministic tie-break per 6.5. This
    function does not have constraint data (caps, per-symbol weights), so
    it cannot itself verify "every constraint still passes after
    redistribution" (V3 6.5) -- the caller MUST re-run `validate_constraints`
    on the rounded plan; this is a real contract gap, flagged in the
    dispatch report, not silently swept under a fabricated constraint
    check.

    Cash conservation is exact by construction: the returned unallocated
    cash is DERIVED as `deployable_cash - sum(rounded contributions)`,
    never accumulated by a separate running total that could drift.
    """

    minimums = minimums or {}
    increments = increments or {}

    working: dict[str, Decimal] = {}
    freed = Decimal("0")

    for asset_class in sorted(proposed_contributions):
        amount = proposed_contributions[asset_class]
        minimum = minimums.get(asset_class)

        if minimum is not None and amount < minimum:
            working[asset_class] = Decimal("0")
            freed += amount
            continue

        increment = increments.get(asset_class)
        if increment is not None and increment > 0:
            steps = int((amount / increment).to_integral_value(rounding=ROUND_DOWN))
            rounded_amount = Decimal(steps) * increment
        else:
            rounded_amount = amount

        freed += amount - rounded_amount
        working[asset_class] = rounded_amount

    if freed > 0:
        for asset_class in sorted(working):
            if working[asset_class] <= 0:
                continue  # buy-only: don't resurrect a below-minimum class here
            if freed <= 0:
                break
            increment = increments.get(asset_class)
            if increment is not None and increment > 0:
                addable = (freed // increment) * increment
            else:
                addable = freed
            if addable > 0:
                working[asset_class] += addable
                freed -= addable

    final_unallocated_cash = deployable_cash - sum(working.values(), Decimal("0"))
    return working, final_unallocated_cash
