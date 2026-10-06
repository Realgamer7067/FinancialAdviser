"""V3 Phase 05 integration: exposes allocation_engine.py + capacity_policy.py
+ allocation_policy.yaml through a real API. Explicitly labelled synthetic --
allocation_policy.yaml has no reviewed/approved sign-off (see its own header
and docs/v3-execution/STATE.md's unresolved-external-input list). This
endpoint must never claim personalized/optimal suitability; it demonstrates
the deterministic engine against a user-supplied exposure and scenario
choice, not a policy-reviewed recommendation.

Deliberately does NOT auto-derive current_exposure from Phase 03's holdings
(HoldingPosition has no asset-class classification field yet -- inventing
one here would be a fabricated mapping, not a real one) -- the caller
supplies current_exposure directly. A later phase adds real classification.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.config import allocation_policy_config
from app.services.allocation_engine import (
    AllocationPlan,
    ConstraintResult,
    ExposureBreakdown,
    rounding_and_fallback,
    target_gap_allocation,
    validate_constraints,
)

router = APIRouter(prefix="/api/plans", tags=["plans"])


class PlanRequest(BaseModel):
    scenario_id: str
    current_exposure: dict[str, str]  # asset_class -> Decimal-as-string amount
    new_cash: str

    @field_validator("new_cash")
    @classmethod
    def _valid_decimal(cls, v: str) -> str:
        try:
            Decimal(v)
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal amount: {v!r}") from exc
        return v


class ConstraintResultOut(BaseModel):
    name: str
    satisfied: bool
    detail: str


class PlanOut(BaseModel):
    is_synthetic: bool
    policy_version: str
    scenario_id: str
    scenario_label: str
    total_planning_wealth: str
    current_exposure: dict[str, str]
    target_exposure: dict[str, str]
    proposed_contributions: dict[str, str]
    unallocated_cash: str
    method: str
    shortfall_note: str | None
    constraint_results: list[ConstraintResultOut]


def _find_scenario(policy: dict, scenario_id: str) -> dict:
    for scenario in policy.get("scenarios", []):
        if scenario["id"] == scenario_id:
            return scenario
    valid_ids = [s["id"] for s in policy.get("scenarios", [])]
    raise HTTPException(
        status_code=422, detail=f"unknown scenario_id {scenario_id!r}; valid options: {valid_ids}"
    )


@router.post("", response_model=PlanOut)
async def compute_plan(payload: PlanRequest):
    policy = allocation_policy_config()
    scenario = _find_scenario(policy, payload.scenario_id)

    try:
        current_exposure_decimal = {k: Decimal(v) for k, v in payload.current_exposure.items()}
        new_cash = Decimal(payload.new_cash)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="current_exposure/new_cash must be valid decimal strings")

    if new_cash < 0:
        raise HTTPException(status_code=422, detail="new_cash must be non-negative")

    target_exposure = {k: Decimal(str(v)) for k, v in scenario["target_exposure"].items()}
    current_total = sum(current_exposure_decimal.values(), Decimal("0"))
    total_planning_wealth = current_total + new_cash

    exposure = ExposureBreakdown(by_asset_class=current_exposure_decimal)
    raw_contributions = target_gap_allocation(exposure, target_exposure, new_cash, total_planning_wealth)
    rounded_contributions, unallocated_cash = rounding_and_fallback(raw_contributions, new_cash)

    plan = AllocationPlan(
        policy_version=policy["policy_version"],
        current_exposure=exposure,
        target_exposure=target_exposure,
        deployable_cash=new_cash,
        proposed_contributions=rounded_contributions,
        unallocated_cash=unallocated_cash,
        method="target_gap",
    )

    # No per-symbol weights exist at this layer (this endpoint works at the
    # asset-class level -- Phase 03's HoldingPosition has no asset-class
    # classification yet, and no stock-level proposal exists here either).
    # validate_constraints's stock-cap/issuer checks need per_symbol_weights
    # to mean anything; passing it empty would make every such check
    # trivially "satisfied" -- misleading, not honest. Skip them entirely
    # rather than fabricate a constraint result with no real data behind it.
    constraint_results: list[ConstraintResult] = validate_constraints(plan)

    return PlanOut(
        is_synthetic=bool(policy.get("is_synthetic", True)),
        policy_version=policy["policy_version"],
        scenario_id=scenario["id"],
        scenario_label=scenario["label"],
        total_planning_wealth=str(total_planning_wealth),
        current_exposure={k: str(v) for k, v in current_exposure_decimal.items()},
        target_exposure={k: str(v) for k, v in target_exposure.items()},
        proposed_contributions={k: str(v) for k, v in rounded_contributions.items()},
        unallocated_cash=str(unallocated_cash),
        method=plan.method,
        shortfall_note=plan.shortfall_note,
        constraint_results=[
            ConstraintResultOut(name=c.name, satisfied=c.satisfied, detail=c.detail) for c in constraint_results
        ],
    )


@router.get("/scenarios")
async def list_scenarios():
    policy = allocation_policy_config()
    return {
        "is_synthetic": bool(policy.get("is_synthetic", True)),
        "policy_version": policy["policy_version"],
        "rationale": policy.get("rationale"),
        "scenarios": [
            {"id": s["id"], "label": s["label"], "target_exposure": s["target_exposure"]}
            for s in policy.get("scenarios", [])
        ],
    }
