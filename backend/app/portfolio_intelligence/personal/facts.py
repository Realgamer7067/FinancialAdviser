"""Financial facts, behavioural tolerance and capacity constraints (plan
sections 4, 12.5). Pure: no DB. Deterministic; nothing here is inferred from
holdings or broker balances, and unknown stays unknown.

Three separate assessments:
- tolerance: behavioural answers only (NO horizon nudge; the legacy score in
  app/risk/scoring.py stays untouched and is not relabelled).
- capacity: RAW constraints (reserve coverage, surplus, debt service, near-term
  obligations). No qualitative low/moderate/high label until a reviewed policy
  exists; `blocks_risk_increasing_actions` uses only the two rules below.
- requirement: per goal, arrives with goals in Phase 04b."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.risk.scoring import DROP_20PCT_POINTS, LOSS_TOLERANCE_POINTS, PRIORITY_POINTS

CAPACITY_POLICY_VERSION = "capacity-p0-unreviewed"
TOLERANCE_VERSION = "tolerance-behavior-v1"

# Fields that must be known before capacity can be assessed at all.
ESSENTIAL_CAPACITY_FIELDS = ["monthly_income", "monthly_essential_expenses", "emergency_reserve_amount",
                             "emergency_reserve_months_target"]


def _money(v):
    if v is None:
        return None
    d = Decimal(str(v))
    if not d.is_finite() or d < 0:
        raise ValueError("must be a finite, non-negative amount")
    return d


class Obligation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=120)
    amount: Decimal
    due_date: date

    @field_validator("amount")
    @classmethod
    def _pos(cls, v):
        d = _money(v)
        if d == 0:
            raise ValueError("must be greater than zero")
        return d


class ToleranceAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_drop_20pct_reaction: str | None = None
    priority: str | None = None
    loss_tolerance: str | None = None

    @field_validator("portfolio_drop_20pct_reaction")
    @classmethod
    def _a(cls, v):
        if v is not None and v not in DROP_20PCT_POINTS:
            raise ValueError(f"must be one of {sorted(DROP_20PCT_POINTS)}")
        return v

    @field_validator("priority")
    @classmethod
    def _b(cls, v):
        if v is not None and v not in PRIORITY_POINTS:
            raise ValueError(f"must be one of {sorted(PRIORITY_POINTS)}")
        return v

    @field_validator("loss_tolerance")
    @classmethod
    def _c(cls, v):
        if v is not None and v not in LOSS_TOLERANCE_POINTS:
            raise ValueError(f"must be one of {sorted(LOSS_TOLERANCE_POINTS)}")
        return v


class FinancialFacts(BaseModel):
    """Every field optional: null = unknown. Money are Decimals (no floats)."""

    model_config = ConfigDict(extra="forbid")
    monthly_income: Decimal | None = None
    income_stability: Literal["stable", "variable", "uncertain"] | None = None
    monthly_essential_expenses: Decimal | None = None
    dependents: int | None = Field(default=None, ge=0, le=20)
    emergency_reserve_amount: Decimal | None = None  # user-confirmed accessible cash set aside
    emergency_reserve_months_target: Decimal | None = None
    monthly_investable_surplus: Decimal | None = None  # user-confirmed; never derived
    one_time_available: Decimal | None = None
    near_term_obligations: list[Obligation] | None = Field(default=None, max_length=50)
    employer_exposure: str | None = Field(default=None, max_length=120)  # issuer/ISIN of own employer, if any
    knowledge_level: Literal["beginner", "intermediate", "advanced"] | None = None
    tolerance_answers: ToleranceAnswers = Field(default_factory=ToleranceAnswers)

    @field_validator("monthly_income", "monthly_essential_expenses", "emergency_reserve_amount",
                     "emergency_reserve_months_target", "monthly_investable_surplus", "one_time_available")
    @classmethod
    def _m(cls, v):
        return _money(v)


def missing_fields(facts: dict) -> list[str]:
    out = [f for f in ESSENTIAL_CAPACITY_FIELDS if facts.get(f) is None]
    answers = facts.get("tolerance_answers") or {}
    out += [f"tolerance_answers.{k}" for k in ToleranceAnswers.model_fields if answers.get(k) is None]
    return out


def compute_tolerance(answers: dict | None) -> dict:
    answers = answers or {}
    need = {"portfolio_drop_20pct_reaction": DROP_20PCT_POINTS, "priority": PRIORITY_POINTS, "loss_tolerance": LOSS_TOLERANCE_POINTS}
    missing = [k for k, m in need.items() if answers.get(k) not in m]
    if missing:
        return {"status": "unknown", "score": None, "band": None, "missing": missing, "version": TOLERANCE_VERSION}
    score = round(sum(m[answers[k]] for k, m in need.items()) / 3)
    band = "conservative" if score < 34 else "moderate" if score < 67 else "aggressive"
    return {"status": "ready", "score": score, "band": band, "missing": [], "version": TOLERANCE_VERSION,
            "note": "behavioural answers only; not adjusted for horizon or capacity"}


def _fmt(d: Decimal) -> str:
    """Plain decimal string without trailing zeros (DBs differ in numeric scale)."""
    t = format(d.normalize(), "f")
    return t


def _num(x):
    return None if x is None else Decimal(str(x))


def compute_capacity(facts: dict, liabilities: list[dict], today: date | None = None) -> dict:
    """liabilities: active revisions as {monthly_payment, outstanding_amount, rate_type, next_reset_date}."""
    today = today or date.today()
    income, expenses = _num(facts.get("monthly_income")), _num(facts.get("monthly_essential_expenses"))
    reserve, months_target = _num(facts.get("emergency_reserve_amount")), _num(facts.get("emergency_reserve_months_target"))
    surplus_stated = _num(facts.get("monthly_investable_surplus"))

    pay_known = [_num(l.get("monthly_payment")) for l in liabilities]
    debt_payments_unknown = any(p is None for p in pay_known)
    debt_payments = sum((p for p in pay_known if p is not None), Decimal(0))

    missing = [f for f in ESSENTIAL_CAPACITY_FIELDS if facts.get(f) is None]
    out: dict = {"policy_version": CAPACITY_POLICY_VERSION, "missing": missing}

    # essential monthly outgo = essential expenses + known debt payments
    outgo = None if expenses is None else expenses + debt_payments
    out["monthly_essential_outgo"] = None if outgo is None else _fmt(outgo)
    out["debt_payments_incomplete"] = debt_payments_unknown  # some liability has no stated payment
    out["reserve_coverage_months"] = (None if reserve is None or outgo is None or outgo == 0
                                      else str((reserve / outgo).quantize(Decimal("0.1"))))
    out["reserve_target_amount"] = None if months_target is None or outgo is None else str((months_target * outgo).quantize(Decimal("0.01")))
    out["computed_monthly_surplus"] = None if income is None or outgo is None else _fmt(income - outgo)
    out["debt_service_ratio"] = None if income is None or income == 0 else str((debt_payments / income).quantize(Decimal("0.0001")))
    out["stated_investable_surplus"] = None if surplus_stated is None else _fmt(surplus_stated)
    out["stated_surplus_exceeds_computed"] = (
        None if surplus_stated is None or income is None or outgo is None else surplus_stated > (income - outgo))

    horizon = today + timedelta(days=365)
    obligations = facts.get("near_term_obligations") or []
    near = [Decimal(str(o["amount"])) for o in obligations if date.fromisoformat(str(o["due_date"])) <= horizon]
    out["near_term_obligations_12m"] = _fmt(sum(near, Decimal(0))) if facts.get("near_term_obligations") is not None else None
    out["floating_rate_liabilities_without_reset_date"] = sum(
        1 for l in liabilities if l.get("rate_type") == "floating" and not l.get("next_reset_date"))

    # The ONLY blocking rules (unreviewed defaults; see CAPACITY_POLICY_VERSION).
    binding: list[dict] = []
    if missing:
        binding.append({"rule": "capacity_unknown", "detail": f"missing: {', '.join(missing)}"})
    elif out["reserve_coverage_months"] is not None and months_target is not None and Decimal(out["reserve_coverage_months"]) < months_target:
        binding.append({"rule": "reserve_shortfall",
                        "detail": f"reserve covers {out['reserve_coverage_months']} months; target is {months_target}"})
    out["status"] = "capacity_unknown" if missing else "raw_constraints_available"
    out["binding_constraints"] = binding
    out["blocks_risk_increasing_actions"] = bool(binding)
    return out
