"""Lightweight failure-simulation harness for Phase 04 benchmarking (V3
Section 12.3's failure-scenario table).

This is a self-contained, deterministic call-routing simulator for
benchmarking/testing purposes -- it is NOT the real scheduler's failure
handling (that lives in the parallel-owned model_scheduler/model_adapter
modules, which this module does not import or depend on). No I/O, no
randomness, no network-failure modeling: given a snapshot of project
states, it just decides whether a dispatch could succeed.
"""

import math
from dataclasses import dataclass
from enum import Enum

_FLOAT_EPSILON = 1e-9


class SimulatedOutcome(str, Enum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    ALL_PROJECTS_EXHAUSTED = "all_projects_exhausted"


@dataclass
class ProjectState:
    alias: str
    healthy: bool
    remaining_daily_budget_usd: float


def simulate_dispatch(projects: list[ProjectState], cost_per_call_usd: float) -> SimulatedOutcome:
    """Pure function: given a list of project states, decides the outcome of
    attempting one dispatch. No healthy project with enough remaining budget
    -> ALL_PROJECTS_EXHAUSTED. At least one eligible project -> SUCCESS (this
    is a call-routing simulation, not a real network-failure simulator --
    keep it simple and deterministic, no randomness).
    """
    if cost_per_call_usd < 0:
        raise ValueError("cost_per_call_usd must be >= 0")

    for project in projects:
        if project.healthy and project.remaining_daily_budget_usd >= cost_per_call_usd:
            return SimulatedOutcome.SUCCESS

    return SimulatedOutcome.ALL_PROJECTS_EXHAUSTED


def simulate_five_project_outage_scenario(
    num_healthy: int, cost_per_call_usd: float, daily_budget_per_project_usd: float
) -> dict:
    """Given a count of currently-healthy projects (0-5) out of 5 total, each
    with the same daily_budget_per_project_usd, returns a dict summarizing
    how many calls the remaining healthy projects can serve before
    ALL_PROJECTS_EXHAUSTED, and at what point the system must fall back to
    cached evidence (per V3 section 12.3: "All projects unavailable | Serve
    valid cached evidence with dates or return partial/queued status; never
    pretend live synthesis succeeded"). Pure arithmetic, no I/O.
    """
    total_projects = 5
    if not 0 <= num_healthy <= total_projects:
        raise ValueError(f"num_healthy must be within [0, {total_projects}]")
    if cost_per_call_usd <= 0:
        raise ValueError("cost_per_call_usd must be > 0")
    if daily_budget_per_project_usd < 0:
        raise ValueError("daily_budget_per_project_usd must be >= 0")

    combined_budget_usd = num_healthy * daily_budget_per_project_usd
    # Add a small epsilon before flooring to avoid binary-float artifacts
    # (e.g. 10.0 / 0.01 landing at 999.999999999998 instead of 1000.0).
    servable_calls = math.floor(combined_budget_usd / cost_per_call_usd + _FLOAT_EPSILON)

    fallback_to_cache_required = num_healthy == 0 or servable_calls == 0

    return {
        "total_projects": total_projects,
        "num_healthy": num_healthy,
        "num_unhealthy": total_projects - num_healthy,
        "combined_budget_usd": combined_budget_usd,
        "cost_per_call_usd": cost_per_call_usd,
        "servable_calls": servable_calls,
        "fallback_to_cache_required": fallback_to_cache_required,
        "outcome": (
            SimulatedOutcome.ALL_PROJECTS_EXHAUSTED if fallback_to_cache_required else SimulatedOutcome.SUCCESS
        ),
    }
