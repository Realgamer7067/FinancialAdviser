"""Evidence gathering for a thesis. The default researcher reuses the existing
deterministic research pipeline (retrieval + claim ledger + verification) and
a one-call model mapping; it is an injectable dependency so tests (and any
future source) never need the network. On-demand only: nothing here runs in
the background (automatic thesis alerts wait for vetted source acquisition)."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.single_user import SINGLE_USER_ID
from app.models.research import ResearchBranch
from app.models.theses import Thesis
from app.portfolio_intelligence.research.thesis import PROMPT_VERSION, THESIS_MAPPING_PROMPT_V1, ConditionVerdict, VerdictSet
from app.services.research_orchestrator import run_research_session
from app.services.retrieval import FetchPolicy
from app.services.web_search import discover_branch_urls

logger = logging.getLogger("thesis")

_POLICY = FetchPolicy(allowed_hosts=None, max_bytes=2_000_000, max_pages=None, timeout_seconds=10, max_redirects=3)
_BRANCHES = ("financials_valuation", "events_governance", "peers_downside")


@dataclass
class ResearchOutcome:
    session_id: object | None
    fact_ids: list[str]
    verification: dict | None
    contradictions: list[dict]
    gaps: list[str] = field(default_factory=list)


@dataclass
class MappingOutcome:
    verdicts: list[ConditionVerdict]
    info: dict  # {"used": bool, "model": ..., "prompt_version": ..., "error": ...}


class ThesisResearcher(Protocol):
    async def gather(self, db: AsyncSession, thesis: Thesis) -> ResearchOutcome: ...
    async def map_conditions(self, thesis: Thesis, facts: list[dict]) -> MappingOutcome: ...


def thesis_question(t: Thesis) -> str:
    conds = "; ".join(c["text"] for c in t.conditions)
    return f"{t.symbol}: has anything happened that bears on these points? {conds}"


class DefaultResearcher:
    async def gather(self, db: AsyncSession, thesis: Thesis) -> ResearchOutcome:
        question = thesis_question(thesis)
        urls: dict[str, list[str]] = {}
        for b in _BRANCHES:
            found = await discover_branch_urls(question, b)
            if found:
                urls[b] = found
        result = await run_research_session(
            db, user_id=SINGLE_USER_ID, question=question, instrument_ids=[str(thesis.instrument_id)], cutoff_policy={},
            budget_envelope={"max_fetches": 6}, branch_fetch_urls=urls, retrieval_policy=_POLICY)
        await db.commit()
        v = result.verification
        verification = None if v is None else {
            "total_material_claims": v.total_material_claims, "supported_count": v.supported_count, "unsupported_count": v.unsupported_count,
            "unknown_count": v.unknown_count, "contradicted_count": v.contradicted_count,
            "unresolved_critical_claim_ids": v.unresolved_critical_claim_ids, "fully_verifiable": v.fully_verifiable,
            "caveat": "internal consistency only: not independent corroboration"}
        fact_ids = [str(f) for b in result.branches for f in (b.fact_ids or [])]
        gaps = list(result.named_gaps)
        if not urls:
            gaps.append("no source URLs were found for this question (search unavailable or empty)")
        return ResearchOutcome(result.session.id, fact_ids, verification, result.contradictions, gaps)

    async def map_conditions(self, thesis: Thesis, facts: list[dict]) -> MappingOutcome:
        from app.models_iface.llm import QwenOpenAICompatibleProvider, StructuredOutputError

        payload = {"conditions": [{"id": c["id"], "text": c["text"], "kind": c["kind"]} for c in thesis.conditions],
                   "facts": [{"fact_id": f["fact_id"], "text": f["text"], "period": f["period"]} for f in facts]}
        try:
            result, meta = await QwenOpenAICompatibleProvider().complete_structured(THESIS_MAPPING_PROMPT_V1, payload, VerdictSet, PROMPT_VERSION)
        except StructuredOutputError as exc:
            return MappingOutcome([], {"used": False, "prompt_version": PROMPT_VERSION, "error": str(exc)[:200]})
        return MappingOutcome(result.verdicts, {"used": True, "model": meta.get("model_name"), "prompt_version": PROMPT_VERSION, "error": None})


_default = DefaultResearcher()


def get_thesis_researcher() -> ThesisResearcher:
    return _default
