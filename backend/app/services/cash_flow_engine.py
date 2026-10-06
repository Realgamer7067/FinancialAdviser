"""Versioned, explicit-assumption cash-flow ledger and SIP/goal-projection
engine (V3 Phase 05, docs/V3-IMPLEMENTATION-PLAN.md section 7).

This module sits ALONGSIDE `financial_planning.py` (untouched, unedited) --
it does not replace it. `financial_planning.py` remains the legacy SIP
service for existing callers: float-based, ordinary-annuity (end-of-month),
nominal-annual-rate/12 convention, no initial balance, no fees, no events.
This module reproduces that exact convention as ONE explicit choice
(`RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING`) among several, adds a
second (`RateBasis.EFFECTIVE_ANNUAL`), and generalizes to a real month-by-month
ledger so skipped months, step-ups, maturity payouts and withdrawals can be
modeled explicitly (V3 7.1) instead of being squeezed into a single annual
multiplier.

Design invariant enforced everywhere in this file: every `MonthlyLedgerEntry`
satisfies
    balance_after == balance_before + contribution + growth - fees
and every `ProjectionResult` satisfies
    initial + cumulative_contributions + cumulative_growth - cumulative_fees
        == nominal_final_value
The ledger is the single source of truth for every total below -- nothing is
computed independently from a closed-form shortcut and then left to
(possibly) disagree with the ledger.

This module never talks to an LLM. Pure deterministic Decimal math.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWELVE = Decimal("12")


class RateBasis(str, Enum):
    NOMINAL_ANNUAL_MONTHLY_COMPOUNDING = "nominal_annual_monthly_compounding"  # r = R/12, the legacy convention
    EFFECTIVE_ANNUAL = "effective_annual"  # r = (1+R)^(1/12) - 1, V3 7.2's new option


class AssumptionProvenance(str, Enum):
    USER_SCENARIO = "user_scenario"
    POLICY_SCENARIO = "policy_scenario"
    HISTORICAL_ESTIMATE = "historical_estimate"
    CONTRACTUAL_TERMS = "contractual_terms"


class ContributionTiming(str, Enum):
    BEGINNING_OF_MONTH = "beginning_of_month"
    END_OF_MONTH = "end_of_month"


@dataclass(frozen=True)
class CashFlowEvent:
    """One dated ledger event -- V3 7.1: 'Use cash-flow events, not a single
    annual multiplier, to handle skipped months, step-ups and maturity
    proceeds.'

    `event_type`: "contribution" | "skip" | "step_up" | "maturity_proceeds" | "withdrawal"

    Semantics (documented here since the frozen dataclass has no
    discriminator field beyond `event_type`/`amount`/`note`):
      - "skip": zeroes the contribution for the single month the event
        falls in. Does not affect the base contribution going forward.
      - "step_up": `amount` is the NEW ABSOLUTE monthly contribution
        (not a delta), effective from that event's month onward, until a
        later step_up event supersedes it. V3 7.3 mentions both percentage
        and fixed-amount step-ups; since there is no discriminator field,
        the caller resolves a percentage step-up to an absolute rupee
        amount before constructing the event.
      - "maturity_proceeds": a one-time positive addition to that month's
        cash flow (folded into that `MonthlyLedgerEntry.contribution`, see
        `project_with_events`).
      - "withdrawal": a one-time subtraction from that month's cash flow
        (folded into `contribution` as a negative amount -- this is NOT a
        violation of "never return a negative SIP", which constrains only
        `back_solve_required_contribution`'s return value).
      - "contribution": an ad-hoc one-off top-up added on top of the base
        schedule for that single month.
    """

    event_date: date
    event_type: str
    amount: Decimal
    note: str


@dataclass(frozen=True)
class ProjectionAssumption:
    annual_rate: Decimal  # e.g. Decimal("0.12") for 12%
    rate_basis: RateBasis
    provenance: AssumptionProvenance
    inflation_rate: Decimal | None = None  # for today's-money target conversion


@dataclass(frozen=True)
class MonthlyLedgerEntry:
    month_index: int  # 0-based
    as_of_date: date
    contribution: Decimal
    growth: Decimal  # this month's growth amount, separately visible from contribution
    fees: Decimal
    balance_before: Decimal
    balance_after: Decimal


@dataclass(frozen=True)
class ProjectionResult:
    assumption: ProjectionAssumption
    timing: ContributionTiming
    ledger: list[MonthlyLedgerEntry]
    cumulative_contributions: Decimal
    cumulative_growth: Decimal
    cumulative_fees: Decimal
    nominal_final_value: Decimal
    inflation_adjusted_final_value: Decimal | None  # None if no inflation_rate given
    gap_to_target: Decimal | None  # target - nominal_final_value, clamped at 0 if funded; None if no target given


def _require_finite(value: Decimal, label: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{label} must be a finite Decimal, got {value!r}")


def monthly_rate(assumption: ProjectionAssumption) -> Decimal:
    """r = R/12 for NOMINAL_ANNUAL_MONTHLY_COMPOUNDING (the EXISTING legacy
    convention used by financial_planning.py's `monthly_rate = annual_rate_pct
    / 100 / 12`, i.e. R/12 once R is already expressed as a fraction rather
    than a percentage); r = (1+R)^(1/12) - 1 for EFFECTIVE_ANNUAL.

    Rejects non-finite rates and any rate that would make (1 + monthly rate)
    non-positive (i.e. worse than a total, instantaneous wipeout every
    month), which is the "real but severe loss, not below -100% effective
    annual" edge case boundary from V3 7.4.
    """
    R = assumption.annual_rate
    _require_finite(R, "annual_rate")

    if assumption.rate_basis == RateBasis.NOMINAL_ANNUAL_MONTHLY_COMPOUNDING:
        r = R / _TWELVE
    elif assumption.rate_basis == RateBasis.EFFECTIVE_ANNUAL:
        if R <= Decimal("-1"):
            raise ValueError(
                f"effective annual rate must be greater than -100%, got {R!r}"
            )
        r = (_ONE + R) ** (_ONE / _TWELVE) - _ONE
    else:
        raise ValueError(f"unknown rate_basis {assumption.rate_basis!r}")

    if r <= Decimal("-1"):
        raise ValueError(
            f"resulting monthly rate {r!r} implies a non-positive balance multiplier; "
            "rate is too severely negative"
        )
    return r


def _validate_inflation_rate(inflation_rate: Decimal) -> None:
    _require_finite(inflation_rate, "inflation_rate")
    if inflation_rate <= Decimal("-1"):
        raise ValueError(
            f"inflation_rate must be greater than -100%, got {inflation_rate!r}"
        )


def _add_months(d: date, n: int) -> date:
    """Step a date forward by `n` whole calendar months, clamping the
    day-of-month to the target month's length (so e.g. Jan 31 + 1 month
    lands on Feb 28/29, never overflows). Pure calendar-module stdlib --
    correct across leap years (V3 7.4's Feb 2028 case)."""
    month_index0 = d.month - 1 + n
    year = d.year + month_index0 // 12
    month = month_index0 % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _inflate(amount: Decimal, inflation_rate: Decimal, months: int) -> Decimal:
    years = Decimal(max(months, 0)) / _TWELVE
    return amount * (_ONE + inflation_rate) ** years


def _deflate(amount: Decimal, inflation_rate: Decimal, months: int) -> Decimal:
    years = Decimal(max(months, 0)) / _TWELVE
    return amount / (_ONE + inflation_rate) ** years


def _resolve_target(
    assumption: ProjectionAssumption,
    target_amount: Decimal | None,
    target_basis: str,
    months: int,
) -> Decimal | None:
    if target_amount is None:
        return None
    if target_basis == "today_money":
        if assumption.inflation_rate is None:
            raise ValueError(
                "target_basis='today_money' requires assumption.inflation_rate to be set"
            )
        _validate_inflation_rate(assumption.inflation_rate)
        return _inflate(target_amount, assumption.inflation_rate, months)
    if target_basis == "future_money":
        return target_amount
    raise ValueError(f"unknown target_basis {target_basis!r}, expected 'today_money' or 'future_money'")


def _gap(effective_target: Decimal | None, nominal_final_value: Decimal) -> Decimal | None:
    if effective_target is None:
        return None
    gap = effective_target - nominal_final_value
    return gap if gap > _ZERO else _ZERO


def _run_ledger(
    initial: Decimal,
    months: int,
    r: Decimal,
    timing: ContributionTiming,
    monthly_fee_rate: Decimal,
    contributions: list[Decimal],
    start_date: date,
) -> list[MonthlyLedgerEntry]:
    """Walks the month-by-month ledger. Intra-month order (V3 7.2):
      END_OF_MONTH:       growth on balance_before, then contribution, then fees.
      BEGINNING_OF_MONTH: contribution first, then growth on
                          (balance_before + contribution), then fees.
    Fees are charged on the post-growth, post-contribution balance
    (`fee_base`), which is also how "fees consuming the residual budget"
    (V3 7.4) is modeled -- a large enough `monthly_fee_rate` can make
    `growth - fees` negative for the month.
    """
    ledger: list[MonthlyLedgerEntry] = []
    balance = initial
    n = max(months, 0)
    for i in range(n):
        contribution = contributions[i]
        balance_before = balance
        if timing == ContributionTiming.BEGINNING_OF_MONTH:
            growth = (balance_before + contribution) * r
        else:
            growth = balance_before * r
        fee_base = balance_before + growth + contribution
        fees = fee_base * monthly_fee_rate
        balance_after = fee_base - fees
        as_of_date = _add_months(start_date, i + 1)
        ledger.append(
            MonthlyLedgerEntry(
                month_index=i,
                as_of_date=as_of_date,
                contribution=contribution,
                growth=growth,
                fees=fees,
                balance_before=balance_before,
                balance_after=balance_after,
            )
        )
        balance = balance_after
    return ledger


def _build_result(
    initial: Decimal,
    months: int,
    assumption: ProjectionAssumption,
    timing: ContributionTiming,
    ledger: list[MonthlyLedgerEntry],
    target_amount: Decimal | None,
    target_basis: str,
) -> ProjectionResult:
    cumulative_contributions = sum((e.contribution for e in ledger), _ZERO)
    cumulative_growth = sum((e.growth for e in ledger), _ZERO)
    cumulative_fees = sum((e.fees for e in ledger), _ZERO)
    nominal_final_value = ledger[-1].balance_after if ledger else initial

    inflation_adjusted_final_value: Decimal | None = None
    if assumption.inflation_rate is not None:
        _validate_inflation_rate(assumption.inflation_rate)
        inflation_adjusted_final_value = _deflate(
            nominal_final_value, assumption.inflation_rate, months
        )

    effective_target = _resolve_target(assumption, target_amount, target_basis, months)
    gap_to_target = _gap(effective_target, nominal_final_value)

    return ProjectionResult(
        assumption=assumption,
        timing=timing,
        ledger=ledger,
        cumulative_contributions=cumulative_contributions,
        cumulative_growth=cumulative_growth,
        cumulative_fees=cumulative_fees,
        nominal_final_value=nominal_final_value,
        inflation_adjusted_final_value=inflation_adjusted_final_value,
        gap_to_target=gap_to_target,
    )


def project_fixed_contribution(
    initial: Decimal,
    monthly_contribution: Decimal,
    months: int,
    assumption: ProjectionAssumption,
    timing: ContributionTiming = ContributionTiming.END_OF_MONTH,
    monthly_fee_rate: Decimal = Decimal("0"),
    target_amount: Decimal | None = None,
    target_basis: str = "future_money",
    start_date: date | None = None,
) -> ProjectionResult:
    """Closed-form FV = initial*(1+r)^n + P*((1+r)^n - 1)/r for END_OF_MONTH
    (multiply the annuity term by (1+r) for BEGINNING_OF_MONTH); at r=0 use
    initial + P*n. That closed form is the mathematical basis of this
    function, but the VALUE returned is always read off the month-by-month
    `ledger` built by `_run_ledger` (never computed twice, so there is no
    possibility of the ledger and the summary disagreeing) -- the ledger
    formula naturally reduces to the closed form (no r=0 special case is
    even needed in the walk itself: growth = balance * r is simply 0 when
    r = 0).

    `start_date` is not part of V3 7.2's prose formula but IS required to
    populate `MonthlyLedgerEntry.as_of_date` with real calendar dates
    (needed for the leap-year edge case in V3 7.4); it is added here as a
    trailing keyword-only-by-convention parameter defaulting to
    `date.today()` so every call form the frozen contract shows still
    works unchanged. See the "ambiguity" note in this module's tests file.
    """
    if start_date is None:
        start_date = date.today()
    r = monthly_rate(assumption)
    n = max(months, 0)
    contributions = [monthly_contribution] * n
    ledger = _run_ledger(initial, months, r, timing, monthly_fee_rate, contributions, start_date)
    return _build_result(initial, months, assumption, timing, ledger, target_amount, target_basis)


def _clamp_month_index(idx: int, n: int) -> int:
    if n <= 0:
        return 0
    return min(max(idx, 0), n - 1)


def _month_index_for_date(start_date: date, event_date: date) -> int:
    """0-based index of the ledger month an event falls into, where ledger
    month i covers the period ending at `start_date` + (i+1) months. An
    event dated on or after `start_date`'s day-of-month in a given
    (year, month) belongs to that month's index; earlier in the month
    belongs to the previous one. Callers passing event dates aligned to
    exact month boundaries from `start_date` (the expected common case)
    get an unambiguous mapping; out-of-range dates are clamped to
    [0, months - 1] by the caller.
    """
    idx = (event_date.year - start_date.year) * 12 + (event_date.month - start_date.month)
    if event_date.day < start_date.day:
        idx -= 1
    return idx


def project_with_events(
    initial: Decimal,
    base_monthly_contribution: Decimal,
    months: int,
    assumption: ProjectionAssumption,
    events: list[CashFlowEvent],
    timing: ContributionTiming = ContributionTiming.END_OF_MONTH,
    monthly_fee_rate: Decimal = Decimal("0"),
    target_amount: Decimal | None = None,
    target_basis: str = "future_money",
    start_date: date | None = None,
) -> ProjectionResult:
    """Walks month-by-month applying `events` on top of the base
    contribution. Resolution order (independent of the order `events` is
    passed in, to keep this deterministic):
      1. Start every month at `base_monthly_contribution`.
      2. Apply every "step_up" event in ascending date order: each sets the
         contribution to its (absolute) `amount` for every month from its
         own month onward, until a later step_up supersedes it.
      3. Apply every "skip" event: zeroes that single month's contribution
         (this happens AFTER step-ups are laid down, so a skip always wins
         for its own month regardless of input ordering).
      4. Fold "maturity_proceeds" (+amount), "withdrawal" (-amount) and
         ad-hoc "contribution" (+amount) events into that single month's
         cash flow on top of the schedule from steps 1-3.
    This is the general event-driven case; `project_fixed_contribution` is
    the simple closed-form case. Both share `_run_ledger`/`_build_result`,
    so both produce the same `MonthlyLedgerEntry` shape and satisfy the
    same balance/cumulative identities.
    """
    if start_date is None:
        start_date = date.today()
    r = monthly_rate(assumption)
    n = max(months, 0)

    contributions = [base_monthly_contribution] * n

    step_ups = sorted(
        (e for e in events if e.event_type == "step_up"), key=lambda e: e.event_date
    )
    for e in step_ups:
        idx = _clamp_month_index(_month_index_for_date(start_date, e.event_date), n)
        for j in range(idx, n):
            contributions[j] = e.amount

    for e in events:
        if e.event_type == "skip":
            idx = _clamp_month_index(_month_index_for_date(start_date, e.event_date), n)
            if n > 0:
                contributions[idx] = _ZERO

    for e in events:
        if e.event_type == "maturity_proceeds":
            idx = _clamp_month_index(_month_index_for_date(start_date, e.event_date), n)
            if n > 0:
                contributions[idx] = contributions[idx] + e.amount
        elif e.event_type == "withdrawal":
            idx = _clamp_month_index(_month_index_for_date(start_date, e.event_date), n)
            if n > 0:
                contributions[idx] = contributions[idx] - e.amount
        elif e.event_type == "contribution":
            idx = _clamp_month_index(_month_index_for_date(start_date, e.event_date), n)
            if n > 0:
                contributions[idx] = contributions[idx] + e.amount
        elif e.event_type in ("skip", "step_up"):
            pass  # handled above
        else:
            raise ValueError(f"unknown CashFlowEvent.event_type {e.event_type!r}")

    ledger = _run_ledger(initial, months, r, timing, monthly_fee_rate, contributions, start_date)
    return _build_result(initial, months, assumption, timing, ledger, target_amount, target_basis)


def back_solve_required_contribution(
    initial: Decimal,
    months: int,
    assumption: ProjectionAssumption,
    target_amount: Decimal,
    target_basis: str = "future_money",
) -> Decimal:
    """Solves for the constant end-of-month monthly contribution P that
    exactly reaches target_amount (inflated first if target_basis is
    "today_money"). NEVER returns negative -- if `initial` alone (grown for
    `months` at `assumption`'s rate) already exceeds the (possibly
    inflated) target, returns Decimal("0"). Uses the closed-form FV formula
    solved for P; at r=0, P = (target - initial) / months, clamped at 0.

    `months <= 0` ("past target date", V3 7.4): if the target is already
    funded by `initial` alone, returns Decimal("0") (consistent with
    "target already funded" always returning zero, regardless of how it
    became funded). If NOT already funded and there is no time left to
    contribute, there is no valid constant-P answer -- this raises
    ValueError rather than silently returning 0 and hiding a real
    shortfall (no caller in this phase depends on a graceful non-raising
    return for that combination; a caller that needs a "shortfall" framing
    should catch this and report gap_to_target instead, as
    ProjectionResult already does).
    """
    r = monthly_rate(assumption)
    effective_target = _resolve_target(assumption, target_amount, target_basis, months)
    assert effective_target is not None  # target_amount is required (not Optional) here

    if months <= 0:
        if initial >= effective_target:
            return _ZERO
        raise ValueError(
            "months <= 0 and target is not already funded by `initial` alone; "
            "there is no time left to contribute a constant monthly amount"
        )

    growth_factor = (_ONE + r) ** months
    grown_initial = initial * growth_factor
    if grown_initial >= effective_target:
        return _ZERO

    remaining = effective_target - grown_initial
    if r == _ZERO:
        p = remaining / Decimal(months)
    else:
        annuity_factor = (growth_factor - _ONE) / r
        p = remaining / annuity_factor

    return p if p > _ZERO else _ZERO
