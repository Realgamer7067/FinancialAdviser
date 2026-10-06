"""Deterministic goal projection (plan sections 5.2, 12.6): low/base/high
POLICY scenarios through the Decimal cash-flow ledger. These are assumptions,
not forecasts or probabilities; there is deliberately no probability field.

Simplifications, stated in every result: contributions are the sum of ACTIVE,
already-started, user-reported commitments (monthly-equivalent, end-of-month);
step-ups are ignored; proposed commitments are shown but excluded; fees and
taxes are excluded."""

from datetime import date
from decimal import Decimal

from app.services.cash_flow_engine import (
    AssumptionProvenance, ContributionTiming, ProjectionAssumption, RateBasis,
    back_solve_required_contribution, project_fixed_contribution,
)

SCENARIO_SET_VERSION = "goal-scenarios-p0-unreviewed"
SCENARIOS = {"low": Decimal("0.04"), "base": Decimal("0.08"), "high": Decimal("0.11")}  # effective annual


def months_until(target: date, today: date) -> int:
    return max((target.year - today.year) * 12 + target.month - today.month, 0)


def required_annual_return(*, target_amount: Decimal, target_basis: str, months: int, inflation: Decimal | None,
                           starting_value: Decimal, monthly_contribution: Decimal, today: date) -> Decimal | None:
    """Smallest effective annual return (0..100%, 0.1% resolution) at which the CURRENT
    value + counted contributions reach the target; None if even 100% would not."""
    def funded(rate: Decimal) -> bool:
        a = ProjectionAssumption(annual_rate=rate, rate_basis=RateBasis.EFFECTIVE_ANNUAL,
                                 provenance=AssumptionProvenance.POLICY_SCENARIO, inflation_rate=inflation)
        r = project_fixed_contribution(starting_value, monthly_contribution, months, a, ContributionTiming.END_OF_MONTH,
                                       target_amount=target_amount, target_basis=target_basis, start_date=today)
        return r.gap_to_target is not None and r.gap_to_target == 0

    lo, hi = Decimal("0"), Decimal("1")
    if funded(lo):
        return lo
    if months <= 0 or not funded(hi):
        return None
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if funded(mid) else (mid, hi)
    return hi.quantize(Decimal("0.001"))


def project_goal(*, target_amount: Decimal, target_basis: str, target_date: date, inflation: Decimal | None,
                 starting_value: Decimal, monthly_contribution: Decimal, today: date | None = None) -> dict:
    today = today or date.today()
    months = months_until(target_date, today)
    out: dict = {"scenario_set": SCENARIO_SET_VERSION, "months": months, "scenarios": {},
                 "note": "Illustrations under stated assumptions, not forecasts or probabilities."}
    if target_basis == "today_money" and inflation is None:
        out["status"] = "needs_input"
        out["missing"] = ["inflation_assumption (target is in today's money)"]
        return out
    out["status"] = "ready"
    for name, rate in SCENARIOS.items():
        a = ProjectionAssumption(annual_rate=rate, rate_basis=RateBasis.EFFECTIVE_ANNUAL,
                                 provenance=AssumptionProvenance.POLICY_SCENARIO, inflation_rate=inflation)
        res = project_fixed_contribution(starting_value, monthly_contribution, months, a, ContributionTiming.END_OF_MONTH,
                                         target_amount=target_amount, target_basis=target_basis, start_date=today)
        try:
            required = back_solve_required_contribution(starting_value, months, a, target_amount, target_basis)
            required_s = format(required.quantize(Decimal("0.01")), "f")
        except ValueError:
            required_s = None  # no time left and unfunded: report the gap instead
        out["scenarios"][name] = {
            "annual_rate": str(rate),
            "projected_value": format(res.nominal_final_value.quantize(Decimal("0.01")), "f"),
            "gap_to_target": None if res.gap_to_target is None else format(res.gap_to_target.quantize(Decimal("0.01")), "f"),
            "required_monthly_contribution": required_s,
            "funded": res.gap_to_target is not None and res.gap_to_target == 0,
        }
    req = required_annual_return(target_amount=target_amount, target_basis=target_basis, months=months, inflation=inflation,
                                 starting_value=starting_value, monthly_contribution=monthly_contribution, today=today)
    out["required_annual_return"] = None if req is None else format(req, "f")
    if req is None or req > SCENARIOS["high"]:
        out["assessment"] = "target_needs_revision"
        out["assessment_message"] = ("Even the high scenario does not reach this target with the current claims and contributions. "
                                     "Revise the target, the date or the contribution; taking more risk is not a fix.")
    elif req > SCENARIOS["base"]:
        out["assessment"] = "needs_higher_return_or_contribution"
        out["assessment_message"] = "Only the high scenario reaches the target. Consider a larger contribution or a later date."
    else:
        out["assessment"] = "reachable_under_base"
        out["assessment_message"] = "The target is reached under the base scenario. This is an illustration, not a forecast."
    out["risk_permission_effect"] = "none"  # a funding gap never raises how much risk is acceptable
    return out
