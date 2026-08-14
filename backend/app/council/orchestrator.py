"""Council orchestrator (Section 16). Runs the planner once per recommendation
run, then the 6 analyst roles per candidate. Every call is structured-JSON,
pydantic-validated, and versioned (Section 26) -- failures are surfaced, not
papered over (Section 50)."""

from dataclasses import dataclass

from app.council.prompts import (
    BEAR_SYSTEM,
    BULL_SYSTEM,
    FUNDAMENTAL_SYSTEM,
    JUDGE_SYSTEM,
    PLANNER_SYSTEM,
    PROMPT_VERSION,
    QUANT_SYSTEM,
    RISK_SYSTEM,
)
from app.council.schemas import (
    BearCaseOutput,
    BullCaseOutput,
    FundamentalAssessmentOutput,
    JudgeVerdictOutput,
    PlannerOutput,
    QuantAssessmentOutput,
    RiskAssessmentOutput,
)
from app.models_iface.llm import LLMProvider, StructuredOutputError
from app.scoring.evidence import CandidateEvidence


@dataclass
class RoleResult:
    role: str
    content: dict
    model_name: str
    model_version: str
    prompt_version: str


async def run_planner(llm: LLMProvider, user_profile: dict, market_regime: dict) -> RoleResult | None:
    try:
        result, meta = await llm.complete_structured(
            PLANNER_SYSTEM,
            {"user_profile": user_profile, "market_regime": market_regime},
            PlannerOutput,
            PROMPT_VERSION,
        )
    except StructuredOutputError:
        return None
    return RoleResult("planner", result.model_dump(), meta["model_name"], meta["model_version"], PROMPT_VERSION)


async def run_candidate_council(
    llm: LLMProvider, evidence: CandidateEvidence, user_profile: dict, plan: dict | None
) -> dict[str, RoleResult]:
    """Returns whatever roles succeeded. Missing roles are simply absent from
    the dict -- the caller/judge/scoring layer must treat that as reduced
    model_agreement/data_quality, not crash the candidate (Section 50)."""

    payload_base = {"evidence": evidence.model_dump(), "user_profile": user_profile, "plan": plan}
    results: dict[str, RoleResult] = {}

    role_specs = [
        ("bull", BULL_SYSTEM, BullCaseOutput),
        ("bear", BEAR_SYSTEM, BearCaseOutput),
        ("fundamental", FUNDAMENTAL_SYSTEM, FundamentalAssessmentOutput),
        ("quant", QUANT_SYSTEM, QuantAssessmentOutput),
        ("risk", RISK_SYSTEM, RiskAssessmentOutput),
    ]

    for role, system_prompt, schema in role_specs:
        try:
            result, meta = await llm.complete_structured(system_prompt, payload_base, schema, PROMPT_VERSION)
        except StructuredOutputError:
            continue
        results[role] = RoleResult(role, result.model_dump(), meta["model_name"], meta["model_version"], PROMPT_VERSION)

    judge_payload = {**payload_base, "analyst_outputs": {r: res.content for r, res in results.items()}}
    try:
        judge_result, judge_meta = await llm.complete_structured(
            JUDGE_SYSTEM, judge_payload, JudgeVerdictOutput, PROMPT_VERSION
        )
        results["judge"] = RoleResult(
            "judge", judge_result.model_dump(), judge_meta["model_name"], judge_meta["model_version"], PROMPT_VERSION
        )
    except StructuredOutputError:
        pass  # judge failure just means no rationale text; deterministic score/gate still apply

    return results
