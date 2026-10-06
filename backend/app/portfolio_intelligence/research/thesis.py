"""Thesis assessment logic (plan section 5.4). Deterministic apart from one
optional mapping step done by a model; everything the model says is validated
before it can matter.

The model's only job: for each user-confirmed condition, point to supported
fact ids and say whether they support / contradict / say nothing about it.
Validation (all deterministic):
- a verdict may only cite fact ids that are in the supported-evidence set;
  otherwise it becomes `no_evidence` and the citation is dropped;
- a `supported`/`contradicted` verdict with no valid citation is `no_evidence`;
- numbers appearing in the model's note must appear in a cited fact; if not,
  the note is suppressed (the verdict stays, the prose goes);
- the aggregate status is computed here by rule, never by the model.

Statuses are qualitative: supported / mixed / weakened / insufficient. There
is no numeric conviction score. `supported` additionally needs at least one
supporting verdict corroborated by >= 2 independent lineages; evidence from a
single source caps the status at `mixed` and says so."""

import re
from typing import Literal

from pydantic import BaseModel, Field

POLICY_VERSION = "thesis-assess-p0-unreviewed"
PROMPT_VERSION = "thesis_map_v1"
STATUSES = ("supported", "mixed", "weakened", "insufficient")

THESIS_MAPPING_PROMPT_V1 = """You map verified evidence to an investor's own thesis conditions. You never judge whether the
investment is good and you never invent facts.

You receive `conditions` (each with an id, text and kind) and `facts` (each with a fact_id and text, all already verified against
real source passages). For EACH condition decide:
- verdict "supported": at least one given fact shows the condition holds;
- verdict "contradicted": at least one given fact shows it does not hold;
- verdict "no_evidence": the facts say nothing relevant (the usual, correct answer when unsure).
Cite ONLY fact_ids you were given, in cited_fact_ids. A supported or contradicted verdict MUST cite at least one fact_id.
`note` is one short plain sentence that may only restate what the cited facts say, with no numbers that are not in them.
No scores, no probabilities, no recommendation."""


class ConditionVerdict(BaseModel):
    condition_id: str
    verdict: Literal["supported", "contradicted", "no_evidence"]
    cited_fact_ids: list[str] = Field(default_factory=list)
    note: str = ""


class VerdictSet(BaseModel):
    verdicts: list[ConditionVerdict]


_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUM.findall(text or "")}


def validate_verdicts(conditions: list[dict], verdicts: list[ConditionVerdict], provenance: dict[str, dict]) -> list[dict]:
    """One result per condition, in the user's order. Only SUPPORTED facts count as citable."""
    citable = {fid: p for fid, p in provenance.items() if p["support_status"] == "supported"}
    given = {v.condition_id: v for v in verdicts}
    out = []
    for c in conditions:
        v = given.get(c["id"])
        row = {"condition_id": c["id"], "text": c["text"], "kind": c["kind"], "verdict": "no_evidence", "cited_fact_ids": [],
               "note": "", "independent_sources": 0, "lineages": [], "dropped": []}
        if v is not None:
            valid = [f for f in dict.fromkeys(v.cited_fact_ids) if f in citable]
            invalid = [f for f in v.cited_fact_ids if f not in citable]
            row["dropped"] = [f"cited an unknown or unverified fact ({f[:8]})" for f in invalid]
            if v.verdict != "no_evidence" and valid:
                row["verdict"], row["cited_fact_ids"] = v.verdict, valid
                lineages = sorted({lin for f in valid for lin in citable[f]["lineages"]})
                row["lineages"], row["independent_sources"] = lineages, len(lineages)
                cited_numbers = set().union(*[_numbers(citable[f]["text"]) | _numbers(str(citable[f].get("value") or "")) for f in valid])
                if v.note.strip():
                    extra = _numbers(v.note) - cited_numbers
                    if extra:
                        row["dropped"].append("note removed: it contained numbers not found in the cited evidence")
                    else:
                        row["note"] = v.note.strip()[:300]
            elif v.verdict != "no_evidence":
                row["dropped"].append("verdict ignored: it cited no verified evidence")
    # kind decides what a verdict MEANS for the thesis (see aggregate_status)
        out.append(row)
    return out


def aggregate_status(per_condition: list[dict]) -> tuple[str, list[str]]:
    """Returns (status, reasons). Pure rule; the model never sets it."""
    supports = [c for c in per_condition if c["kind"] == "supports"]
    invalid = [c for c in per_condition if c["kind"] == "invalidates"]
    met = [c for c in supports if c["verdict"] == "supported"]
    failed = [c for c in supports if c["verdict"] == "contradicted"]
    hit = [c for c in invalid if c["verdict"] == "supported"]       # an invalidating condition was observed
    cleared = [c for c in invalid if c["verdict"] == "contradicted"]  # evidence says it has not happened
    reasons: list[str] = []
    if hit:
        reasons.append("an invalidating condition appears to have happened: " + "; ".join(c["text"] for c in hit))
        return "weakened", reasons
    if failed and not met:
        reasons.append("evidence contradicts a condition your thesis relied on: " + "; ".join(c["text"] for c in failed))
        return "weakened", reasons
    if met and not failed:
        corroborated = [c for c in met if c["independent_sources"] >= 2]
        if corroborated:
            reasons.append("conditions met with independent corroboration")
            return "supported", reasons
        reasons.append("conditions met, but only by a single source; independent corroboration is missing")
        return "mixed", reasons
    if met and failed:
        reasons.append("some conditions are met and others contradicted")
        return "mixed", reasons
    if cleared and not met and not failed:
        reasons.append("evidence says an invalidating condition has not happened, but nothing confirms your supporting conditions")
        return "insufficient", reasons
    reasons.append("the evidence found does not address your conditions")
    return "insufficient", reasons


def change_log(prior_status: str | None, new_status: str, per_condition: list[dict], prior_per_condition: list[dict] | None) -> str:
    if prior_status is None:
        return f"First assessment: {new_status}."
    prior = {c["condition_id"]: c["verdict"] for c in (prior_per_condition or [])}
    moved = [f"'{c['text'][:60]}': {prior.get(c['condition_id'], 'new')} -> {c['verdict']}" for c in per_condition
             if prior.get(c["condition_id"]) != c["verdict"]]
    head = "No change in status." if prior_status == new_status else f"Status changed from {prior_status} to {new_status}."
    return head + (" Condition changes: " + "; ".join(moved) + "." if moved else " No condition changed.")
