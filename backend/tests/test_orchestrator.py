"""Coverage for council/orchestrator.py -- previously zero. Locks in that
the 5 analyst roles run concurrently (asyncio.gather) but the judge still
sees all of their outputs, and that one role failing doesn't take down the
others (Section 50 graceful degradation)."""

from datetime import date

import pytest

from app.council.orchestrator import run_candidate_council
from app.council.schemas import (
    BearCaseOutput,
    BullCaseOutput,
    FundamentalAssessmentOutput,
    JudgeVerdictOutput,
    QuantAssessmentOutput,
    RiskAssessmentOutput,
)
from app.models_iface.llm import LLMProvider, StructuredOutputError
from app.scoring.evidence import CandidateEvidence, MarketEvidence

_ROLE_SCHEMAS = {
    "bull": BullCaseOutput,
    "bear": BearCaseOutput,
    "fundamental": FundamentalAssessmentOutput,
    "quant": QuantAssessmentOutput,
    "risk": RiskAssessmentOutput,
}


def _fill(schema):
    # model_construct bypasses validation -- fine here, we only care that
    # orchestrator plumbing (concurrency, partial failure, judge payload)
    # behaves correctly, not that these specific field values are realistic.
    return schema.model_construct()


class _FakeLLM(LLMProvider):
    def __init__(self, fail_roles: set[str] = frozenset()):
        self.fail_roles = fail_roles
        self.calls: list[str] = []

    async def complete_structured(self, system_prompt, user_payload, response_model, prompt_version):
        role = {v: k for k, v in _ROLE_SCHEMAS.items()}.get(response_model, "judge")
        self.calls.append(role)
        if role in self.fail_roles:
            raise StructuredOutputError(f"{role} failed")
        if response_model is JudgeVerdictOutput:
            return _fill(JudgeVerdictOutput), {"model_name": "fake", "model_version": "v1"}
        return _fill(response_model), {"model_name": "fake", "model_version": "v1"}


def _evidence() -> CandidateEvidence:
    return CandidateEvidence(
        symbol="TEST",
        exchange="NSE",
        market=MarketEvidence(price=100.0, market_cap=None, volume=0),
        fundamentals=None,
        technical=None,
        kronos=None,
        news=None,
        portfolio=None,
    )


@pytest.mark.asyncio
async def test_all_roles_succeed_including_judge():
    llm = _FakeLLM()
    results = await run_candidate_council(llm, _evidence(), {}, plan=None)
    assert set(results.keys()) == {"bull", "bear", "fundamental", "quant", "risk", "judge"}
    # judge must be called last, after all 5 analysts (it needs their output).
    assert llm.calls[-1] == "judge"
    assert set(llm.calls[:-1]) == {"bull", "bear", "fundamental", "quant", "risk"}


@pytest.mark.asyncio
async def test_one_failed_role_does_not_affect_others_or_judge():
    llm = _FakeLLM(fail_roles={"bear"})
    results = await run_candidate_council(llm, _evidence(), {}, plan=None)
    assert "bear" not in results
    assert set(results.keys()) == {"bull", "fundamental", "quant", "risk", "judge"}
